export function Inbox() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Bandeja</h1>
        <p className="text-muted-foreground mt-1">
          Pedidos pendientes de revisión, aprobados, rechazados.
        </p>
      </div>

      <div className="rounded-lg border bg-card p-12 text-center text-muted-foreground">
        <p className="text-sm">Aún no hay pedidos.</p>
        <p className="text-xs mt-2">
          Próximamente — Fase 1: ingesta automática de email + extracción IA.
        </p>
      </div>
    </div>
  );
}
