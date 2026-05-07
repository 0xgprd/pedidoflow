import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Mail, Plug, RefreshCw, Trash2, Zap, AlertTriangle, CheckCircle2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { TenantBanner } from "@/components/TenantBanner";
import { getTenantId, integrationsApi } from "@/lib/api";
import type { EmailIntegrationRead, IntegrationStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS_BADGE: Record<IntegrationStatus, string> = {
  pending: "bg-slate-200 text-slate-800",
  active: "bg-emerald-200 text-emerald-900",
  expired: "bg-amber-200 text-amber-900",
  error: "bg-red-200 text-red-900",
  disabled: "bg-zinc-200 text-zinc-700",
};

const STATUS_LABEL: Record<IntegrationStatus, string> = {
  pending: "Pendiente",
  active: "Activa",
  expired: "Expirada — reconectar",
  error: "Error",
  disabled: "Desactivada",
};

export function Integrations() {
  const [params] = useSearchParams();
  const [items, setItems] = useState<EmailIntegrationRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [polling, setPolling] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!getTenantId()) return;
    setLoading(true);
    setError(null);
    try {
      setItems(await integrationsApi.list());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleConnect = async () => {
    setConnecting(true);
    setError(null);
    try {
      const { authorization_url } = await integrationsApi.connectOutlook();
      window.location.href = authorization_url;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setConnecting(false);
    }
  };

  const handleDisconnect = async (id: string, email: string) => {
    if (!confirm(`¿Desconectar ${email}? Dejará de recibir pedidos por correo.`)) return;
    try {
      await integrationsApi.disconnect(id);
      setItems((prev) => prev.filter((i) => i.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const [info, setInfo] = useState<string | null>(null);

  const handlePollNow = async (id: string) => {
    setPolling(id);
    setError(null);
    setInfo(null);
    try {
      const r = await integrationsApi.pollNow(id);
      setInfo(r.message);
      // Refrescamos varias veces para que el usuario vea cómo el status pasa
      // de "Error" a "Activa" y aparezca el "último sync"
      setTimeout(refresh, 500);
      setTimeout(refresh, 3000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPolling(null);
    }
  };

  const connectedEmail = params.get("connected");
  const callbackError = params.get("error");

  return (
    <div className="space-y-5">
      <TenantBanner onChanged={refresh} />

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Plug className="h-6 w-6 text-sky-600" />
            Integraciones
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Conecta tu correo para que los pedidos lleguen automáticamente a la bandeja.
          </p>
        </div>
        <Button variant="outline" onClick={refresh} disabled={loading}>
          <RefreshCw className={cn("h-4 w-4 mr-2", loading && "animate-spin")} />
          Refrescar
        </Button>
      </div>

      {connectedEmail && (
        <div className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-900 flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4" />
          Conectado: <strong>{connectedEmail}</strong>
        </div>
      )}
      {callbackError && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4" />
          Error de conexión: {callbackError}
        </div>
      )}
      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </div>
      )}
      {info && (
        <div className="rounded-md border border-sky-300 bg-sky-50 p-3 text-sm text-sky-900 flex items-center justify-between gap-3">
          <span>{info}</span>
          <Link to="/inbox" className="text-blue-600 hover:underline whitespace-nowrap">
            Ver bandeja →
          </Link>
        </div>
      )}

      {/* Card Outlook (siempre visible para conectar) */}
      <div className="rounded-lg border bg-card p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="rounded-md bg-blue-50 p-2">
              <Mail className="h-6 w-6 text-blue-600" />
            </div>
            <div>
              <h3 className="font-semibold">Microsoft Outlook</h3>
              <p className="text-sm text-muted-foreground mt-0.5">
                Vigilamos tu bandeja de entrada. Cada email con PDF adjunto crea un pedido.
              </p>
            </div>
          </div>
          <Button onClick={handleConnect} disabled={connecting || !getTenantId()}>
            {connecting ? "Redirigiendo..." : "Conectar cuenta"}
          </Button>
        </div>
      </div>

      {/* Lista de integraciones conectadas */}
      {items.length > 0 && (
        <div className="rounded-lg border bg-card overflow-hidden">
          <div className="px-4 py-2.5 border-b bg-muted/30">
            <h2 className="text-sm font-semibold">Cuentas conectadas ({items.length})</h2>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-muted/30 text-left">
              <tr>
                <th className="px-4 py-2 font-medium">Cuenta</th>
                <th className="px-4 py-2 font-medium">Estado</th>
                <th className="px-4 py-2 font-medium">Último sync</th>
                <th className="px-4 py-2 font-medium w-44 text-right">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} className="border-t">
                  <td className="px-4 py-3">
                    <div className="font-medium">{it.email}</div>
                    {it.display_name && (
                      <div className="text-xs text-muted-foreground">{it.display_name}</div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "inline-block rounded-full px-2 py-0.5 text-xs font-medium",
                        STATUS_BADGE[it.status],
                      )}
                    >
                      {STATUS_LABEL[it.status]}
                    </span>
                    {it.last_error && (
                      <div className="text-xs text-red-700 mt-1 font-mono">{it.last_error}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground text-xs">
                    {it.last_polled_at
                      ? new Date(it.last_polled_at).toLocaleString("es-ES")
                      : "Nunca"}
                  </td>
                  <td className="px-4 py-3 text-right space-x-1">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={
                        polling === it.id ||
                        it.status === "disabled" ||
                        it.status === "pending"
                      }
                      onClick={() => handlePollNow(it.id)}
                      title={
                        it.status === "error"
                          ? "Reintentar tras error"
                          : it.status === "expired"
                            ? "Renueva el token e intenta sincronizar"
                            : "Sincronizar ahora"
                      }
                    >
                      <Zap className={cn("h-3 w-3 mr-1", polling === it.id && "animate-pulse")} />
                      Sincronizar
                    </Button>
                    <button
                      onClick={() => handleDisconnect(it.id, it.email)}
                      title="Desconectar"
                      className="text-red-600 hover:text-red-800 p-1.5 rounded hover:bg-red-50 align-middle"
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

      <details className="rounded-lg border bg-card">
        <summary className="px-4 py-2 text-xs font-medium text-muted-foreground cursor-pointer select-none">
          ¿Cómo funciona?
        </summary>
        <div className="px-4 pb-4 text-sm text-muted-foreground space-y-2">
          <p>
            Cuando conectas Outlook, autorizas a Pedidoflow a leer correos entrantes con adjuntos.
            Un worker de fondo (cada ~5 min) consulta tu bandeja:
          </p>
          <ol className="list-decimal list-inside space-y-1 ml-2">
            <li>Solo procesamos correos nuevos desde la última sincronización.</li>
            <li>Por cada PDF adjunto, creamos un pedido en la <Link to="/inbox" className="text-blue-600 hover:underline">bandeja</Link>.</li>
            <li>El pipeline de OCR + IA + reglas se aplica igual que con uploads manuales.</li>
            <li>El correo original queda en tu Outlook intacto.</li>
          </ol>
        </div>
      </details>
    </div>
  );
}
