import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Upload,
  RefreshCw,
  FileText,
  FileCheck2,
  HelpCircle,
  AlertTriangle,
  Mail,
  ShieldX,
  Link2Off,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, getTenantId } from "@/lib/api";
import type { DocumentListItem, DocumentStatus, DocumentType } from "@/lib/api";
import { cn } from "@/lib/utils";

// =============================================================================
// Status visible (label en UI, distinto del valor interno)
// =============================================================================

const STATUS_LABEL: Record<DocumentStatus, string> = {
  pending: "En cola",
  processing: "Procesando",
  extracted: "Pendiente",  // ← antes "extracted", ahora "Pendiente"
  failed: "Error",
  approved: "Aprobado",
  rejected: "Rechazado",
};

const STATUS_BADGE: Record<DocumentStatus, string> = {
  pending: "bg-slate-200 text-slate-800",
  processing: "bg-blue-200 text-blue-900 animate-pulse",
  extracted: "bg-emerald-200 text-emerald-900",
  failed: "bg-red-200 text-red-900",
  approved: "bg-green-300 text-green-900",
  rejected: "bg-zinc-300 text-zinc-800",
};

const TYPE_BADGE: Record<DocumentType, { label: string; cls: string; icon: typeof FileText }> = {
  pedido: { label: "Pedido", cls: "bg-sky-100 text-sky-900 border-sky-300", icon: FileText },
  oferta: { label: "Oferta", cls: "bg-violet-100 text-violet-900 border-violet-300", icon: FileCheck2 },
  desconocido: { label: "?", cls: "bg-zinc-100 text-zinc-700 border-zinc-300", icon: HelpCircle },
};

const ACTIVE_STATUSES = new Set<DocumentStatus>(["pending", "processing"]);

// Polling adaptativo: rápido si hay docs en proceso, relajado si no.
const POLL_INTERVAL_ACTIVE_MS = 2500;
const POLL_INTERVAL_IDLE_MS = 15000;

// Bump al cambiar el shape de DocumentListItem (invalida caches antiguas)
const CACHE_KEY = "pedidoflow.inbox.cache.v4";

function loadCache(): DocumentListItem[] {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as DocumentListItem[];
    return parsed.filter((d) => d && d.id && d.status);
  } catch {
    return [];
  }
}

function saveCache(items: DocumentListItem[]) {
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(items));
  } catch {
    /* sessionStorage lleno o no disponible */
  }
}

// =============================================================================
// Filtros
// =============================================================================

type StatusFilter = "pending" | "approved" | "rejected" | "processing" | "all";
type TypeFilter = "all" | DocumentType;

const STATUS_FILTERS: Array<{ key: StatusFilter; label: string; matches: (d: DocumentListItem) => boolean }> = [
  { key: "pending", label: "Pendientes", matches: (d) => d.status === "extracted" },
  { key: "approved", label: "Aprobados", matches: (d) => d.status === "approved" },
  { key: "rejected", label: "Rechazados", matches: (d) => d.status === "rejected" },
  {
    key: "processing",
    label: "Procesando",
    matches: (d) => d.status === "pending" || d.status === "processing" || d.status === "failed",
  },
  { key: "all", label: "Todos", matches: () => true },
];

export function Inbox() {
  const [docs, setDocs] = useState<DocumentListItem[]>(loadCache);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async (silent = false) => {
    if (!getTenantId()) return;
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data = await api.listDocuments();
      setDocs(data);
      saveCache(data);
      setLastSync(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const hasActive = docs.some((d) => ACTIVE_STATUSES.has(d.status));
    const interval = hasActive ? POLL_INTERVAL_ACTIVE_MS : POLL_INTERVAL_IDLE_MS;
    const timer = setInterval(() => refresh(true), interval);
    return () => clearInterval(timer);
  }, [docs, refresh]);

  useEffect(() => {
    function handleVisibility() {
      if (document.visibilityState === "visible") {
        refresh(true);
      }
    }
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [refresh]);

  const filteredDocs = useMemo(() => {
    const statusFilterFn = STATUS_FILTERS.find((f) => f.key === statusFilter)!.matches;
    return docs.filter((d) => {
      if (!statusFilterFn(d)) return false;
      if (typeFilter !== "all" && (d.document_type ?? "desconocido") !== typeFilter) return false;
      return true;
    });
  }, [docs, statusFilter, typeFilter]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await api.uploadDocument(file);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Bandeja</h1>
          <p className="text-muted-foreground mt-1">
            Pedidos PDF en el pipeline de extracción IA.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <SyncIndicator lastSync={lastSync} loading={loading} />
          <Button variant="outline" onClick={() => refresh()} disabled={loading}>
            <RefreshCw className={cn("h-4 w-4 mr-2", loading && "animate-spin")} />
            Refrescar
          </Button>
          <Button onClick={() => fileInputRef.current?.click()} disabled={uploading || !getTenantId()}>
            <Upload className="h-4 w-4 mr-2" />
            {uploading ? "Subiendo..." : "Subir PDF"}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            onChange={handleUpload}
            className="hidden"
          />
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">{error}</div>
      )}

      {/* Tabs primarios — por estado */}
      <StatusTabs value={statusFilter} onChange={setStatusFilter} docs={docs} />

      {/* Filtro secundario — chips por tipo */}
      <TypeChips value={typeFilter} onChange={setTypeFilter} docs={docs} statusFilter={statusFilter} />

      {filteredDocs.length === 0 ? (
        <div className="rounded-lg border bg-card p-12 text-center text-muted-foreground">
          <p className="text-sm">
            {statusFilter === "pending"
              ? "No hay documentos pendientes de revisar."
              : "Sin resultados para los filtros actuales."}
          </p>
          {docs.length === 0 && (
            <p className="text-xs mt-2">Sube un PDF arriba o conecta Outlook (Integraciones).</p>
          )}
        </div>
      ) : (
        <div className="rounded-lg border bg-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left">
              <tr>
                <th className="px-3 py-3 font-medium w-20">Tipo</th>
                <th className="px-3 py-3 font-medium">Archivo</th>
                <th className="px-3 py-3 font-medium w-40">Estado</th>
                <th className="px-3 py-3 font-medium">Fuente</th>
                <th className="px-3 py-3 font-medium w-44">Recibido</th>
              </tr>
            </thead>
            <tbody>
              {filteredDocs.map((doc) => {
                const typeMeta = TYPE_BADGE[doc.document_type] ?? TYPE_BADGE.desconocido;
                const TypeIcon = typeMeta.icon;
                const dateLabel = formatReceivedDate(doc);
                return (
                  <tr key={doc.id} className="border-t hover:bg-muted/30 transition-colors">
                    <td className="px-3 py-3">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
                          typeMeta.cls,
                        )}
                      >
                        <TypeIcon className="h-3 w-3" />
                        {typeMeta.label}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <Link
                        to={`/inbox/${doc.id}`}
                        className="text-blue-600 hover:underline font-medium"
                      >
                        {doc.original_filename ?? doc.id.slice(0, 8)}
                      </Link>
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span
                          className={cn(
                            "inline-block rounded-full px-2 py-0.5 text-xs font-medium",
                            STATUS_BADGE[doc.status],
                          )}
                        >
                          {STATUS_LABEL[doc.status]}
                        </span>
                        <DocWarnings doc={doc} />
                      </div>
                    </td>
                    <td className="px-3 py-3 text-muted-foreground">
                      {doc.source === "email" && doc.source_email ? (
                        <span className="inline-flex items-center gap-1.5">
                          <Mail className="h-3 w-3 text-muted-foreground/70" />
                          <span className="truncate max-w-64" title={doc.source_email}>
                            {doc.source_email}
                          </span>
                        </span>
                      ) : (
                        <span>{doc.source}</span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-muted-foreground text-xs tabular-nums">
                      {dateLabel}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// Warnings inline (badges) por documento
// =============================================================================

/** Estados en los que vale la pena mostrar el aviso "sin oferta" para un pedido. */
const SHOW_LINK_WARNING_STATUSES = new Set<DocumentStatus>(["extracted", "approved"]);

function DocWarnings({ doc }: { doc: DocumentListItem }) {
  const showSinOferta =
    doc.document_type === "pedido" &&
    doc.has_offer_link === false &&
    SHOW_LINK_WARNING_STATUSES.has(doc.status);

  if (!doc.has_blocking_issues && !doc.has_discrepancies && !showSinOferta) return null;

  return (
    <>
      {doc.has_blocking_issues && (
        <span
          title="Aprobación bloqueada por reglas o por precio bajo del mínimo del catálogo"
          className="inline-flex items-center gap-1 rounded-full bg-red-100 text-red-900 border border-red-300 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide"
        >
          <ShieldX className="h-3 w-3" />
          Bloqueado
        </span>
      )}
      {showSinOferta && (
        <span
          title="No se ha encontrado oferta vinculada para este pedido. Sube la oferta o vincúlala manualmente."
          className="inline-flex items-center gap-1 rounded-full bg-amber-100 text-amber-900 border border-amber-300 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide"
        >
          <Link2Off className="h-3 w-3" />
          Sin oferta
        </span>
      )}
      {doc.has_discrepancies && (
        <span
          title="El pedido tiene precios o cantidades distintos a la oferta vinculada"
          className="inline-flex items-center gap-1 rounded-full bg-amber-100 text-amber-900 border border-amber-300 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide"
        >
          <AlertTriangle className="h-3 w-3" />
          Discrepancias
        </span>
      )}
    </>
  );
}

// =============================================================================
// Tabs por estado
// =============================================================================

function StatusTabs({
  value,
  onChange,
  docs,
}: {
  value: StatusFilter;
  onChange: (v: StatusFilter) => void;
  docs: DocumentListItem[];
}) {
  const counts = useMemo(() => {
    const c: Record<StatusFilter, number> = { pending: 0, approved: 0, rejected: 0, processing: 0, all: docs.length };
    for (const d of docs) {
      for (const f of STATUS_FILTERS) {
        if (f.key !== "all" && f.matches(d)) c[f.key]++;
      }
    }
    return c;
  }, [docs]);

  return (
    <div className="flex gap-1 border-b">
      {STATUS_FILTERS.map((f) => {
        const active = value === f.key;
        return (
          <button
            key={f.key}
            onClick={() => onChange(f.key)}
            className={cn(
              "px-3 py-2 text-sm border-b-2 -mb-px transition-colors flex items-center gap-2",
              active
                ? "border-foreground text-foreground font-medium"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {f.label}
            <span
              className={cn(
                "rounded-full text-xs px-1.5 py-0.5 tabular-nums",
                active ? "bg-foreground text-background" : "bg-muted",
              )}
            >
              {counts[f.key]}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// =============================================================================
// Filtro chips por tipo
// =============================================================================

function TypeChips({
  value,
  onChange,
  docs,
  statusFilter,
}: {
  value: TypeFilter;
  onChange: (v: TypeFilter) => void;
  docs: DocumentListItem[];
  statusFilter: StatusFilter;
}) {
  const statusFn = STATUS_FILTERS.find((f) => f.key === statusFilter)!.matches;
  const counts = useMemo(() => {
    const filtered = docs.filter(statusFn);
    const c = { all: filtered.length, pedido: 0, oferta: 0, desconocido: 0 } as Record<TypeFilter, number>;
    for (const d of filtered) {
      const t = d.document_type ?? "desconocido";
      c[t] = (c[t] ?? 0) + 1;
    }
    return c;
  }, [docs, statusFn]);

  const tabs: Array<{ key: TypeFilter; label: string }> = [
    { key: "all", label: "Todos los tipos" },
    { key: "pedido", label: "Pedidos" },
    { key: "oferta", label: "Ofertas" },
    { key: "desconocido", label: "Sin clasificar" },
  ];

  return (
    <div className="flex flex-wrap gap-1.5">
      {tabs.map((t) => {
        const active = value === t.key;
        const count = counts[t.key];
        return (
          <button
            key={t.key}
            onClick={() => onChange(t.key)}
            disabled={count === 0 && t.key !== "all"}
            className={cn(
              "rounded-full border px-2.5 py-0.5 text-xs transition-colors inline-flex items-center gap-1.5",
              active
                ? "bg-zinc-900 text-white border-zinc-900"
                : "bg-white text-muted-foreground border-zinc-300 hover:bg-muted",
              count === 0 && t.key !== "all" && "opacity-40 cursor-not-allowed",
            )}
          >
            {t.label}
            <span className={cn("tabular-nums", active ? "text-white/80" : "text-zinc-500")}>
              {count}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// =============================================================================
// Helpers
// =============================================================================

function formatReceivedDate(doc: DocumentListItem): string {
  const dateStr = doc.email_received_at ?? doc.created_at;
  return new Date(dateStr).toLocaleString("es-ES", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function SyncIndicator({ lastSync, loading }: { lastSync: Date | null; loading: boolean }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 5000);
    return () => clearInterval(t);
  }, []);

  if (loading) {
    return (
      <span className="text-xs text-muted-foreground inline-flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
        Sincronizando...
      </span>
    );
  }
  if (!lastSync) return null;
  const diff = Math.floor((Date.now() - lastSync.getTime()) / 1000);
  const label = diff < 5 ? "ahora" : diff < 60 ? `hace ${diff}s` : `hace ${Math.floor(diff / 60)}m`;
  return (
    <span className="text-xs text-muted-foreground inline-flex items-center gap-1.5">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
      Actualizado {label}
    </span>
  );
}
