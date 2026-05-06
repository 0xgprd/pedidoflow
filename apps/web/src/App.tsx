import { Route, Routes } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { Inbox } from "@/pages/Inbox";
import { Home } from "@/pages/Home";
import { Catalog } from "@/pages/Catalog";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/catalog" element={<Catalog />} />
      </Route>
    </Routes>
  );
}
