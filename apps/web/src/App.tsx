import { Route, Routes } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { RequireAuth } from "@/components/RequireAuth";
import { AuthProvider } from "@/lib/AuthContext";
import { Inbox } from "@/pages/Inbox";
import { DocumentDetail } from "@/pages/DocumentDetail";
import { Home } from "@/pages/Home";
import { Catalog } from "@/pages/Catalog";
import { Memory } from "@/pages/Memory";
import { Integrations } from "@/pages/Integrations";
import { Rules } from "@/pages/Rules";
import { SignIn } from "@/pages/SignIn";
import { SignUp } from "@/pages/SignUp";
import { Onboarding } from "@/pages/Onboarding";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Públicas */}
        <Route path="/sign-in" element={<SignIn />} />
        <Route path="/sign-up" element={<SignUp />} />
        <Route path="/onboarding" element={<Onboarding />} />

        {/* Protegidas: requieren auth + tenant */}
        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route path="/" element={<Home />} />
            <Route path="/inbox" element={<Inbox />} />
            <Route path="/inbox/:id" element={<DocumentDetail />} />
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
