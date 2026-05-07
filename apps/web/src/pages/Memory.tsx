import { useCallback, useEffect, useMemo, useState } from "react";
import { Brain, Trash2, RefreshCw, Plus, X, Globe2, User, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, getTenantId, tenantFieldsApi } from "@/lib/api";
import type { ConceptRead, SchemaField, TenantFieldRead } from "@/lib/api";
import { cn } from "@/lib/utils";

export function Memory() {
  const [concepts, setConcepts] = useState<ConceptRead[]>([]);
  const [schemaFields, setSchemaFields] = useState<SchemaField[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Estado del formulario "añadir campo custom" por grupo
  const [addingTo, setAddingTo] = useState<string | null>(null);
  const [newFieldLabel, setNewFieldLabel] = useState("");

  const refresh = useCallback(async () => {
    if (!getTenantId()) return;
    setLoading(true);
    setError(null);
    try {
      const [c, sf] = await Promise.all([api.listConcepts(), api.listSchemaFields()]);
      setConcepts(c);
      setSchemaFields(sf);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Mapa field_path → concept (el del tenant prevalece sobre global)
  const conceptByField = useMemo(() => {
    const m = new Map<string, ConceptRead>();
    for (const c of concepts) {
      if (!c.field_path) continue;
      const existing = m.get(c.field_path);
      // tenant gana sobre global si ambos existen
      if (!existing || (existing.tenant_id === null && c.tenant_id !== null)) {
        m.set(c.field_path, c);
      }
    }
    return m;
  }, [concepts]);

  // Conceptos sin field_path (libres / sustitución)
  const freeConcepts = useMemo(
    () => concepts.filter((c) => !c.field_path),
    [concepts],
  );

  // Schema fields agrupados (Cliente / Pedido / Totales) — preserva orden de la API
  const groupedFields = useMemo(() => {
    const out = new Map<string, SchemaField[]>();
    for (const f of schemaFields) {
      const arr = out.get(f.group) ?? [];
      arr.push(f);
      out.set(f.group, arr);
    }
    return out;
  }, [schemaFields]);

  const totalAliases = concepts.reduce((s, c) => s + c.aliases.length, 0);
  const totalHits = concepts.reduce((s, c) => s + c.hits, 0);

  const handleAddAlias = async (concept: ConceptRead, alias: string) => {
    if (!alias.trim()) return;
    try {
      const updated = await api.addConceptAlias(concept.id, alias.trim());
      setConcepts((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleRemoveAlias = async (concept: ConceptRead, alias: string) => {
    try {
      const newAliases = concept.aliases.filter((a) => a !== alias);
      const updated = await api.updateConcept(concept.id, { aliases: newAliases });
      setConcepts((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleCreateForField = async (field: SchemaField, isGlobal: boolean) => {
    try {
      const created = await api.createConcept({
        name: field.label,
        field_path: field.path,
        aliases: [],
        is_global: isGlobal,
      });
      setConcepts((prev) => [...prev, created]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleToggleScope = async (concept: ConceptRead) => {
    try {
      const updated = await api.updateConcept(concept.id, {
        is_global: concept.tenant_id !== null, // si era tenant → ahora global, y viceversa
      });
      setConcepts((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleDelete = async (concept: ConceptRead) => {
    if (!confirm(`¿Eliminar "${concept.name}" y todos sus aliases?`)) return;
    try {
      await api.deleteConcept(concept.id);
      setConcepts((prev) => prev.filter((c) => c.id !== concept.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleAddCustomField = async (group: string) => {
    if (!newFieldLabel.trim()) return;
    try {
      await tenantFieldsApi.create({ group, label: newFieldLabel.trim() });
      setNewFieldLabel("");
      setAddingTo(null);
      // Recargar para que el nuevo campo aparezca en /schema-fields
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleRemoveCustomField = async (field: SchemaField) => {
    if (!field.tenant_field_id) return;
    if (
      !confirm(
        `¿Eliminar el campo "${field.label}"? Se borrarán también sus aliases. Los pedidos antiguos conservan el dato.`,
      )
    )
      return;
    try {
      await tenantFieldsApi.remove(field.tenant_field_id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Brain className="h-6 w-6 text-violet-600" />
            Memoria — Diccionario de campos
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Aliases (palabras del PDF) que el sistema reconoce para cada campo. Cuando llega un PDF
            nuevo, Claude usa estas pistas para extraer correctamente los datos. También puedes
            añadir <strong>campos propios</strong> a cada grupo (ej: "Horario de entrega").
          </p>
        </div>
        <Button variant="outline" onClick={refresh} disabled={loading}>
          <RefreshCw className={cn("h-4 w-4 mr-2", loading && "animate-spin")} />
          Refrescar
        </Button>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Stat label="Aliases totales" value={totalAliases} />
        <Stat
          label="Campos con aliases"
          value={conceptByField.size}
          sub={`de ${schemaFields.length} disponibles`}
        />
        <Stat label="Aplicaciones" value={totalHits} />
      </div>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </div>
      )}

      {/* Campos del esquema agrupados */}
      {Array.from(groupedFields.entries()).map(([group, fields]) => (
        <div key={group} className="space-y-2">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
            {group}
          </h2>
          <div className="space-y-2">
            {fields.map((field) => (
              <FieldCard
                key={field.path}
                field={field}
                concept={conceptByField.get(field.path) ?? null}
                onAddAlias={handleAddAlias}
                onRemoveAlias={handleRemoveAlias}
                onCreateForField={handleCreateForField}
                onToggleScope={handleToggleScope}
                onDeleteConcept={handleDelete}
                onRemoveCustomField={handleRemoveCustomField}
              />
            ))}

            {/* Inline form para añadir campo custom al grupo */}
            {addingTo === group ? (
              <div className="rounded-lg border border-dashed border-violet-300 bg-violet-50/50 p-3 flex items-center gap-2">
                <input
                  autoFocus
                  type="text"
                  value={newFieldLabel}
                  onChange={(e) => setNewFieldLabel(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleAddCustomField(group);
                    }
                    if (e.key === "Escape") {
                      setAddingTo(null);
                      setNewFieldLabel("");
                    }
                  }}
                  placeholder='Ej: "Horario de entrega"'
                  className="flex-1 rounded border px-2 py-1.5 text-sm"
                />
                <Button
                  size="sm"
                  onClick={() => handleAddCustomField(group)}
                  disabled={!newFieldLabel.trim()}
                >
                  Crear
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setAddingTo(null);
                    setNewFieldLabel("");
                  }}
                >
                  Cancelar
                </Button>
              </div>
            ) : (
              <button
                onClick={() => {
                  setAddingTo(group);
                  setNewFieldLabel("");
                }}
                className="w-full rounded-lg border border-dashed border-zinc-300 hover:border-violet-400 hover:bg-violet-50/30 text-sm text-muted-foreground hover:text-violet-700 px-3 py-2 inline-flex items-center justify-center gap-1.5 transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
                Añadir campo a {group}
              </button>
            )}
          </div>
        </div>
      ))}

      {/* Conceptos libres (sin field_path) — sustituyen valores */}
      {freeConcepts.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
            Conceptos libres (sustitución de valores)
          </h2>
          <div className="space-y-2">
            {freeConcepts.map((c) => (
              <FreeConceptCard
                key={c.id}
                concept={c}
                onAddAlias={handleAddAlias}
                onRemoveAlias={handleRemoveAlias}
                onDelete={handleDelete}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <div className="text-xs text-muted-foreground uppercase tracking-wide">{label}</div>
      <div className="mt-0.5 text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

function FieldCard({
  field,
  concept,
  onAddAlias,
  onRemoveAlias,
  onCreateForField,
  onToggleScope,
  onDeleteConcept,
  onRemoveCustomField,
}: {
  field: SchemaField;
  concept: ConceptRead | null;
  onAddAlias: (concept: ConceptRead, alias: string) => void;
  onRemoveAlias: (concept: ConceptRead, alias: string) => void;
  onCreateForField: (field: SchemaField, isGlobal: boolean) => void;
  onToggleScope: (concept: ConceptRead) => void;
  onDeleteConcept: (concept: ConceptRead) => void;
  onRemoveCustomField: (field: SchemaField) => void;
}) {
  const [aliasInput, setAliasInput] = useState("");

  const submitAlias = () => {
    if (!aliasInput.trim() || !concept) return;
    onAddAlias(concept, aliasInput);
    setAliasInput("");
  };

  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-3",
        field.is_custom && "border-violet-200 bg-violet-50/30",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-medium">{field.label}</h3>
            <code className="text-xs text-muted-foreground">{field.path}</code>
            {field.is_custom && (
              <span className="text-xs bg-violet-100 text-violet-900 rounded px-1.5 py-0.5 inline-flex items-center gap-1">
                <Sparkles className="h-3 w-3" /> custom
              </span>
            )}
            {concept && (
              <button
                onClick={() => onToggleScope(concept)}
                className={cn(
                  "text-xs rounded px-1.5 py-0.5 inline-flex items-center gap-1 transition-colors cursor-pointer",
                  concept.tenant_id === null
                    ? "bg-amber-100 text-amber-900 hover:bg-amber-200"
                    : "bg-sky-100 text-sky-900 hover:bg-sky-200",
                )}
                title="Click para cambiar entre 'solo este cliente' y 'global (todos los clientes)'"
              >
                {concept.tenant_id === null ? (
                  <>
                    <Globe2 className="h-3 w-3" /> global
                  </>
                ) : (
                  <>
                    <User className="h-3 w-3" /> solo este cliente
                  </>
                )}
              </button>
            )}
            {concept && concept.hits > 0 && (
              <span className="text-xs bg-emerald-100 text-emerald-900 rounded-full px-2 py-0.5">
                {concept.hits}× aplicado
              </span>
            )}
          </div>

          {!concept ? (
            <div className="mt-2 flex items-center gap-2 text-xs flex-wrap">
              <span className="text-muted-foreground italic">Sin aliases.</span>
              <button
                onClick={() => onCreateForField(field, false)}
                className="text-blue-600 hover:underline inline-flex items-center gap-1"
              >
                <Plus className="h-3 w-3" /> Añadir alias para este cliente
              </button>
              <span className="text-muted-foreground">·</span>
              <button
                onClick={() => onCreateForField(field, true)}
                className="text-blue-600 hover:underline inline-flex items-center gap-1"
              >
                <Globe2 className="h-3 w-3" /> Para todos los clientes
              </button>
            </div>
          ) : (
            <>
              <div className="mt-2 flex flex-wrap gap-1">
                {concept.aliases.map((a, i) => (
                  <span
                    key={i}
                    className="inline-flex items-center gap-1 bg-zinc-200 text-zinc-800 rounded px-2 py-0.5 text-xs font-mono"
                  >
                    {a}
                    <button
                      onClick={() => onRemoveAlias(concept, a)}
                      className="hover:bg-zinc-300 rounded-full p-0.5"
                      title="Quitar"
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </span>
                ))}
                {concept.aliases.length === 0 && (
                  <span className="text-xs text-muted-foreground italic">
                    Aún sin aliases. Añade el primero abajo.
                  </span>
                )}
              </div>
              <div className="mt-2 flex gap-2">
                <input
                  value={aliasInput}
                  onChange={(e) => setAliasInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      submitAlias();
                    }
                  }}
                  placeholder="Añadir alias..."
                  className="flex-1 rounded border px-2 py-1 text-xs"
                />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={submitAlias}
                  disabled={!aliasInput.trim()}
                >
                  <Plus className="h-3 w-3" />
                </Button>
              </div>
            </>
          )}
        </div>
        <div className="flex flex-col gap-1 shrink-0">
          {concept && (
            <button
              onClick={() => onDeleteConcept(concept)}
              className="text-red-600 hover:bg-red-50 p-1.5 rounded"
              title="Eliminar todos los aliases de este campo"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
          {field.is_custom && (
            <button
              onClick={() => onRemoveCustomField(field)}
              className="text-zinc-500 hover:bg-zinc-100 hover:text-red-600 p-1.5 rounded"
              title="Eliminar este campo del esquema"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function FreeConceptCard({
  concept,
  onAddAlias,
  onRemoveAlias,
  onDelete,
}: {
  concept: ConceptRead;
  onAddAlias: (concept: ConceptRead, alias: string) => void;
  onRemoveAlias: (concept: ConceptRead, alias: string) => void;
  onDelete: (concept: ConceptRead) => void;
}) {
  const [aliasInput, setAliasInput] = useState("");
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-medium">{concept.name}</h3>
            {concept.code && (
              <span className="text-xs bg-violet-100 text-violet-900 rounded px-1.5 py-0.5 font-mono">
                {concept.code}
              </span>
            )}
            {concept.tenant_id === null && (
              <span className="text-xs bg-amber-100 text-amber-900 rounded px-1.5 py-0.5 inline-flex items-center gap-1">
                <Globe2 className="h-3 w-3" /> global
              </span>
            )}
            {concept.hits > 0 && (
              <span className="text-xs bg-emerald-100 text-emerald-900 rounded-full px-2 py-0.5">
                {concept.hits}×
              </span>
            )}
          </div>
          <div className="mt-2 flex flex-wrap gap-1">
            {concept.aliases.map((a, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 bg-zinc-200 text-zinc-800 rounded px-2 py-0.5 text-xs font-mono"
              >
                {a}
                <button
                  onClick={() => onRemoveAlias(concept, a)}
                  className="hover:bg-zinc-300 rounded-full p-0.5"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </span>
            ))}
          </div>
          <div className="mt-2 flex gap-2">
            <input
              value={aliasInput}
              onChange={(e) => setAliasInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && aliasInput.trim()) {
                  e.preventDefault();
                  onAddAlias(concept, aliasInput);
                  setAliasInput("");
                }
              }}
              placeholder="Añadir alias..."
              className="flex-1 rounded border px-2 py-1 text-xs"
            />
          </div>
        </div>
        <button
          onClick={() => onDelete(concept)}
          className="text-red-600 hover:bg-red-50 p-1.5 rounded shrink-0"
          title="Eliminar concepto"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// Suprime el warning si TenantFieldRead se importa pero no se usa de forma directa
// (lo recibimos vía SchemaField que lleva tenant_field_id).
type _Unused = TenantFieldRead;
const _unused: _Unused | undefined = undefined;
void _unused;
