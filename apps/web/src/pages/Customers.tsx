/**
 * Vista "Clientes" — agrega los documentos del tenant por cliente y muestra:
 * - Estado de alta en el ERP (verde si registrado, ámbar si solo aparece en pedidos)
 * - Conteos: pedidos / ofertas / fichas
 * - Total facturado (pedidos approved)
 * - Última actividad
 *
 * No es un CRUD — los clientes "viven" en el ERP. Esto es vista de lectura
 * útil como mini-CRM para el equipo comercial.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  RefreshCw,
  Users,
  Building2,
  CheckCircle2,
  ExternalLink,
  FileText,
  HelpCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { customersApi, getTenantId } from "@/lib/api";
import type { CustomerSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

type FilterKey = "all" | "in_erp" | "ready_to_register" | "no_registration_form";

export function Customers() {
  const [customers, setCustomers] = useState<CustomerSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterKey>("all");

  const refresh = useCallback(async () => {
    if (!getTenantId()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await customersApi.list();
      setCustomers(res.customers);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const filtered = customers.filter((c) =>
    filter === "all" ? true : c.registration_status === filter,
  );

  const counts = {
    all: customers.length,
    in_erp: customers.filter((c) => c.registration_status === "in_erp").length,
    ready_to_register: customers.filter(
      (c) => c.registration_status === "ready_to_register",
    ).length,
    no_registration_form: customers.filter(
      (c) => c.registration_status === "no_registration_form",
    ).length,
  };

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Clientes</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Cartera de clientes que han aparecido en pedidos, ofertas o fichas de alta.
            Para empujar un pedido al ERP el cliente debe estar dado de alta — si
            está <strong>"Sin ficha"</strong>, pídele al cliente que rellene la ficha
            de alta y súbela aquí.
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

      {/* Filtros — 3 estados claros sobre el alta del cliente */}
      <div className="flex gap-1 border-b">
        {(
          [
            { key: "all", label: "Todos", count: counts.all },
            { key: "in_erp", label: "En ERP", count: counts.in_erp },
            {
              key: "ready_to_register",
              label: "Ficha lista para alta",
              count: counts.ready_to_register,
            },
            {
              key: "no_registration_form",
              label: "Sin ficha",
              count: counts.no_registration_form,
            },
          ] as const
        ).map((tab) => {
          const active = filter === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setFilter(tab.key)}
              className={cn(
                "px-3 py-2 text-sm border-b-2 -mb-px transition-colors flex items-center gap-2",
                active
                  ? "border-foreground text-foreground font-medium"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
              <span
                className={cn(
                  "rounded-full text-xs px-1.5 py-0.5 tabular-nums",
                  active ? "bg-foreground text-background" : "bg-muted",
                )}
              >
                {tab.count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Tabla de clientes */}
      {filtered.length === 0 ? (
        <div className="rounded-lg border bg-card p-12 text-center">
          <Users className="h-12 w-12 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            {customers.length === 0
              ? "Aún no han pasado clientes por Order Flow. Sube un PDF o sincroniza el correo."
              : "Sin clientes para este filtro."}
          </p>
        </div>
      ) : (
        <div className="rounded-lg border bg-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left">
              <tr>
                <th className="px-3 py-3 font-medium">Cliente</th>
                <th className="px-3 py-3 font-medium w-40">Estado</th>
                <th className="px-3 py-3 font-medium text-right w-32">Pedidos</th>
                <th className="px-3 py-3 font-medium text-right w-40">Facturado</th>
                <th className="px-3 py-3 font-medium w-40">Última actividad</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr key={c.key} className="border-t hover:bg-muted/30 transition-colors">
                  <td className="px-3 py-3">
                    <div className="flex items-start gap-2">
                      <Building2 className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                      <div className="min-w-0">
                        <div className="font-medium truncate">{c.display_name}</div>
                        <div className="text-xs text-muted-foreground font-mono mt-0.5">
                          {c.eu_vat || c.tax_id || "—"}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-3">
                    <RegistrationStatusBadge customer={c} />
                  </td>
                  <td className="px-3 py-3 text-right">
                    <div className="tabular-nums font-medium">
                      {c.pedidos_count}
                      <span className="text-xs text-muted-foreground ml-1">
                        ({c.pedidos_approved_count} aprob.)
                      </span>
                    </div>
                    {c.pedidos_pushed_to_erp_count > 0 && (
                      <div className="text-xs text-muted-foreground">
                        {c.pedidos_pushed_to_erp_count} en ERP
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-3 text-right tabular-nums font-medium">
                    {c.total_amount_approved > 0
                      ? formatMoney(c.total_amount_approved, c.currency)
                      : "—"}
                  </td>
                  <td className="px-3 py-3 text-xs text-muted-foreground tabular-nums">
                    {c.last_activity_at ? formatDate(c.last_activity_at) : "—"}
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

function RegistrationStatusBadge({ customer }: { customer: CustomerSummary }) {
  if (customer.registration_status === "in_erp") {
    return (
      <div className="space-y-0.5">
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 text-emerald-900 border border-emerald-300 px-2 py-0.5 text-xs font-medium">
          <CheckCircle2 className="h-3 w-3" />
          En ERP
        </span>
        {customer.erp_customer_url && (
          <div>
            <a
              href={customer.erp_customer_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-600 hover:underline inline-flex items-center gap-0.5"
            >
              {customer.erp_customer_id}
              <ExternalLink className="h-2.5 w-2.5" />
            </a>
          </div>
        )}
      </div>
    );
  }
  if (customer.registration_status === "ready_to_register") {
    return (
      <div className="space-y-0.5">
        <span className="inline-flex items-center gap-1 rounded-full bg-indigo-100 text-indigo-900 border border-indigo-300 px-2 py-0.5 text-xs font-medium">
          <FileText className="h-3 w-3" />
          Ficha lista
        </span>
        {customer.registration_document_id && (
          <div>
            <Link
              to={`/inbox/${customer.registration_document_id}`}
              className="text-xs text-blue-600 hover:underline"
            >
              Revisar y dar de alta →
            </Link>
          </div>
        )}
      </div>
    );
  }
  // no_registration_form
  return (
    <div className="space-y-0.5">
      <span
        className="inline-flex items-center gap-1 rounded-full bg-zinc-100 text-zinc-700 border border-zinc-300 px-2 py-0.5 text-xs font-medium"
        title="Este cliente solo aparece en pedidos/ofertas. Para darlo de alta en el ERP necesitas su ficha de alta — pídesela al cliente."
      >
        <HelpCircle className="h-3 w-3" />
        Sin ficha
      </span>
    </div>
  );
}

function formatMoney(value: number, currency: string): string {
  const symbol = currency === "EUR" ? "€" : currency === "USD" ? "$" : currency;
  return `${value.toLocaleString("es-ES", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} ${symbol}`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("es-ES", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
