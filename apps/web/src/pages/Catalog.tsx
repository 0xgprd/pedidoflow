import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, Plus, Upload, Trash2, RefreshCw, Search, Save, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { TenantBanner } from "@/components/TenantBanner";
import { catalogApi, getTenantId } from "@/lib/api";
import type { CatalogItemRead, CatalogItemUpdate, CatalogUploadResult } from "@/lib/api";
import { cn } from "@/lib/utils";

export function Catalog() {
  const [items, setItems] = useState<CatalogItemRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [uploadResult, setUploadResult] = useState<CatalogUploadResult | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    if (!getTenantId()) return;
    setLoading(true);
    setError(null);
    try {
      setItems(await catalogApi.list({ search: search || undefined, active_only: !showInactive }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [search, showInactive]);

  useEffect(() => {
    const t = setTimeout(refresh, 200);
    return () => clearTimeout(t);
  }, [refresh]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setError(null);
    setUploadResult(null);
    try {
      const r = await catalogApi.uploadCsv(file);
      setUploadResult(r);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleDelete = async (id: string, ref: string) => {
    if (!confirm(`¿Eliminar "${ref}" del catálogo?`)) return;
    try {
      await catalogApi.remove(id);
      setItems((prev) => prev.filter((i) => i.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="space-y-5">
      <TenantBanner onChanged={refresh} />

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <BookOpen className="h-6 w-6 text-amber-600" />
            Catálogo de referencias
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Tu lista de productos con precio mínimo. Los pedidos por debajo del mínimo se
            marcan como bloqueantes en la revisión.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={refresh} disabled={loading}>
            <RefreshCw className={cn("h-4 w-4 mr-2", loading && "animate-spin")} />
            Refrescar
          </Button>
          <Button variant="outline" onClick={() => fileRef.current?.click()} disabled={!getTenantId()}>
            <Upload className="h-4 w-4 mr-2" /> Importar CSV
          </Button>
          <Button onClick={() => setAdding(true)} disabled={!getTenantId()}>
            <Plus className="h-4 w-4 mr-2" /> Nueva ref
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.txt,text/csv"
            onChange={handleUpload}
            className="hidden"
          />
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </div>
      )}

      {uploadResult && (
        <div className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-900">
          Importación: <strong>{uploadResult.created}</strong> nuevas,{" "}
          <strong>{uploadResult.updated}</strong> actualizadas,{" "}
          <strong>{uploadResult.skipped}</strong> ignoradas
          {uploadResult.errors.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs">{uploadResult.errors.length} errores</summary>
              <ul className="mt-1 text-xs font-mono space-y-0.5">
                {uploadResult.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}

      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Buscar por ref o descripción..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 rounded border bg-white text-sm"
          />
        </div>
        <label className="text-sm flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(e) => setShowInactive(e.target.checked)}
          />
          Mostrar inactivas
        </label>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {items.length} ref.
        </span>
      </div>

      {items.length === 0 && !adding ? (
        <div className="rounded-lg border bg-card p-12 text-center text-muted-foreground">
          <BookOpen className="h-10 w-10 mx-auto mb-3 text-muted-foreground/50" />
          <p className="text-sm font-medium text-foreground">Catálogo vacío</p>
          <p className="text-xs mt-2 max-w-md mx-auto">
            Importa un CSV con columnas <code className="bg-muted px-1 rounded">reference, description, unit, min_price, currency</code>{" "}
            o añade referencias una a una con el botón "Nueva ref".
          </p>
        </div>
      ) : (
        <div className="rounded-lg border bg-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left">
              <tr>
                <th className="px-4 py-2 font-medium">Referencia</th>
                <th className="px-4 py-2 font-medium">Descripción</th>
                <th className="px-4 py-2 font-medium">Ud</th>
                <th className="px-4 py-2 font-medium text-right">Precio mín.</th>
                <th className="px-4 py-2 font-medium text-right">Precio lista</th>
                <th className="px-4 py-2 font-medium">Activa</th>
                <th className="px-4 py-2 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {adding && (
                <CatalogRowEdit
                  initial={null}
                  onCancel={() => setAdding(false)}
                  onSaved={(item) => {
                    setItems((prev) => [item, ...prev]);
                    setAdding(false);
                  }}
                />
              )}
              {items.map((it) =>
                editingId === it.id ? (
                  <CatalogRowEdit
                    key={it.id}
                    initial={it}
                    onCancel={() => setEditingId(null)}
                    onSaved={(updated) => {
                      setItems((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
                      setEditingId(null);
                    }}
                  />
                ) : (
                  <tr
                    key={it.id}
                    className={cn(
                      "border-t hover:bg-muted/20 cursor-pointer",
                      !it.active && "opacity-60",
                    )}
                    onClick={() => setEditingId(it.id)}
                  >
                    <td className="px-4 py-2 font-mono text-xs">{it.reference}</td>
                    <td className="px-4 py-2">
                      {it.description ?? <span className="italic text-muted-foreground">—</span>}
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">{it.unit ?? "—"}</td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      {it.min_price !== null ? (
                        formatPrice(it.min_price, it.currency)
                      ) : (
                        <span className="italic text-amber-700">sin mínimo</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                      {it.list_price !== null ? formatPrice(it.list_price, it.currency) : "—"}
                    </td>
                    <td className="px-4 py-2">{it.active ? "✓" : "—"}</td>
                    <td className="px-2 py-2">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(it.id, it.reference);
                        }}
                        className="text-red-600 hover:text-red-800 p-1 rounded hover:bg-red-50"
                        title="Eliminar"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CatalogRowEdit({
  initial,
  onCancel,
  onSaved,
}: {
  initial: CatalogItemRead | null;
  onCancel: () => void;
  onSaved: (item: CatalogItemRead) => void;
}) {
  const [reference, setReference] = useState(initial?.reference ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [unit, setUnit] = useState(initial?.unit ?? "");
  const [minPrice, setMinPrice] = useState(initial?.min_price ?? "");
  const [listPrice, setListPrice] = useState(initial?.list_price ?? "");
  const [currency, setCurrency] = useState(initial?.currency ?? "EUR");
  const [active, setActive] = useState(initial?.active ?? true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleSave = async () => {
    if (!reference.trim()) {
      setErr("Referencia obligatoria");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      let saved: CatalogItemRead;
      const payload: CatalogItemUpdate = {
        reference,
        description: description || null,
        unit: unit || null,
        min_price: minPrice || null,
        list_price: listPrice || null,
        currency,
        active,
      };
      if (initial) {
        saved = await catalogApi.update(initial.id, payload);
      } else {
        saved = await catalogApi.upsert({ ...payload, reference });
      }
      onSaved(saved);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <tr className="border-t bg-amber-50/50">
      <td className="px-4 py-2">
        <input
          autoFocus
          value={reference}
          onChange={(e) => setReference(e.target.value)}
          placeholder="TF-75"
          className="w-full rounded border px-2 py-1 text-xs font-mono"
        />
      </td>
      <td className="px-4 py-2">
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Descripción"
          className="w-full rounded border px-2 py-1 text-sm"
        />
      </td>
      <td className="px-4 py-2">
        <input
          value={unit}
          onChange={(e) => setUnit(e.target.value)}
          placeholder="ML"
          maxLength={20}
          className="w-16 rounded border px-2 py-1 text-sm"
        />
      </td>
      <td className="px-4 py-2 text-right">
        <input
          type="number"
          step="0.01"
          value={minPrice}
          onChange={(e) => setMinPrice(e.target.value)}
          placeholder="0.00"
          className="w-24 rounded border px-2 py-1 text-sm text-right tabular-nums"
        />
      </td>
      <td className="px-4 py-2 text-right">
        <input
          type="number"
          step="0.01"
          value={listPrice}
          onChange={(e) => setListPrice(e.target.value)}
          placeholder="0.00"
          className="w-24 rounded border px-2 py-1 text-sm text-right tabular-nums"
        />
      </td>
      <td className="px-4 py-2">
        <select
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
          className="rounded border px-1 py-1 text-xs mr-2"
        >
          <option>EUR</option>
          <option>USD</option>
          <option>GBP</option>
        </select>
        <input
          type="checkbox"
          checked={active}
          onChange={(e) => setActive(e.target.checked)}
          title="Activa"
        />
      </td>
      <td className="px-1 py-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="text-emerald-700 hover:bg-emerald-50 p-1 rounded"
          title="Guardar"
        >
          <Save className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={onCancel}
          disabled={saving}
          className="text-zinc-600 hover:bg-zinc-100 p-1 rounded ml-1"
          title="Cancelar"
        >
          <X className="h-3.5 w-3.5" />
        </button>
        {err && <div className="text-xs text-red-700 mt-1 max-w-32">{err}</div>}
      </td>
    </tr>
  );
}

function formatPrice(value: string, currency: string): string {
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  const symbol = currency === "EUR" ? "€" : currency === "USD" ? "$" : currency;
  return `${n.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${symbol}`;
}
