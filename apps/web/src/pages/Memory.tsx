import { useCallback, useEffect, useState } from "react";
import { Brain, Trash2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { TenantBanner } from "@/components/TenantBanner";
import { api, getTenantId } from "@/lib/api";
import type { FieldMappingRead } from "@/lib/api";
import { cn } from "@/lib/utils";

export function Memory() {
  const [mappings, setMappings] = useState<FieldMappingRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!getTenantId()) return;
    setLoading(true);
    setError(null);
    try {
      setMappings(await api.listFieldMappings());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleDelete = async (id: string) => {
    if (!confirm("¿Eliminar este mapeo? Solo afecta a futuras extracciones.")) return;
    try {
      await api.deleteFieldMapping(id);
      setMappings((prev) => prev.filter((m) => m.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const totalHits = mappings.reduce((sum, m) => sum + m.hits, 0);

  return (
    <div className="space-y-5">
      <TenantBanner onChanged={refresh} />

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Brain className="h-6 w-6 text-violet-600" />
            Memoria del tenant
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Reglas de canonicalización aprendidas. Cada vez que corriges algo, se aplica automáticamente
            en futuras extracciones del mismo cliente.
          </p>
        </div>
        <Button variant="outline" onClick={refresh} disabled={loading}>
          <RefreshCw className={cn("h-4 w-4 mr-2", loading && "animate-spin")} />
          Refrescar
        </Button>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Stat label="Reglas activas" value={String(mappings.length)} />
        <Stat label="Aplicaciones totales" value={String(totalHits)} />
        <Stat
          label="Más usada"
          value={mappings[0]?.canonical_value ?? "—"}
          sub={mappings[0] ? `${mappings[0].hits} aplicaciones` : undefined}
        />
      </div>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </div>
      )}

      {mappings.length === 0 ? (
        <div className="rounded-lg border bg-card p-12 text-center text-muted-foreground">
          <Brain className="h-10 w-10 mx-auto mb-3 text-muted-foreground/50" />
          <p className="text-sm font-medium text-foreground">Sin reglas aún</p>
          <p className="text-xs mt-2 max-w-md mx-auto">
            Cuando revises pedidos, selecciona texto en el PDF o usa el botón "Asignar concepto"
            sobre cualquier campo. Las reglas se guardarán aquí y se aplicarán automáticamente
            a futuros pedidos del mismo cliente.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border bg-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left">
              <tr>
                <th className="px-4 py-3 font-medium">Texto detectado</th>
                <th className="px-4 py-3 font-medium">→ Concepto canónico</th>
                <th className="px-4 py-3 font-medium">Código</th>
                <th className="px-4 py-3 font-medium">Alcance</th>
                <th className="px-4 py-3 font-medium text-right">Aplicado</th>
                <th className="px-4 py-3 font-medium w-8"></th>
              </tr>
            </thead>
            <tbody>
              {mappings.map((m) => (
                <tr key={m.id} className="border-t hover:bg-muted/20">
                  <td className="px-4 py-3 font-mono text-xs">{m.source_text}</td>
                  <td className="px-4 py-3 font-medium">{m.canonical_value}</td>
                  <td className="px-4 py-3">
                    {m.canonical_code ? (
                      <span className="inline-block bg-violet-100 text-violet-900 rounded px-1.5 py-0.5 text-xs font-mono">
                        {m.canonical_code}
                      </span>
                    ) : (
                      <span className="text-muted-foreground italic">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground font-mono">
                    {m.field_path_pattern ?? "cualquier campo"}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    <span
                      className={cn(
                        "inline-block rounded-full px-2 py-0.5 text-xs",
                        m.hits > 0 ? "bg-emerald-100 text-emerald-900" : "bg-zinc-100 text-zinc-600",
                      )}
                    >
                      {m.hits}×
                    </span>
                  </td>
                  <td className="px-2 py-3">
                    <button
                      onClick={() => handleDelete(m.id)}
                      title="Eliminar mapeo"
                      className="text-red-600 hover:text-red-800 p-1 rounded hover:bg-red-50"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <div className="text-xs text-muted-foreground uppercase tracking-wide">{label}</div>
      <div className="mt-0.5 text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}
