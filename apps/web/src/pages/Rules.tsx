import { useCallback, useEffect, useState } from "react";
import { Workflow, Plus, Trash2, RefreshCw, Save, X, Power, PowerOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { getTenantId, rulesApi } from "@/lib/api";
import type {
  RuleAction,
  RuleCondition,
  RuleOperator,
  RuleScope,
  WorkflowRuleCreate,
  WorkflowRuleRead,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// =============================================================================
// Catálogo de fields y operadores (selectables en el editor)
// =============================================================================

const FIELDS: Array<{ value: string; label: string; group: string; type: "number" | "string" | "exists" }> = [
  // Totales
  { value: "totales.subtotal_ht", label: "Subtotal HT (€)", group: "Totales", type: "number" },
  { value: "totales.iva", label: "IVA", group: "Totales", type: "number" },
  { value: "totales.total_ttc", label: "Total TTC (€)", group: "Totales", type: "number" },
  // Cliente
  { value: "cliente.nombre", label: "Nombre cliente", group: "Cliente", type: "string" },
  { value: "cliente.cif_nif", label: "CIF / NIF", group: "Cliente", type: "string" },
  { value: "cliente.contacto_email", label: "Email contacto", group: "Cliente", type: "string" },
  // Pedido
  { value: "pedido.numero_oferta", label: "Nº oferta", group: "Pedido", type: "string" },
  { value: "pedido.numero_pedido_cliente", label: "Nº pedido cliente", group: "Pedido", type: "string" },
  { value: "pedido.observaciones", label: "Observaciones", group: "Pedido", type: "string" },
  // Líneas (agregaciones)
  { value: "lineas.count", label: "Nº de líneas", group: "Líneas", type: "number" },
  { value: "lineas.sum.cantidad", label: "Suma cantidades", group: "Líneas", type: "number" },
  { value: "lineas.sum.importe_linea", label: "Suma importes", group: "Líneas", type: "number" },
  { value: "lineas.any.descripcion", label: "ALGUNA línea (descripción)", group: "Líneas", type: "string" },
  { value: "lineas.all.descripcion", label: "TODAS las líneas (descripción)", group: "Líneas", type: "string" },
  { value: "lineas.any.referencia", label: "ALGUNA línea (referencia)", group: "Líneas", type: "string" },
  // Validación
  { value: "validation.summary.blocking", label: "Validación: nº bloqueantes", group: "Validación", type: "number" },
  { value: "validation.summary.warnings", label: "Validación: nº avisos", group: "Validación", type: "number" },
];

const OPERATORS: Array<{ value: RuleOperator; label: string; types: ("number" | "string" | "exists")[] }> = [
  { value: "lt", label: "<", types: ["number"] },
  { value: "lte", label: "≤", types: ["number"] },
  { value: "gt", label: ">", types: ["number"] },
  { value: "gte", label: "≥", types: ["number"] },
  { value: "eq", label: "=", types: ["number", "string"] },
  { value: "neq", label: "≠", types: ["number", "string"] },
  { value: "contains", label: "contiene", types: ["string"] },
  { value: "not_contains", label: "no contiene", types: ["string"] },
  { value: "matches", label: "regex", types: ["string"] },
  { value: "exists", label: "existe", types: ["number", "string", "exists"] },
  { value: "not_exists", label: "no existe", types: ["number", "string", "exists"] },
];

const ACTION_LABELS: Record<RuleAction, string> = {
  block: "Bloquear aprobación",
  warn: "Solo aviso",
  set_status: "Cambiar estado",
  add_note: "Añadir nota",
};

const SCOPE_LABELS: Record<RuleScope, string> = {
  all: "Todos los documentos",
  pedido: "Solo pedidos",
  oferta: "Solo ofertas",
};

// =============================================================================
// Página
// =============================================================================

const EMPTY_RULE: WorkflowRuleCreate = {
  name: "",
  description: "",
  enabled: true,
  priority: 100,
  scope: "pedido",
  conditions: [{ field: "totales.subtotal_ht", operator: "lt", value: 2500 }],
  action: "block",
  action_params: { message: "" },
};

export function Rules() {
  const [rules, setRules] = useState<WorkflowRuleRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<WorkflowRuleRead | "new" | null>(null);

  const refresh = useCallback(async () => {
    if (!getTenantId()) return;
    setLoading(true);
    setError(null);
    try {
      setRules(await rulesApi.list());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`¿Eliminar la regla "${name}"?`)) return;
    try {
      await rulesApi.remove(id);
      setRules((prev) => prev.filter((r) => r.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleToggle = async (rule: WorkflowRuleRead) => {
    try {
      const updated = await rulesApi.update(rule.id, { enabled: !rule.enabled });
      setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Workflow className="h-6 w-6 text-indigo-600" />
            Reglas de workflow
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Lógica de negocio que se aplica automáticamente tras la extracción.
            Crea reglas para bloquear, avisar o anotar documentos según condiciones que tú definas.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={refresh} disabled={loading}>
            <RefreshCw className={cn("h-4 w-4 mr-2", loading && "animate-spin")} />
            Refrescar
          </Button>
          <Button onClick={() => setEditing("new")} disabled={!getTenantId()}>
            <Plus className="h-4 w-4 mr-2" /> Nueva regla
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </div>
      )}

      {rules.length === 0 ? (
        <div className="rounded-lg border bg-card p-12 text-center text-muted-foreground">
          <Workflow className="h-10 w-10 mx-auto mb-3 text-muted-foreground/50" />
          <p className="text-sm font-medium text-foreground">Sin reglas configuradas</p>
          <p className="text-xs mt-2 max-w-md mx-auto">
            Crea tu primera regla para automatizar validaciones, por ejemplo:
            "bloquear pedidos &lt; 2500€ que no incluyan línea de transporte".
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {rules.map((rule) => (
            <RuleCard
              key={rule.id}
              rule={rule}
              onEdit={() => setEditing(rule)}
              onDelete={() => handleDelete(rule.id, rule.name)}
              onToggle={() => handleToggle(rule)}
            />
          ))}
        </div>
      )}

      {editing && (
        <RuleEditorModal
          initial={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(saved) => {
            setRules((prev) => {
              const existing = prev.findIndex((r) => r.id === saved.id);
              if (existing >= 0) {
                const next = [...prev];
                next[existing] = saved;
                return next;
              }
              return [...prev, saved];
            });
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}

// =============================================================================
// Tarjeta de regla
// =============================================================================

const ACTION_COLORS: Record<RuleAction, string> = {
  block: "bg-red-100 text-red-900 border-red-300",
  warn: "bg-amber-100 text-amber-900 border-amber-300",
  set_status: "bg-blue-100 text-blue-900 border-blue-300",
  add_note: "bg-zinc-100 text-zinc-700 border-zinc-300",
};

function RuleCard({
  rule,
  onEdit,
  onDelete,
  onToggle,
}: {
  rule: WorkflowRuleRead;
  onEdit: () => void;
  onDelete: () => void;
  onToggle: () => void;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-4 hover:shadow-sm transition-all",
        !rule.enabled && "opacity-60",
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold cursor-pointer hover:underline" onClick={onEdit}>
              {rule.name}
            </h3>
            <span className={cn("inline-block rounded border px-2 py-0.5 text-xs", ACTION_COLORS[rule.action])}>
              {ACTION_LABELS[rule.action]}
            </span>
            <span className="text-xs text-muted-foreground">{SCOPE_LABELS[rule.scope]}</span>
            {rule.hits > 0 && (
              <span className="text-xs bg-emerald-100 text-emerald-900 rounded-full px-2">
                {rule.hits}× aplicada
              </span>
            )}
          </div>
          {rule.description && (
            <p className="text-sm text-muted-foreground mt-1">{rule.description}</p>
          )}
          <div className="mt-2 space-y-0.5 text-xs font-mono text-muted-foreground">
            {rule.conditions.map((c, i) => (
              <div key={i}>
                {i > 0 && <span className="text-amber-700 mr-1">AND</span>}
                <span className="text-foreground">{c.field}</span>{" "}
                <span className="text-blue-700">{c.operator}</span>{" "}
                {c.value !== undefined && c.value !== null && (
                  <span className="text-violet-700">"{String(c.value)}"</span>
                )}
              </div>
            ))}
          </div>
        </div>
        <div className="flex items-start gap-1">
          <button
            onClick={onToggle}
            className={cn(
              "p-1.5 rounded hover:bg-muted",
              rule.enabled ? "text-emerald-700" : "text-muted-foreground",
            )}
            title={rule.enabled ? "Desactivar" : "Activar"}
          >
            {rule.enabled ? <Power className="h-4 w-4" /> : <PowerOff className="h-4 w-4" />}
          </button>
          <button
            onClick={onDelete}
            className="p-1.5 rounded hover:bg-red-50 text-red-600"
            title="Eliminar"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Modal editor de reglas
// =============================================================================

function RuleEditorModal({
  initial,
  onClose,
  onSaved,
}: {
  initial: WorkflowRuleRead | null;
  onClose: () => void;
  onSaved: (rule: WorkflowRuleRead) => void;
}) {
  const [draft, setDraft] = useState<WorkflowRuleCreate>(() =>
    initial
      ? {
          name: initial.name,
          description: initial.description ?? "",
          enabled: initial.enabled,
          priority: initial.priority,
          scope: initial.scope,
          conditions: initial.conditions,
          action: initial.action,
          action_params: initial.action_params,
        }
      : { ...EMPTY_RULE },
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleSave = async () => {
    if (!draft.name.trim()) {
      setErr("El nombre es obligatorio");
      return;
    }
    if (draft.conditions.length === 0) {
      setErr("Debe haber al menos una condición");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const saved = initial
        ? await rulesApi.update(initial.id, draft)
        : await rulesApi.create(draft);
      onSaved(saved);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const updateCondition = (idx: number, patch: Partial<RuleCondition>) => {
    setDraft({
      ...draft,
      conditions: draft.conditions.map((c, i) => (i === idx ? { ...c, ...patch } : c)),
    });
  };

  const addCondition = () => {
    setDraft({
      ...draft,
      conditions: [
        ...draft.conditions,
        { field: "totales.subtotal_ht", operator: "lt", value: 0 },
      ],
    });
  };

  const removeCondition = (idx: number) => {
    setDraft({ ...draft, conditions: draft.conditions.filter((_, i) => i !== idx) });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm overflow-auto p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-2xl rounded-lg border bg-white shadow-xl p-5 space-y-4 my-auto">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold">{initial ? "Editar regla" : "Nueva regla"}</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Las reglas se evalúan tras la extracción. Si todas las condiciones se cumplen, se aplica la acción.
            </p>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground p-1">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs font-medium uppercase text-muted-foreground">Nombre</label>
            <input
              autoFocus
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder="Transporte obligatorio bajo 2500€"
              className="mt-1 w-full rounded border px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="text-xs font-medium uppercase text-muted-foreground">Aplicar a</label>
            <select
              value={draft.scope}
              onChange={(e) => setDraft({ ...draft, scope: e.target.value as RuleScope })}
              className="mt-1 w-full rounded border px-3 py-2 text-sm bg-white"
            >
              {(Object.keys(SCOPE_LABELS) as RuleScope[]).map((s) => (
                <option key={s} value={s}>
                  {SCOPE_LABELS[s]}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="text-xs font-medium uppercase text-muted-foreground">
            Descripción <span className="normal-case opacity-70">(opcional)</span>
          </label>
          <input
            value={draft.description ?? ""}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            placeholder="Por qué existe esta regla, contexto del negocio..."
            className="mt-1 w-full rounded border px-3 py-2 text-sm"
          />
        </div>

        {/* Condiciones */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-xs font-medium uppercase text-muted-foreground">
              Si (todas las condiciones AND)
            </label>
            <Button size="sm" variant="ghost" onClick={addCondition}>
              <Plus className="h-3 w-3 mr-1" /> Condición
            </Button>
          </div>
          {draft.conditions.map((cond, idx) => (
            <ConditionEditor
              key={idx}
              condition={cond}
              onChange={(patch) => updateCondition(idx, patch)}
              onRemove={draft.conditions.length > 1 ? () => removeCondition(idx) : undefined}
            />
          ))}
        </div>

        {/* Acción */}
        <div className="rounded border bg-muted/30 p-3 space-y-2">
          <label className="text-xs font-medium uppercase text-muted-foreground">
            Entonces (acción)
          </label>
          <div className="grid grid-cols-2 gap-2">
            <select
              value={draft.action}
              onChange={(e) => setDraft({ ...draft, action: e.target.value as RuleAction })}
              className="rounded border px-2 py-1.5 text-sm bg-white"
            >
              {(Object.keys(ACTION_LABELS) as RuleAction[]).map((a) => (
                <option key={a} value={a}>
                  {ACTION_LABELS[a]}
                </option>
              ))}
            </select>
            <input
              value={(draft.action_params?.message as string) ?? ""}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  action_params: { ...draft.action_params, message: e.target.value },
                })
              }
              placeholder="Mensaje a mostrar al usuario"
              className="rounded border px-2 py-1.5 text-sm"
            />
          </div>
        </div>

        {err && <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900">{err}</div>}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancelar
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            <Save className="h-4 w-4 mr-2" />
            {saving ? "Guardando..." : "Guardar regla"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Editor de una condición
// =============================================================================

function ConditionEditor({
  condition,
  onChange,
  onRemove,
}: {
  condition: RuleCondition;
  onChange: (patch: Partial<RuleCondition>) => void;
  onRemove?: () => void;
}) {
  const fieldDef = FIELDS.find((f) => f.value === condition.field);
  const fieldType = fieldDef?.type ?? "string";
  const validOps = OPERATORS.filter((o) => o.types.includes(fieldType));
  const opNeedsValue = !["exists", "not_exists", "is_null", "is_not_null"].includes(condition.operator);

  return (
    <div className="grid grid-cols-12 gap-2 items-start rounded border bg-card p-2">
      {/* Campo */}
      <select
        value={condition.field}
        onChange={(e) => {
          const newField = e.target.value;
          const newDef = FIELDS.find((f) => f.value === newField);
          // Si cambia de tipo, ajustar operador
          const newValidOps = OPERATORS.filter((o) => o.types.includes(newDef?.type ?? "string"));
          const opStillValid = newValidOps.some((o) => o.value === condition.operator);
          onChange({
            field: newField,
            operator: opStillValid ? condition.operator : newValidOps[0].value,
          });
        }}
        className="col-span-5 rounded border px-2 py-1.5 text-xs bg-white"
      >
        {Array.from(new Set(FIELDS.map((f) => f.group))).map((group) => (
          <optgroup key={group} label={group}>
            {FIELDS.filter((f) => f.group === group).map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>

      {/* Operador */}
      <select
        value={condition.operator}
        onChange={(e) => onChange({ operator: e.target.value as RuleOperator })}
        className="col-span-2 rounded border px-2 py-1.5 text-xs bg-white"
      >
        {validOps.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>

      {/* Valor */}
      {opNeedsValue ? (
        <input
          type={fieldType === "number" ? "number" : "text"}
          step={fieldType === "number" ? "any" : undefined}
          value={condition.value === undefined || condition.value === null ? "" : String(condition.value)}
          onChange={(e) =>
            onChange({
              value:
                fieldType === "number"
                  ? e.target.value === ""
                    ? null
                    : Number(e.target.value)
                  : e.target.value,
            })
          }
          placeholder={fieldType === "number" ? "0.00" : "valor"}
          className="col-span-4 rounded border px-2 py-1.5 text-xs"
        />
      ) : (
        <div className="col-span-4 text-xs text-muted-foreground italic px-2 py-1.5">
          (sin valor)
        </div>
      )}

      {/* Botón eliminar */}
      <div className="col-span-1 flex justify-end">
        {onRemove && (
          <button
            onClick={onRemove}
            className="text-red-600 hover:bg-red-50 p-1 rounded"
            title="Quitar condición"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Toggle case-insensitive si es string contains/matches */}
      {fieldType === "string" &&
        ["contains", "not_contains", "equals", "not_equals", "matches"].includes(condition.operator) && (
          <label className="col-span-12 flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
            <input
              type="checkbox"
              checked={!!condition.case_insensitive}
              onChange={(e) => onChange({ case_insensitive: e.target.checked })}
            />
            Ignorar mayúsculas/minúsculas
          </label>
        )}
    </div>
  );
}
