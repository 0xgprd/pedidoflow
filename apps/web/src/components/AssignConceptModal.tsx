import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { FieldMappingRead } from "@/lib/api";

interface Props {
  open: boolean;
  /** Texto que se quiere mapear (lo que el usuario seleccionó en el PDF
   *  o el valor original del campo antes de editar). */
  sourceText: string;
  /** Sugerencia inicial para canonical_value (opcional, ej: el valor que
   *  el usuario acaba de escribir editando un campo). */
  initialCanonical?: string;
  /** Path del campo si viene del form (ej "lineas.0.descripcion") — se
   *  ofrece como pattern sugerido. */
  hintFieldPath?: string;
  onClose: () => void;
  onSaved: (mapping: FieldMappingRead) => void;
}

/**
 * Modal para crear/actualizar un FieldMapping per-tenant.
 *
 * Ejemplo de uso típico:
 *   sourceText="FREIGHT COST"  → canonical_value="Transporte" + code="FP"
 *
 * Cuando se guarda, futuras extracciones del tenant aplicarán automáticamente
 * la regla: cualquier campo cuyo valor contenga "FREIGHT COST" se canonicaliza
 * a "Transporte (FP)".
 */
export function AssignConceptModal({
  open,
  sourceText,
  initialCanonical,
  hintFieldPath,
  onClose,
  onSaved,
}: Props) {
  const [canonical, setCanonical] = useState("");
  const [code, setCode] = useState("");
  const [scope, setScope] = useState<"any" | "section">("any");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setCanonical(initialCanonical?.trim() ?? "");
      setCode("");
      setScope("any");
      setError(null);
    }
  }, [open, initialCanonical]);

  if (!open) return null;

  const sectionPattern = hintFieldPath ? sectionPatternFor(hintFieldPath) : null;

  const handleSave = async () => {
    if (!canonical.trim()) {
      setError("Indica un concepto canónico (ej: Transporte)");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await api.upsertFieldMapping({
        source_text: sourceText,
        canonical_value: canonical.trim(),
        canonical_code: code.trim() || null,
        field_path_pattern: scope === "section" && sectionPattern ? sectionPattern : null,
      });
      onSaved(created);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-[480px] max-w-[95vw] rounded-lg border bg-white shadow-xl p-5 space-y-4">
        <div>
          <h2 className="text-lg font-semibold">Asignar concepto</h2>
          <p className="text-xs text-muted-foreground mt-1">
            Cuando vuelva a aparecer este texto en un pedido del tenant, se canonicalizará
            automáticamente.
          </p>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Texto detectado en el PDF
          </label>
          <div className="rounded border bg-zinc-50 px-3 py-2 text-sm font-mono break-words">
            {sourceText}
          </div>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="canonical" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Concepto canónico
          </label>
          <input
            id="canonical"
            autoFocus
            type="text"
            placeholder="ej: Transporte"
            value={canonical}
            onChange={(e) => setCanonical(e.target.value)}
            className="w-full rounded border px-3 py-2 text-sm"
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="code" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Código corto <span className="text-muted-foreground/70 normal-case">(opcional)</span>
          </label>
          <input
            id="code"
            type="text"
            placeholder="ej: FP"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            maxLength={20}
            className="w-full rounded border px-3 py-2 text-sm font-mono"
          />
          {code && canonical && (
            <p className="text-xs text-muted-foreground">
              Se mostrará como <span className="font-medium">{canonical} ({code})</span>
            </p>
          )}
        </div>

        {sectionPattern && (
          <div className="space-y-2">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Alcance
            </label>
            <div className="space-y-1.5 text-sm">
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="scope"
                  checked={scope === "any"}
                  onChange={() => setScope("any")}
                  className="mt-0.5"
                />
                <div>
                  <div className="font-medium">Cualquier campo</div>
                  <div className="text-xs text-muted-foreground">
                    Aplica donde aparezca el texto
                  </div>
                </div>
              </label>
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="scope"
                  checked={scope === "section"}
                  onChange={() => setScope("section")}
                  className="mt-0.5"
                />
                <div>
                  <div className="font-medium">Solo en {humanScope(sectionPattern)}</div>
                  <div className="text-xs text-muted-foreground font-mono">{sectionPattern}</div>
                </div>
              </label>
            </div>
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
          <Button onClick={handleSave} disabled={saving || !canonical.trim()}>
            {saving ? "Guardando..." : "Guardar para este cliente"}
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Convierte "lineas.0.descripcion" → "lineas.*.descripcion" */
function sectionPatternFor(path: string): string {
  return path.replace(/\.\d+\./g, ".*.");
}

function humanScope(pattern: string): string {
  if (pattern.startsWith("cliente.")) return "datos del cliente";
  if (pattern.startsWith("pedido.")) return "datos del pedido";
  if (pattern.startsWith("lineas.")) {
    const part = pattern.replace(/^lineas\.\*\./, "");
    return `líneas (${part})`;
  }
  if (pattern.startsWith("totales.")) return "totales";
  return pattern;
}
