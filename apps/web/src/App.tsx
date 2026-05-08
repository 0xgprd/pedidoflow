import { Route, Routes } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { RequireAuth } from "@/components/RequireAuth";
import { AuthProvider } from "@/lib/AuthContext";
import { Inbox } from "@/pages/Inbox";
import { DocumentDetail } from "@/pages/DocumentDetail";
import { Home } from "@/pages/Home";
import { Catalog } from "@/pages/Catalog";
import { Customers } from "@/pages/Customers";
import { Memory } from "@/pages/Memory";
import { Integrations } from "@/pages/Integrations";
import { Rules } from "@/pages/Rules";
import { SignIn } from "@/pages/SignIn";
import { SignUp } from "@/pages/SignUp";
import { Onboarding } from "@/pages/Onboarding";
import { Landing } from "@/pages/Landing";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Públicas */}
        <Route path="/" element={<Landing />} />
        <Route path="/sign-in" element={<SignIn />} />
        <Route path="/sign-up" element={<SignUp />} />
        <Route path="/onboarding" element={<Onboarding />} />

        {/* Protegidas: requieren auth + tenant */}
        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route path="/dashboard" element={<Home />} />
            <Route path="/inbox" element={<Inbox />} />
            <Route path="/inbox/:id" element={<DocumentDetail />} />
            <Route path="/clientes" element={<Customers />} />
            {/* /clientes/alta es atajo a las fichas pendientes en bandeja */}
            <Route
              path="/clientes/alta"
              element={<Inbox />}
            />
            <Route path="/catalog" element={<Catalog />} />
            <Route path="/memory" element={<Memory />} />
            <Route path="/rules" element={<Rules />} />
            <Route path="/integrations" element={<Integrations />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  );
}
