import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  RefreshCw,
  Inbox as InboxIcon,
  FileText,
  FileCheck2,
  AlertTriangle,
  ShieldX,
  Link2,
  CheckCircle2,
  Workflow as WorkflowIcon,
  BookOpen,
  TrendingUp,
  Briefcase,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { dashboardApi, getTenantId } from "@/lib/api";
import type { DashboardStats } from "@/lib/api";
import { cn } from "@/lib/utils";

export function Home() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!getTenantId()) return;
    setLoading(true);
    setError(null);
    try {
      setStats(await dashboardApi.stats());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="space-y-5 max-w-6xl">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Inicio</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Resumen del estado de tus pedidos y ofertas.
          </p>
        </div>
        <Button variant="outline" onClick={refresh} disabled={loading}>
          <RefreshCw className={cn("h-4 w-4 mr-2", loading && "animate-spin")} />
          Refrescar
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </div>
      )}

      {!getTenantId() && !error && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          Selecciona un tenant arriba para ver el dashboard.
        </div>
      )}

      {stats && (
        <>
          {/* Hero stats — 4 KPIs principales (sólo pedidos: las ofertas son
              catálogo pasivo y no representan facturación) */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <KpiCard
              icon={TrendingUp}
              label="€ facturado (30d)"
              value={formatMoney(stats.amounts.approved_total_30d, stats.amounts.currency)}
              sub="suma TTC de pedidos aprobados"
              accent="emerald"
              isMoney
            />
            <KpiCard
              icon={CheckCircle2}
              label="Pedidos aprobados (30d)"
              value={stats.approval_rate.approved_30d}
              sub={
                stats.approval_rate.rate !== null
                  ? `${Math.round(stats.approval_rate.rate * 100)}% de los decididos`
                  : "sin datos"
              }
              accent="emerald"
            />
            <KpiCard
              icon={AlertTriangle}
              label="Pedidos a revisar"
              value={stats.needs_review.count}
              sub={
                stats.needs_review.blocked_by_rules > 0
                  ? `${stats.needs_review.blocked_by_rules} bloqueados por reglas`
                  : "pendientes de aprobación"
              }
              accent={stats.needs_review.blocked_by_rules > 0 ? "red" : "amber"}
              link="/inbox?status=extracted"
            />
            <KpiCard
              icon={Briefcase}
              label="€ en ofertas"
              value={formatMoney(stats.offers.total_amount, stats.offers.currency)}
              sub={`${stats.offers.count} ofertas activas en pipeline`}
              accent="violet"
              isMoney
              link="/inbox?type=oferta"
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            {/* Tipos */}
            <Section title="Por tipo" icon={FileText}>
              <BarRow label="Pedidos" value={stats.documents.by_type.pedido} total={stats.documents.total} color="bg-sky-500" />
              <BarRow label="Ofertas" value={stats.documents.by_type.oferta} total={stats.documents.total} color="bg-violet-500" />
              <BarRow label="Sin clasificar" value={stats.documents.by_type.desconocido} total={stats.documents.total} color="bg-zinc-400" />
            </Section>

            {/* Estados */}
            <Section title="Por estado" icon={FileCheck2}>
              <BarRow label="Extracted (revisar)" value={stats.documents.by_status.extracted} total={stats.documents.total} color="bg-emerald-400" />
              <BarRow label="Approved" value={stats.documents.by_status.approved} total={stats.documents.total} color="bg-green-600" />
              <BarRow label="Rejected" value={stats.documents.by_status.rejected} total={stats.documents.total} color="bg-zinc-500" />
              <BarRow label="Failed" value={stats.documents.by_status.failed} total={stats.documents.total} color="bg-red-500" />
              <BarRow label="Processing/Pending" value={stats.documents.by_status.processing + stats.documents.by_status.pending} total={stats.documents.total} color="bg-blue-400" />
            </Section>

            {/* Vinculación pedido↔oferta */}
            <Section title="Pedidos vinculados a oferta" icon={Link2}>
              <BarRow
                label="Con oferta"
                value={stats.linking.pedidos_with_offer}
                total={stats.linking.pedidos_with_offer + stats.linking.pedidos_without_offer}
                color="bg-emerald-500"
              />
              <BarRow
                label="Sin oferta"
                value={stats.linking.pedidos_without_offer}
                total={stats.linking.pedidos_with_offer + stats.linking.pedidos_without_offer}
                color="bg-amber-500"
              />
              {stats.linking.pedidos_without_offer > 0 && (
                <Link to="/inbox?type=pedido" className="text-xs text-blue-600 hover:underline mt-2 inline-block">
                  Ver pedidos →
                </Link>
              )}
            </Section>

            {/* Reglas activas */}
            <Section title="Reglas workflow" icon={WorkflowIcon}>
              <div className="text-sm">
                <strong>{stats.rules.active_count}</strong> activas
                {stats.rules.total_count > stats.rules.active_count && (
                  <span className="text-muted-foreground"> · {stats.rules.total_count - stats.rules.active_count} desactivadas</span>
                )}
              </div>
              {stats.rules.top_5.length > 0 ? (
                <div className="mt-3 space-y-1">
                  <div className="text-xs uppercase text-muted-foreground tracking-wide">Más aplicadas</div>
                  {stats.rules.top_5.map((r) => (
                    <div key={r.id} className="flex items-center justify-between text-sm">
                      <span className="truncate">{r.name}</span>
                      <span className="text-xs bg-emerald-100 text-emerald-900 rounded-full px-2 py-0.5 ml-2 shrink-0">{r.hits}×</span>
                    </div>
                  ))}
                </div>
              ) : (
                <Link to="/rules" className="text-xs text-blue-600 hover:underline mt-2 inline-block">
                  Crear primera regla →
                </Link>
              )}
            </Section>

            {/* Catálogo */}
            <Section title="Catálogo" icon={BookOpen}>
              <div className="text-sm space-y-1">
                <div>
                  <strong>{stats.catalog.items_count}</strong> referencias
                </div>
                {stats.catalog.items_without_min_price > 0 && (
                  <div className="text-amber-700">
                    <strong>{stats.catalog.items_without_min_price}</strong> sin precio mínimo
                  </div>
                )}
              </div>
              <Link to="/catalog" className="text-xs text-blue-600 hover:underline mt-2 inline-block">
                Gestionar catálogo →
              </Link>
            </Section>

            {/* Aprobación 30d */}
            <Section title="Decisiones (30d)" icon={CheckCircle2}>
              <div className="grid grid-cols-2 gap-3 text-center">
                <div className="rounded bg-emerald-50 p-3">
                  <div className="text-2xl font-semibold text-emerald-900 tabular-nums">{stats.approval_rate.approved_30d}</div>
                  <div className="text-xs text-emerald-800 uppercase tracking-wide">Aprobados</div>
                </div>
                <div className="rounded bg-zinc-100 p-3">
                  <div className="text-2xl font-semibold text-zinc-700 tabular-nums">{stats.approval_rate.rejected_30d}</div>
                  <div className="text-xs text-zinc-600 uppercase tracking-wide">Rechazados</div>
                </div>
              </div>
            </Section>
          </div>

          {/* Bloqueos urgentes */}
          {(stats.needs_review.blocked_by_rules > 0 || stats.needs_review.with_validation_blocking > 0) && (
            <div className="rounded-lg border border-red-300 bg-red-50 p-4">
              <div className="flex items-center gap-2 font-semibold text-red-900">
                <ShieldX className="h-5 w-5" />
                Pedidos con bloqueos
              </div>
              <ul className="mt-2 text-sm text-red-900 space-y-1">
                {stats.needs_review.blocked_by_rules > 0 && (
                  <li>• {stats.needs_review.blocked_by_rules} bloqueado(s) por reglas workflow</li>
                )}
                {stats.needs_review.with_validation_blocking > 0 && (
                  <li>• {stats.needs_review.with_validation_blocking} con líneas bajo precio mínimo del catálogo</li>
                )}
              </ul>
              <Link to="/inbox?status=extracted" className="text-sm text-red-900 underline hover:no-underline mt-2 inline-block">
                Ir a la bandeja →
              </Link>
            </div>
          )}

          {/* Documentos recientes */}
          <Section title="Recientes (10)" icon={InboxIcon} fullWidth>
            {stats.recent_documents.length === 0 ? (
              <p className="text-sm text-muted-foreground italic">Sin documentos aún. Sube uno desde la bandeja.</p>
            ) : (
              <div className="divide-y">
                {stats.recent_documents.map((d) => (
                  <Link
                    key={d.id}
                    to={`/inbox/${d.id}`}
                    className="flex items-center gap-3 py-2 hover:bg-muted/30 -mx-4 px-4"
                  >
                    <span
                      className={cn(
                        "inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-medium uppercase",
                        d.document_type === "pedido" && "bg-sky-100 text-sky-900 border-sky-300",
                        d.document_type === "oferta" && "bg-violet-100 text-violet-900 border-violet-300",
                        d.document_type === "desconocido" && "bg-zinc-100 text-zinc-700 border-zinc-300",
                      )}
                    >
                      {d.document_type === "desconocido" ? "?" : d.document_type}
                    </span>
                    <span className="flex-1 truncate text-sm">{d.original_filename ?? d.id.slice(0, 8)}</span>
                    <StatusBadge status={d.status} />
                    <span className="text-xs text-muted-foreground tabular-nums shrink-0 w-32 text-right">
                      {new Date(d.created_at).toLocaleString("es-ES")}
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </Section>
        </>
      )}
    </div>
  );
}

// =============================================================================
// Componentes
// =============================================================================

const ACCENT_COLORS = {
  zinc: "bg-zinc-50 border-zinc-200 text-zinc-900",
  amber: "bg-amber-50 border-amber-200 text-amber-900",
  red: "bg-red-50 border-red-200 text-red-900",
  emerald: "bg-emerald-50 border-emerald-200 text-emerald-900",
  violet: "bg-violet-50 border-violet-200 text-violet-900",
} as const;

function KpiCard({
  icon: Icon,
  label,
  value,
  sub,
  accent,
  link,
  isMoney,
}: {
  icon: typeof InboxIcon;
  label: string;
  value: number | string;
  sub?: string;
  accent: keyof typeof ACCENT_COLORS;
  link?: string;
  isMoney?: boolean;
}) {
  const content = (
    <div
      className={cn(
        "rounded-lg border p-4 transition-shadow",
        ACCENT_COLORS[accent],
        link && "cursor-pointer hover:shadow-sm",
      )}
    >
      <div className="flex items-start justify-between">
        <div className="text-xs uppercase tracking-wide opacity-80">{label}</div>
        <Icon className="h-4 w-4 opacity-60" />
      </div>
      <div className={cn("mt-2 font-semibold tabular-nums", isMoney ? "text-xl" : "text-3xl")}>
        {value}
      </div>
      {sub && <div className="text-xs mt-1 opacity-70">{sub}</div>}
    </div>
  );
  return link ? <Link to={link}>{content}</Link> : content;
}

function Section({
  title,
  icon: Icon,
  children,
  fullWidth,
}: {
  title: string;
  icon: typeof InboxIcon;
  children: React.ReactNode;
  fullWidth?: boolean;
}) {
  return (
    <div className={cn("rounded-lg border bg-card p-4", fullWidth && "lg:col-span-3")}>
      <div className="flex items-center gap-2 mb-3 text-sm font-medium">
        <Icon className="h-4 w-4 text-muted-foreground" />
        {title}
      </div>
      {children}
    </div>
  );
}

function BarRow({
  label,
  value,
  total,
  color,
}: {
  label: string;
  value: number;
  total: number;
  color: string;
}) {
  const pct = total > 0 ? (value / total) * 100 : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="tabular-nums font-medium">{value}</span>
      </div>
      <div className="h-1.5 bg-muted rounded-full overflow-hidden">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

const STATUS_PILL: Record<string, string> = {
  pending: "bg-slate-200 text-slate-800",
  processing: "bg-blue-200 text-blue-900",
  extracted: "bg-slate-100 text-slate-700",
  failed: "bg-red-200 text-red-900",
  approved: "bg-green-300 text-green-900",
  rejected: "bg-zinc-300 text-zinc-800",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn("inline-block rounded-full px-2 py-0.5 text-xs font-medium shrink-0", STATUS_PILL[status])}>
      {status}
    </span>
  );
}

function formatMoney(value: number, currency: string): string {
  const symbol = currency === "EUR" ? "€" : currency === "USD" ? "$" : currency;
  return `${value.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${symbol}`;
}
