import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { api, clearTenantId, getTenantId, setTenantId } from "@/lib/api";
import type { TenantRead } from "@/lib/api";

interface Props {
  onChanged?: () => void;
}

/**
 * Pre-Clerk: el tenant_id se selecciona manualmente y se guarda en localStorage.
 * Cuando integremos Clerk, este banner desaparece (el tenant viene del JWT).
 */
export function TenantBanner({ onChanged }: Props) {
  const [tenants, setTenants] = useState<TenantRead[]>([]);
  const [active, setActive] = useState<string | null>(getTenantId());
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  useEffect(() => {
    api.listTenants().then(setTenants).catch(() => setTenants([]));
  }, []);

  const select = (id: string) => {
    setTenantId(id);
    setActive(id);
    onChanged?.();
  };

  const clear = () => {
    clearTenantId();
    setActive(null);
    onChanged?.();
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    const slug = newName.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    try {
      const t = await api.createTenant({ name: newName.trim(), slug });
      setTenants((prev) => [...prev, t]);
      select(t.id);
      setNewName("");
      setCreating(false);
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    }
  };

  if (active) {
    const tenant = tenants.find((t) => t.id === active);
    return (
      <div className="rounded-md border bg-muted/40 px-4 py-2 text-xs text-muted-foreground flex items-center justify-between">
        <span>
          Tenant activo: <strong>{tenant?.name ?? active.slice(0, 8)}</strong>
        </span>
        <button
          onClick={clear}
          className="text-blue-600 hover:underline"
        >
          cambiar
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-md border border-amber-300 bg-amber-50 p-4 space-y-3">
      <div className="text-sm font-medium text-amber-900">
        Selecciona un tenant para empezar
      </div>
      {tenants.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {tenants.map((t) => (
            <Button key={t.id} size="sm" variant="outline" onClick={() => select(t.id)}>
              {t.name}
            </Button>
          ))}
        </div>
      )}
      {creating ? (
        <div className="flex gap-2">
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Nombre tenant (ej: Quimilock)"
            className="flex-1 rounded border px-2 py-1 text-sm"
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
          <Button size="sm" onClick={handleCreate}>
            Crear
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setCreating(false)}>
            Cancelar
          </Button>
        </div>
      ) : (
        <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
          + Nuevo tenant
        </Button>
      )}
    </div>
  );
}
