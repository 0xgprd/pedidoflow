/**
 * Contexto global de auth (Supabase) + tenant resuelto desde el backend.
 *
 * Hook `useAuth()` devuelve:
 *   - session, user (de Supabase)
 *   - tenant (del backend /auth/me — null si aún no hizo onboarding)
 *   - loading (true mientras se inicializa)
 *   - signIn, signUp, signOut, refreshTenant
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { Session, User } from "@supabase/supabase-js";

import { supabase } from "@/lib/supabase";

export interface BackendTenant {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
}

interface AuthState {
  session: Session | null;
  user: User | null;
  tenant: BackendTenant | null;
  loading: boolean;
  error: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** Llama POST /auth/onboard para crear/reclamar el tenant del user. */
  onboard: (payload: {
    name?: string;
    slug?: string;
    claim_slug?: string;
  }) => Promise<BackendTenant>;
  /** Refresca tenant desde el backend (después de onboarding). */
  refreshTenant: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

const BACKEND_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

async function fetchTenant(accessToken: string): Promise<BackendTenant | null> {
  const res = await fetch(`${BACKEND_BASE}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) {
    if (res.status === 401) return null;
    throw new Error(`/auth/me devolvió ${res.status}`);
  }
  const body = (await res.json()) as { tenant: BackendTenant | null };
  return body.tenant;
}

async function postOnboard(
  accessToken: string,
  payload: { name?: string; slug?: string; claim_slug?: string },
): Promise<BackendTenant> {
  const res = await fetch(`${BACKEND_BASE}/api/v1/auth/onboard`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`/auth/onboard ${res.status}: ${await res.text()}`);
  return (await res.json()) as BackendTenant;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [tenant, setTenant] = useState<BackendTenant | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Cuando cambia el session, sincroniza tenant
  const syncTenant = useCallback(async (s: Session | null) => {
    if (!s) {
      setTenant(null);
      return;
    }
    try {
      const t = await fetchTenant(s.access_token);
      setTenant(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    supabase.auth.getSession().then(({ data }) => {
      if (cancelled) return;
      setSession(data.session);
      syncTenant(data.session).finally(() => {
        if (!cancelled) setLoading(false);
      });
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
      syncTenant(newSession);
    });
    return () => {
      cancelled = true;
      sub.subscription.unsubscribe();
    };
  }, [syncTenant]);

  const signIn = useCallback(async (email: string, password: string) => {
    setError(null);
    const { error: e } = await supabase.auth.signInWithPassword({ email, password });
    if (e) throw e;
  }, []);

  const signUp = useCallback(async (email: string, password: string) => {
    setError(null);
    const { error: e } = await supabase.auth.signUp({ email, password });
    if (e) throw e;
  }, []);

  const signOut = useCallback(async () => {
    setError(null);
    await supabase.auth.signOut();
    setTenant(null);
  }, []);

  const onboard = useCallback<AuthState["onboard"]>(
    async (payload) => {
      if (!session) throw new Error("No session");
      const t = await postOnboard(session.access_token, payload);
      setTenant(t);
      return t;
    },
    [session],
  );

  const refreshTenant = useCallback(async () => {
    if (!session) return;
    await syncTenant(session);
  }, [session, syncTenant]);

  const value = useMemo<AuthState>(
    () => ({
      session,
      user: session?.user ?? null,
      tenant,
      loading,
      error,
      signIn,
      signUp,
      signOut,
      onboard,
      refreshTenant,
    }),
    [session, tenant, loading, error, signIn, signUp, signOut, onboard, refreshTenant],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() debe usarse dentro de <AuthProvider>");
  return ctx;
}
