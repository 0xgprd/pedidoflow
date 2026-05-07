import { Link, NavLink, Outlet } from "react-router-dom";
import { Inbox, BookOpen, Home as HomeIcon, Brain, Plug, Workflow } from "lucide-react";

import { cn } from "@/lib/utils";

const navItems = [
  { to: "/", label: "Inicio", icon: HomeIcon },
  { to: "/inbox", label: "Bandeja", icon: Inbox },
  { to: "/memory", label: "Memoria", icon: Brain },
  { to: "/rules", label: "Reglas", icon: Workflow },
  { to: "/integrations", label: "Integraciones", icon: Plug },
  { to: "/catalog", label: "Catálogo", icon: BookOpen },
];

export function Layout() {
  return (
    <div className="min-h-screen flex">
      <aside className="w-60 border-r bg-card p-4 flex flex-col gap-1">
        <Link to="/" className="text-xl font-semibold mb-6 px-2">
          Pedidoflow
        </Link>
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors",
                isActive
                  ? "bg-accent text-accent-foreground font-medium"
                  : "text-muted-foreground hover:bg-accent/50",
              )
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
        <div className="mt-auto text-xs text-muted-foreground px-2">
          v0.0.1 · Fase 0
        </div>
      </aside>

      <main className="flex-1 p-8">
        <Outlet />
      </main>
    </div>
  );
}
