import { useEffect, useMemo, useState } from "react";
import { Search, Globe2, User, ChevronLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { ConceptRead, SchemaField } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  /** Texto seleccionado en el PDF */
  sourceText: string;
  onClose: () => void;
  onSaved?: (concept: ConceptRead) => void;
}

/**
 * Modal "Asignar a campo": el usuario elige a qué campo del esquema corresponde
 * la palabra/frase seleccionada. Si el campo ya tiene un Concept del tenant, se
 * añade el alias. Si no, crea uno nuevo.
 */
export function AssignToConceptModal({ open, sourceText, onClose, onSaved }: Props) {
  const [schemaFields, setSchemaFields] = useState<SchemaField[]>([]);
  const [concepts, setConcepts] = useState<ConceptRead[]>([]);
  const [search, setSearch] = useState("");
  const [picking, setPicking] = useState<SchemaField | null>(null);
  const [isGlobal, setIsGlobal] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setSearch("");
    setPicking(null);
    setIsGlobal(false);
    setError(null);
    Promise.all([api.listSchemaFields(), api.listConcepts()])
      .then(([sf, cs]) => {
        setSchemaFields(sf);
        setConcepts(cs);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [open]);

  // Concepts por field_path para indicar cuántos aliases tiene cada campo
  const conceptsByField = useMemo(() => {
    const m = new Map<string, ConceptRead>();
    for (const c of concepts) {
      if (c.field_path) m.set(c.field_path, c);
    }
    return m;
  }, [concepts]);

  // Agrupar fields por su grupo (Cliente / Pedido / Totales)
  const grouped = useMemo(() => {
    const norm = search.toLowerCase().trim();
    const filtered = norm
      ? schemaFields.filter(
          (f) =>
            f.label.toLowerCase().includes(norm) ||
            f.path.toLowerCase().includes(norm) ||
            (conceptsByField.get(f.path)?.aliases ?? []).some((a) => a.includes(norm)),
        )
      : schemaFields;
    const out = new Map<string, SchemaField[]>();
    for (const f of filtered) {
      const arr = out.get(f.group) ?? [];
      arr.push(f);
      out.set(f.group, arr);
    }
    return out;
  }, [schemaFields, search, conceptsByField]);

  if (!open) return null;

  const handleAssign = async () => {
    if (!picking) return;
    setSaving(true);
    setError(null);
    try {
      const existing = conceptsByField.get(picking.path);
      let saved: ConceptRead;
      if (existing) {
        saved = await api.addConceptAlias(existing.id, sourceText);
      } else {
        saved = await api.createConcept({
          name: picking.label,
          field_path: picking.path,
          aliases: [sourceText],
          is_global: isGlobal,
        });
      }
      onSaved?.(saved);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm overflow-auto p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-[560px] max-w-[95vw] rounded-lg border bg-white shadow-xl p-5 space-y-4 my-auto">
        <div>
          <h2 className="text-lg font-semibold">
            {picking ? "Confirmar asignación" : "¿A qué campo corresponde?"}
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            {picking
              ? "El sistema reconocerá esta etiqueta en futuras extracciones."
              : "Elige el campo del panel derecho al que vincular esta palabra."}
          </p>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Texto del PDF
          </label>
          <div className="rounded border bg-zinc-50 px-3 py-2 text-sm font-mono break-words max-h-24 overflow-auto">
            {sourceText}
          </div>
        </div>

        {!picking ? (
          <>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <input
                autoFocus
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar campo (nombre, alias o path...)"
                className="w-full pl-8 pr-3 py-1.5 rounded border text-sm"
              />
            </div>

            <div className="max-h-[400px] overflow-auto space-y-3 pr-1">
              {Array.from(grouped.entries()).map(([group, fields]) => (
                <div key={group}>
                  <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">
                    {group}
                  </div>
                  <div className="space-y-1">
                    {fields.map((f) => {
                      const c = conceptsByField.get(f.path);
                      return (
                        <button
                          key={f.path}
                          onClick={() => setPicking(f)}
                          className="w-full text-left px-3 py-2 rounded border hover:border-blue-400 hover:bg-blue-50/50 transition-colors flex items-center justify-between gap-2"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="text-sm font-medium">{f.label}</div>
                            {c && c.aliases.length > 0 && (
                              <div className="text-xs text-muted-foreground truncate mt-0.5">
                                {c.aliases.slice(0, 4).join(" · ")}
                                {c.aliases.length > 4 && ` · +${c.aliases.length - 4}`}
                              </div>
                            )}
                          </div>
                          {c && c.aliases.length > 0 && (
                            <span className="text-xs bg-emerald-100 text-emerald-900 rounded-full px-2 py-0.5 shrink-0">
                              {c.aliases.length} alias{c.aliases.length !== 1 && "es"}
                            </span>
                          )}
                          {c && c.tenant_id === null && (
                            <Globe2 className="h-3.5 w-3.5 text-amber-600 shrink-0" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
              {grouped.size === 0 && (
                <div className="text-sm text-center py-6 text-muted-foreground">
                  Ningún campo coincide con la búsqueda.
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="space-y-3">
            <button
              onClick={() => setPicking(null)}
              className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
            >
              <ChevronLeft className="h-3 w-3" /> elegir otro campo
            </button>

            <div className="rounded border bg-blue-50 p-3 text-sm">
              <div className="font-medium">{picking.label}</div>
              <div className="text-xs text-muted-foreground font-mono mt-0.5">{picking.path}</div>
            </div>

            {!conceptsByField.has(picking.path) && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Alcance del nuevo concepto
                </label>
                <div className="space-y-1.5 text-sm">
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      type="radio"
                      checked={!isGlobal}
                      onChange={() => setIsGlobal(false)}
                      className="mt-0.5"
                    />
                    <div>
                      <div className="font-medium flex items-center gap-1.5">
                        <User className="h-3 w-3" /> Solo este cliente
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Solo se aplica a documentos de este tenant
                      </div>
                    </div>
                  </label>
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      type="radio"
                      checked={isGlobal}
                      onChange={() => setIsGlobal(true)}
                      className="mt-0.5"
                    />
                    <div>
                      <div className="font-medium flex items-center gap-1.5">
                        <Globe2 className="h-3 w-3" /> Para todos los clientes
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Aplica a documentos de cualquier tenant
                      </div>
                    </div>
                  </label>
                </div>
              </div>
            )}

            {conceptsByField.has(picking.path) && (
              <div className="text-xs text-muted-foreground bg-emerald-50 border border-emerald-200 rounded p-2">
                Ya existe un concepto para este campo. El texto se añadirá como nuevo alias.
              </div>
            )}
          </div>
        )}

        {error && (
          <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancelar
          </Button>
          {picking && (
            <Button onClick={handleAssign} disabled={saving}>
              {saving ? "Guardando..." : "Confirmar"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// cn helper para evitar import si no se usa
const _ = cn;
void _;
