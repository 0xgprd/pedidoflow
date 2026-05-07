import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Building2, Loader2, ArrowRight, ArrowDownToLine } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/AuthContext";

/**
 * Onboarding tras signup: el user elige si crea un espacio nuevo o reclama
 * uno huérfano (caso Quimilock pre-auth).
 */
export function Onboarding() {
  const { user, tenant, onboard, loading } = useAuth();
  const navigate = useNavigate();

  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"create" | "claim">("create");
  const [claimSlug, setClaimSlug] = useState("");

  // Si ya tiene tenant, fuera de aquí
  useEffect(() => {
    if (!loading && tenant) navigate("/", { replace: true });
  }, [loading, tenant, navigate]);

  // Pre-rellenar el nombre con el local-part del email
  useEffect(() => {
    if (user?.email && !name) {
      const local = user.email.split("@")[0];
      setName(local.charAt(0).toUpperCase() + local.slice(1));
    }
  }, [user, name]);

  const handleCreate = async () => {
    setError(null);
    setBusy(true);
    try {
      await onboard({ name: name.trim() || undefined });
      navigate("/", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleClaim = async () => {
    setError(null);
    setBusy(true);
    try {
      await onboard({ claim_slug: claimSlug.trim() });
      navigate("/", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-50 px-4">
      <div className="w-full max-w-md space-y-6 bg-white p-8 rounded-lg border shadow-sm">
        <div className="text-center">
          <Building2 className="h-10 w-10 text-violet-600 mx-auto" />
          <h1 className="text-xl font-semibold tracking-tight mt-3">Configura tu espacio</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Bienvenido{user?.email ? `, ${user.email}` : ""}. Cada cuenta tiene su propio espacio
            con su catálogo, sus reglas y sus pedidos.
          </p>
        </div>

        <div className="flex border rounded-md overflow-hidden text-sm">
          <button
            onClick={() => setMode("create")}
            className={
              mode === "create"
                ? "flex-1 px-3 py-2 bg-violet-600 text-white"
                : "flex-1 px-3 py-2 hover:bg-zinc-50"
            }
          >
            Crear nuevo
          </button>
          <button
            onClick={() => setMode("claim")}
            className={
              mode === "claim"
                ? "flex-1 px-3 py-2 bg-violet-600 text-white"
                : "flex-1 px-3 py-2 hover:bg-zinc-50"
            }
          >
            Reclamar existente
          </button>
        </div>

        {mode === "create" ? (
          <div className="space-y-3">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Nombre del espacio (tu empresa)
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded border px-3 py-2 text-sm"
              placeholder="ej: Quimilock, ACME Industries..."
            />
            <Button onClick={handleCreate} disabled={busy} className="w-full">
              {busy ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <ArrowRight className="h-4 w-4 mr-2" />
              )}
              Crear espacio
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Slug del espacio existente
            </label>
            <input
              type="text"
              value={claimSlug}
              onChange={(e) => setClaimSlug(e.target.value)}
              className="w-full rounded border px-3 py-2 text-sm font-mono"
              placeholder="ej: quimilock"
            />
            <p className="text-xs text-muted-foreground">
              Solo si ya existe un espacio sin user vinculado (migración legacy).
            </p>
            <Button
              onClick={handleClaim}
              disabled={busy || !claimSlug.trim()}
              className="w-full"
              variant="outline"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <ArrowDownToLine className="h-4 w-4 mr-2" />
              )}
              Reclamar este espacio
            </Button>
          </div>
        )}

        {error && (
          <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-900">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
