import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Inbox,
  BookOpen,
  Home as HomeIcon,
  Brain,
  Plug,
  Workflow,
  LogOut,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/AuthContext";

const navItems = [
  { to: "/dashboard", label: "Inicio", icon: HomeIcon },
  { to: "/inbox", label: "Bandeja", icon: Inbox },
  { to: "/memory", label: "Memoria", icon: Brain },
  { to: "/rules", label: "Reglas", icon: Workflow },
  { to: "/integrations", label: "Integraciones", icon: Plug },
  { to: "/catalog", label: "Catálogo", icon: BookOpen },
];

export function Layout() {
  const { user, tenant, signOut } = useAuth();
  const navigate = useNavigate();

  const handleSignOut = async () => {
    await signOut();
    navigate("/sign-in", { replace: true });
  };

  return (
    <div className="min-h-screen flex">
      <aside className="w-60 border-r bg-card p-4 flex flex-col gap-1">
        <Link to="/?view=landing" className="text-xl font-semibold mb-6 px-2">
          Order Flow
        </Link>
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/dashboard"}
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

        <div className="mt-auto pt-4 border-t space-y-2">
          {tenant && (
            <div className="px-2 text-xs">
              <div className="font-medium truncate">{tenant.name}</div>
              <div className="text-muted-foreground truncate">{user?.email}</div>
            </div>
          )}
          <button
            onClick={handleSignOut}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-muted-foreground hover:bg-red-50 hover:text-red-700 transition-colors"
          >
            <LogOut className="h-4 w-4" />
            Cerrar sesión
          </button>
          <div className="text-[10px] text-muted-foreground px-2">v0.0.2 · Fase 2</div>
        </div>
      </aside>

      <main className="flex-1 p-8">
        <Outlet />
      </main>
    </div>
  );
}
