"""Engine de evaluación de WorkflowRule sobre extracted_json.

Lenguaje de condiciones (subset estilo Airtable filters):

  field    : path al valor a evaluar
  operator : función de comparación
  value    : valor de comparación (puede no aplicar para "exists" / "not_exists")
  case_insensitive: bool (opcional, solo para strings)

Field paths soportados:
  - Cualquier path JSON: "totales.subtotal_ht", "cliente.nombre", "pedido.numero_oferta"
  - Listas con agregación:
      "lineas.count"           → longitud de lineas
      "lineas.sum.cantidad"    → suma de cantidad
      "lineas.sum.importe_linea" → suma de importes
      "lineas.any.<field>"     → True si alguna línea cumple (operador se aplica a c/línea)
      "lineas.all.<field>"     → True si todas cumplen
  - Validación: "validation.summary.blocking", "validation.summary.warnings"

Operadores:
  Numéricos: lt, lte, gt, gte, eq, neq
  String:    contains, not_contains, equals, not_equals, matches (regex)
  Existencia: exists, not_exists, is_null, is_not_null

Acciones (cuando todas las condiciones AND se cumplen):
  - block      → impide aprobación
  - warn       → solo aviso
  - set_status → action_params.status (cambia estado)
  - add_note   → action_params.message (añade nota)
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.models.workflow_rule import RuleAction, RuleScope, WorkflowRule

log = get_logger(__name__)


# =============================================================================
# Resolución de field paths
# =============================================================================


def _resolve_path(data: Any, path: list[str]) -> Any:
    """Camina path simple (sin agregaciones) sobre un dict/list."""
    cur = data
    for part in path:
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                idx = int(part)
                cur = cur[idx] if 0 <= idx < len(cur) else None
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _evaluate_aggregate(
    field: str,
    extracted: dict[str, Any],
) -> tuple[Any, bool] | None:
    """Maneja paths con agregación (count, sum, any, all). Devuelve (valor, is_iter_op)
    o None si no es agregación.

    `is_iter_op=True` significa que el valor es una lista de elementos a evaluar
    individualmente (any/all), no un escalar.
    """
    parts = field.split(".")
    # lineas.count
    if len(parts) == 2 and parts[1] == "count":
        items = _resolve_path(extracted, [parts[0]])
        return (len(items) if isinstance(items, list) else 0, False)

    # lineas.sum.<field>
    if len(parts) == 3 and parts[1] == "sum":
        items = _resolve_path(extracted, [parts[0]])
        if not isinstance(items, list):
            return (0, False)
        total = 0.0
        import contextlib

        for item in items:
            v = _resolve_path(item, [parts[2]])
            if isinstance(v, int | float):
                total += v
            elif isinstance(v, str):
                with contextlib.suppress(ValueError):
                    total += float(v)
        return (total, False)

    # lineas.any.<field> / lineas.all.<field>
    if len(parts) >= 3 and parts[1] in ("any", "all"):
        items = _resolve_path(extracted, [parts[0]])
        if not isinstance(items, list):
            return ([], True)
        sub_path = parts[2:]
        return ([_resolve_path(item, sub_path) for item in items], True)

    return None


def _resolve_field(field: str, extracted: dict[str, Any]) -> tuple[Any, bool]:
    """Devuelve (valor, is_iter) — is_iter=True si el path es any/all."""
    agg = _evaluate_aggregate(field, extracted)
    if agg is not None:
        return agg
    return (_resolve_path(extracted, field.split(".")), False)


# =============================================================================
# Operadores
# =============================================================================


def _to_number(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "."))
        except ValueError:
            return None
    return None


def _eval_op(actual: Any, op: str, expected: Any, *, case_insensitive: bool = False) -> bool:
    if op == "exists":
        return actual is not None
    if op == "not_exists" or op == "is_null":
        return actual is None
    if op == "is_not_null":
        return actual is not None

    # is_blank: vale para campos opcionales (null, string vacío o número 0).
    # Útil para "transporte vacío", "iva sin especificar", etc.
    if op == "is_blank":
        if actual is None:
            return True
        if isinstance(actual, str) and not actual.strip():
            return True
        n = _to_number(actual)
        return n is not None and n == 0
    if op == "is_not_blank":
        if actual is None:
            return False
        if isinstance(actual, str) and not actual.strip():
            return False
        n = _to_number(actual)
        return not (n is not None and n == 0)

    # Numéricos
    if op in ("lt", "lte", "gt", "gte"):
        an = _to_number(actual)
        en = _to_number(expected)
        if an is None or en is None:
            return False
        return {
            "lt": an < en,
            "lte": an <= en,
            "gt": an > en,
            "gte": an >= en,
        }[op]

    if op in ("eq", "equals"):
        an, en = _to_number(actual), _to_number(expected)
        if an is not None and en is not None:
            return an == en
        return _str(actual, case_insensitive) == _str(expected, case_insensitive)
    if op in ("neq", "not_equals"):
        an, en = _to_number(actual), _to_number(expected)
        if an is not None and en is not None:
            return an != en
        return _str(actual, case_insensitive) != _str(expected, case_insensitive)

    # String
    if op == "contains":
        return _str(expected, case_insensitive) in _str(actual, case_insensitive)
    if op == "not_contains":
        return _str(expected, case_insensitive) not in _str(actual, case_insensitive)
    if op == "matches":
        try:
            flags = re.IGNORECASE if case_insensitive else 0
            return re.search(str(expected), _str(actual, False), flags) is not None
        except re.error:
            return False

    log.warning("rules.unknown_operator", operator=op)
    return False


def _str(v: Any, case_insensitive: bool) -> str:
    if v is None:
        return ""
    s = str(v)
    return s.lower() if case_insensitive else s


# =============================================================================
# Evaluación de condiciones y reglas
# =============================================================================


def evaluate_condition(condition: dict[str, Any], extracted: dict[str, Any]) -> bool:
    field = condition.get("field", "")
    op = condition.get("operator", "")
    expected = condition.get("value")
    ci = bool(condition.get("case_insensitive", False))

    actual, is_iter = _resolve_field(field, extracted)
    if not is_iter:
        return _eval_op(actual, op, expected, case_insensitive=ci)

    # Para any/all: actual es lista de valores
    items = actual if isinstance(actual, list) else []
    if ".any." in field:
        return any(_eval_op(v, op, expected, case_insensitive=ci) for v in items)
    if ".all." in field:
        return bool(items) and all(_eval_op(v, op, expected, case_insensitive=ci) for v in items)
    return False


def evaluate_rule(rule: WorkflowRule, extracted: dict[str, Any]) -> bool:
    """True si todas las condiciones AND se cumplen."""
    if not rule.conditions:
        return False
    return all(evaluate_condition(c, extracted) for c in rule.conditions)


# =============================================================================
# Evaluación completa: aplica todas las reglas activas y devuelve resultado
# =============================================================================


def evaluate_rules(
    rules: list[WorkflowRule],
    extracted: dict[str, Any],
    *,
    document_type: str,
) -> dict[str, Any]:
    """Devuelve estructura para `extracted_json.workflow`:

    {
        "blocked": bool,
        "blocking_rules": [{rule_id, name, message}, ...],
        "warnings": [{rule_id, name, message}, ...],
        "notes": [{rule_id, name, message}, ...],
        "status_overrides": [{rule_id, status}],
        "rules_evaluated": int,
        "rules_matched": [rule_id, ...],
    }
    """
    blocked = False
    blocking_rules: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    status_overrides: list[dict[str, Any]] = []
    matched_ids: list[str] = []
    matched_uuid_ids: list[UUID] = []

    # Filtrar por scope + enabled, ordenar por priority asc
    applicable = [
        r
        for r in rules
        if r.enabled and (r.scope == RuleScope.ALL or r.scope.value == document_type)
    ]
    applicable.sort(key=lambda r: r.priority)

    for rule in applicable:
        try:
            if not evaluate_rule(rule, extracted):
                continue
        except Exception as e:
            log.warning("rules.evaluate_failed", rule_id=str(rule.id), error=str(e))
            continue

        matched_ids.append(str(rule.id))
        matched_uuid_ids.append(rule.id)
        message = (rule.action_params or {}).get("message") or rule.description or rule.name
        item = {"rule_id": str(rule.id), "name": rule.name, "message": message}

        if rule.action == RuleAction.BLOCK:
            blocked = True
            blocking_rules.append(item)
        elif rule.action == RuleAction.WARN:
            warnings.append(item)
        elif rule.action == RuleAction.ADD_NOTE:
            notes.append(item)
        elif rule.action == RuleAction.SET_STATUS:
            new_status = (rule.action_params or {}).get("status")
            if new_status:
                status_overrides.append({**item, "status": new_status})

    return {
        "blocked": blocked,
        "blocking_rules": blocking_rules,
        "warnings": warnings,
        "notes": notes,
        "status_overrides": status_overrides,
        "rules_evaluated": len(applicable),
        "rules_matched": matched_ids,
        "_matched_uuid_ids": matched_uuid_ids,  # uso interno para increment_hits
    }
