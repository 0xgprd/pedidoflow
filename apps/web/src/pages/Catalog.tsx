export function Catalog() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Catálogo</h1>
        <p className="text-muted-foreground mt-1">
          Productos, mapeo de referencias por cliente, reglas.
        </p>
      </div>

      <div className="rounded-lg border bg-card p-12 text-center text-muted-foreground">
        <p className="text-sm">Aún no hay catálogo cargado.</p>
        <p className="text-xs mt-2">
          Próximamente — Fase 2: import CSV/Excel del catálogo del cliente.
        </p>
      </div>
    </div>
  );
}
