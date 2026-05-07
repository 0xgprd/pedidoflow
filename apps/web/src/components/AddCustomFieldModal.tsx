import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

interface Props {
  open: boolean;
  /** Texto seleccionado en el PDF (preselecciona como `value`). */
  initialValue: string;
  onClose: () => void;
  onConfirm: (field: { name: string; value: string; source_text: string }) => void;
}

/**
 * Modal para añadir un "campo custom" sobre el documento actual.
 *
 * Caso típico: el usuario selecciona en el PDF "Plazo entrega: 15 días",
 * abre este modal, le pone nombre "Plazo entrega" y lo guarda como campo
 * extra del documento.
 *
 * El campo se guarda en `extracted_json.custom_fields[]` (no requiere migración).
 */
export function AddCustomFieldModal({ open, initialValue, onClose, onConfirm }: Props) {
  const [name, setName] = useState("");
  const [value, setValue] = useState("");

  useEffect(() => {
    if (open) {
      setName("");
      setValue(initialValue);
    }
  }, [open, initialValue]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-[460px] max-w-[95vw] rounded-lg border bg-white shadow-xl p-5 space-y-4">
        <div>
          <h2 className="text-lg font-semibold">Crear campo custom</h2>
          <p className="text-xs text-muted-foreground mt-1">
            Añade un dato que no estaba en el formulario, asociado al texto seleccionado del PDF.
          </p>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Texto seleccionado del PDF
          </label>
          <div className="rounded border bg-zinc-50 px-3 py-2 text-sm font-mono break-words max-h-24 overflow-auto">
            {initialValue}
          </div>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="cf-name" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Nombre del campo
          </label>
          <input
            id="cf-name"
            autoFocus
            type="text"
            placeholder="ej: Plazo de entrega, Incoterm, Nº pedido interno..."
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded border px-3 py-2 text-sm"
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="cf-value" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Valor (editable)
          </label>
          <input
            id="cf-value"
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-full rounded border px-3 py-2 text-sm"
          />
          <p className="text-xs text-muted-foreground">
            Por defecto el texto del PDF tal cual. Edítalo si quieres normalizarlo.
          </p>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button
            onClick={() => {
              if (!name.trim()) return;
              onConfirm({ name: name.trim(), value: value.trim(), source_text: initialValue });
              onClose();
            }}
            disabled={!name.trim()}
          >
            Añadir campo
          </Button>
        </div>
      </div>
    </div>
  );
}
