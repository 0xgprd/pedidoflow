import { Route, Routes } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { Inbox } from "@/pages/Inbox";
import { DocumentDetail } from "@/pages/DocumentDetail";
import { Home } from "@/pages/Home";
import { Catalog } from "@/pages/Catalog";
import { Memory } from "@/pages/Memory";
import { Integrations } from "@/pages/Integrations";
import { Rules } from "@/pages/Rules";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/inbox/:id" element={<DocumentDetail />} />
        <Route path="/catalog" element={<Catalog />} />
        <Route path="/memory" element={<Memory />} />
        <Route path="/rules" element={<Rules />} />
        <Route path="/integrations" element={<Integrations />} />
      </Route>
    </Routes>
  );
}
