/**
 * Cliente HTTP simple hacia la API Pedidoflow.
 * En dev usamos el proxy de Vite (/api → http://localhost:8000).
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export interface HealthResponse {
  status: string;
  version: string;
  timestamp: string;
}

export const api = {
  health: () => request<HealthResponse>("/api/v1/health"),
};
