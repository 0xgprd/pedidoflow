import { useEffect, useState } from "react";

import { api, type HealthResponse } from "@/lib/api";

export function Home() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Pedidoflow</h1>
        <p className="text-muted-foreground mt-1">
          Automatiza la entrada de pedidos en Sage 200 y otros ERPs.
        </p>
      </div>

      <div className="rounded-lg border bg-card p-6">
        <h2 className="text-lg font-semibold mb-3">Estado del backend</h2>
        {error && (
          <div className="text-destructive text-sm">
            ⚠ No se ha podido conectar con la API: {error}
          </div>
        )}
        {!error && !health && <div className="text-sm">Comprobando…</div>}
        {health && (
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt className="text-muted-foreground">Status</dt>
            <dd className="font-mono">{health.status}</dd>
            <dt className="text-muted-foreground">Versión</dt>
            <dd className="font-mono">{health.version}</dd>
            <dt className="text-muted-foreground">Timestamp</dt>
            <dd className="font-mono text-xs">{health.timestamp}</dd>
          </dl>
        )}
      </div>

      <div className="rounded-lg border bg-card p-6">
        <h2 className="text-lg font-semibold mb-3">Roadmap</h2>
        <ul className="space-y-1 text-sm">
          <li>✅ Fase 0 — Setup repo + skeleton</li>
          <li>⬜ Fase 1 — Document ingestion + extracción IA</li>
          <li>⬜ Fase 2 — Catálogo + memoria (pgvector)</li>
          <li>⬜ Fase 3 — UI revisión + field mapping</li>
          <li>⬜ Fase 4 — Conector Outlook</li>
          <li>⬜ Fase 5 — Sage 200 integration</li>
          <li>⬜ Fase 6 — Onboarding Quimilock</li>
        </ul>
      </div>
    </div>
  );
}
