"""Tests del rules_engine + endpoints workflow-rules."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.models.workflow_rule import RuleAction, RuleScope, WorkflowRule
from app.services.rules_engine import (
    _resolve_field,
    evaluate_condition,
    evaluate_rule,
    evaluate_rules,
)

# =============================================================================
# Field resolution
# =============================================================================


def test_resolve_simple_path() -> None:
    data = {"totales": {"subtotal_ht": 1500, "iva": 315}}
    val, is_iter = _resolve_field("totales.subtotal_ht", data)
    assert val == 1500
    assert is_iter is False


def test_resolve_count() -> None:
    data = {"lineas": [{"a": 1}, {"a": 2}, {"a": 3}]}
    val, _ = _resolve_field("lineas.count", data)
    assert val == 3


def test_resolve_sum() -> None:
    data = {"lineas": [{"cantidad": 2}, {"cantidad": 5}, {"cantidad": 3.5}]}
    val, _ = _resolve_field("lineas.sum.cantidad", data)
    assert val == 10.5


def test_resolve_any() -> None:
    data = {"lineas": [{"descripcion": "Frais"}, {"descripcion": "Transporte FP"}]}
    val, is_iter = _resolve_field("lineas.any.descripcion", data)
    assert is_iter is True
    assert val == ["Frais", "Transporte FP"]


# =============================================================================
# Operators
# =============================================================================


def test_lt_numeric() -> None:
    assert evaluate_condition({"field": "x", "operator": "lt", "value": 100}, {"x": 50}) is True
    assert evaluate_condition({"field": "x", "operator": "lt", "value": 100}, {"x": 100}) is False


def test_contains_case_insensitive() -> None:
    cond = {
        "field": "lineas.any.descripcion",
        "operator": "contains",
        "value": "transporte",
        "case_insensitive": True,
    }
    assert evaluate_condition(cond, {"lineas": [{"descripcion": "Transporte FP"}]}) is True
    assert evaluate_condition(cond, {"lineas": [{"descripcion": "Frais Divers"}]}) is False


def test_not_contains_with_any() -> None:
    """NO existe ninguna línea que contenga el texto."""
    cond = {
        "field": "lineas.any.descripcion",
        "operator": "not_contains",
        "value": "transporte",
        "case_insensitive": True,
    }
    # Si TODAS las descripciones NOT contain → es True para "any" porque
    # cada una individualmente cumple. ¡Pero la semántica de "any.X not_contains Y"
    # es ambigua! El engine evalúa: any(line not_contains "transporte"), que
    # devuelve True si AL MENOS UNA línea no contiene. Eso NO es lo que el
    # usuario quiere. Ver test_business_rule más abajo para la forma correcta.
    assert evaluate_condition(cond, {"lineas": [{"descripcion": "Frais"}]}) is True


def test_exists() -> None:
    assert (
        evaluate_condition(
            {"field": "pedido.numero_oferta", "operator": "exists"},
            {"pedido": {"numero_oferta": "X"}},
        )
        is True
    )
    assert (
        evaluate_condition({"field": "pedido.numero_oferta", "operator": "exists"}, {"pedido": {}})
        is False
    )


# =============================================================================
# Reglas completas
# =============================================================================


def _rule(**kwargs: Any) -> WorkflowRule:
    defaults = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "name": "Test rule",
        "enabled": True,
        "priority": 100,
        "scope": RuleScope.ALL,
        "conditions": [],
        "action": RuleAction.WARN,
        "action_params": {},
    }
    defaults.update(kwargs)
    return WorkflowRule(**defaults)


def test_rule_all_conditions_must_pass() -> None:
    rule = _rule(
        conditions=[
            {"field": "totales.subtotal_ht", "operator": "lt", "value": 2500},
            {"field": "lineas.count", "operator": "gte", "value": 1},
        ]
    )
    assert evaluate_rule(rule, {"totales": {"subtotal_ht": 1500}, "lineas": [{}]}) is True
    assert evaluate_rule(rule, {"totales": {"subtotal_ht": 5000}, "lineas": [{}]}) is False
    assert evaluate_rule(rule, {"totales": {"subtotal_ht": 1500}, "lineas": []}) is False


def test_business_rule_transporte_obligatorio() -> None:
    """Caso real: bloquear pedidos < 2500€ sin línea de transporte.

    La condición correcta es: 'lineas.all.descripcion not_contains transporte'
    (todas las líneas NO contienen "transporte" → ninguna es transporte).
    """
    rule = _rule(
        name="Transporte obligatorio bajo 2500€",
        action=RuleAction.BLOCK,
        action_params={"message": "Pedidos < 2500€ deben incluir transporte"},
        conditions=[
            {"field": "totales.subtotal_ht", "operator": "lt", "value": 2500},
            {
                "field": "lineas.all.descripcion",
                "operator": "not_contains",
                "value": "transporte",
                "case_insensitive": True,
            },
        ],
    )

    # Caso 1: pedido pequeño SIN línea de transporte → DEBE bloquear
    pedido_sin_transporte = {
        "totales": {"subtotal_ht": 1500},
        "lineas": [
            {"descripcion": "Tubo TF-75"},
            {"descripcion": "Goma GF-1"},
        ],
    }
    assert evaluate_rule(rule, pedido_sin_transporte) is True

    # Caso 2: pedido pequeño CON transporte → NO bloquea
    pedido_con_transporte = {
        "totales": {"subtotal_ht": 1500},
        "lineas": [
            {"descripcion": "Tubo TF-75"},
            {"descripcion": "Costes de Transporte (FP)"},
        ],
    }
    assert evaluate_rule(rule, pedido_con_transporte) is False

    # Caso 3: pedido grande sin transporte → NO bloquea (Quimilock asume transporte)
    pedido_grande = {
        "totales": {"subtotal_ht": 5000},
        "lineas": [{"descripcion": "Tubo TF-75"}],
    }
    assert evaluate_rule(rule, pedido_grande) is False


def test_evaluate_rules_action_routing() -> None:
    rule_block = _rule(
        name="Bloqueante",
        action=RuleAction.BLOCK,
        action_params={"message": "X bloqueante"},
        conditions=[{"field": "x", "operator": "eq", "value": 1}],
    )
    rule_warn = _rule(
        name="Aviso",
        action=RuleAction.WARN,
        action_params={"message": "Y aviso"},
        conditions=[{"field": "y", "operator": "eq", "value": 1}],
    )
    result = evaluate_rules([rule_block, rule_warn], {"x": 1, "y": 1}, document_type="pedido")
    assert result["blocked"] is True
    assert len(result["blocking_rules"]) == 1
    assert len(result["warnings"]) == 1
    assert result["rules_evaluated"] == 2


def test_evaluate_rules_filters_by_scope() -> None:
    rule_only_pedido = _rule(
        scope=RuleScope.PEDIDO,
        conditions=[{"field": "x", "operator": "eq", "value": 1}],
    )
    result_oferta = evaluate_rules([rule_only_pedido], {"x": 1}, document_type="oferta")
    assert result_oferta["rules_evaluated"] == 0
    result_pedido = evaluate_rules([rule_only_pedido], {"x": 1}, document_type="pedido")
    assert result_pedido["rules_evaluated"] == 1


def test_evaluate_rules_skips_disabled() -> None:
    rule = _rule(
        enabled=False,
        conditions=[{"field": "x", "operator": "eq", "value": 1}],
    )
    result = evaluate_rules([rule], {"x": 1}, document_type="pedido")
    assert result["rules_evaluated"] == 0


# =============================================================================
# Endpoints CRUD
# =============================================================================


@pytest.fixture
def tenant_id(client: TestClient) -> UUID:
    r = client.post("/api/v1/tenants", json={"name": "Q", "slug": "q"})
    return UUID(r.json()["id"])


def _auth(t: UUID) -> dict[str, str]:
    return {"X-Tenant-Id": str(t)}


def test_create_and_list_rule(client: TestClient, tenant_id: UUID) -> None:
    payload = {
        "name": "Transporte obligatorio",
        "scope": "pedido",
        "action": "block",
        "action_params": {"message": "Falta transporte"},
        "conditions": [{"field": "totales.subtotal_ht", "operator": "lt", "value": 2500}],
    }
    r = client.post("/api/v1/workflow-rules", json=payload, headers=_auth(tenant_id))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Transporte obligatorio"
    assert body["enabled"] is True

    r = client.get("/api/v1/workflow-rules", headers=_auth(tenant_id))
    assert len(r.json()) == 1


def test_test_rule_endpoint(client: TestClient, tenant_id: UUID) -> None:
    """El endpoint /test evalúa sin persistir."""
    payload = {
        "rule": {
            "name": "test",
            "scope": "pedido",
            "action": "warn",
            "conditions": [{"field": "totales.subtotal_ht", "operator": "lt", "value": 2500}],
        },
        "extracted_json": {"totales": {"subtotal_ht": 1000}, "lineas": []},
        "document_type": "pedido",
    }
    r = client.post("/api/v1/workflow-rules/test", json=payload, headers=_auth(tenant_id))
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["rules_evaluated"] == 1
    assert len(result["rules_matched"]) == 1
    # No debe haber creado nada
    r = client.get("/api/v1/workflow-rules", headers=_auth(tenant_id))
    assert r.json() == []


def test_validation_empty_conditions(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/workflow-rules",
        json={"name": "x", "conditions": [], "action": "warn"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 400
