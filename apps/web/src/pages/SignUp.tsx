import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { UserPlus, Loader2, CheckCircle2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/AuthContext";

export function SignUp() {
  const { signUp } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < 6) {
      setError("La contraseña debe tener al menos 6 caracteres.");
      return;
    }
    setBusy(true);
    try {
      await signUp(email.trim(), password);
      setDone(true);
      // Si Supabase no requiere email confirm, el session ya está activo →
      // AuthContext lo detecta y syncTenant carga (será null) → onboarding.
      // Esperamos un tick para que se propague el session.
      setTimeout(() => navigate("/onboarding", { replace: true }), 800);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-zinc-50 px-4">
        <div className="w-full max-w-sm space-y-4 bg-white p-8 rounded-lg border shadow-sm text-center">
          <CheckCircle2 className="h-12 w-12 text-emerald-500 mx-auto" />
          <h2 className="text-lg font-semibold">Cuenta creada</h2>
          <p className="text-sm text-muted-foreground">
            Si tienes la verificación de email activada en Supabase, recibirás un correo de
            confirmación. Si no, te llevamos al onboarding...
          </p>
          <Loader2 className="h-5 w-5 animate-spin mx-auto text-muted-foreground" />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-50 px-4">
      <div className="w-full max-w-sm space-y-6 bg-white p-8 rounded-lg border shadow-sm">
        <div className="text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Order Flow</h1>
          <p className="text-sm text-muted-foreground mt-1">Crear cuenta nueva</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="email" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Correo
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded border px-3 py-2 text-sm"
              placeholder="tu@empresa.com"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="password" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Contraseña
            </label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded border px-3 py-2 text-sm"
              placeholder="mínimo 6 caracteres"
            />
          </div>

          {error && (
            <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-900">
              {error}
            </div>
          )}

          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <UserPlus className="h-4 w-4 mr-2" />
            )}
            Crear cuenta
          </Button>
        </form>

        <div className="text-xs text-center text-muted-foreground">
          ¿Ya tienes cuenta?{" "}
          <Link to="/sign-in" className="text-blue-600 hover:underline">
            Iniciar sesión
          </Link>
        </div>
      </div>
    </div>
  );
}
