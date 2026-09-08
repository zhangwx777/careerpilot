import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { ApplicationFormPage } from "./pages/ApplicationFormPage";
import { ApplicationsPage } from "./pages/ApplicationsPage";
import { CompaniesPage } from "./pages/CompaniesPage";
import { PositionsPage } from "./pages/PositionsPage";
import { SmartEntryPage } from "./pages/SmartEntryPage";
import { TimelinePage } from "./pages/TimelinePage";
import { IntelPage } from "./pages/IntelPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/applications" replace />} />
        <Route path="/applications" element={<ApplicationsPage />} />
        <Route path="/applications/new" element={<ApplicationFormPage />} />
        <Route path="/applications/:id/edit" element={<ApplicationFormPage />} />
        <Route path="/smart-entry" element={<SmartEntryPage />} />
        <Route path="/smart-entry/:id" element={<SmartEntryPage />} />
        <Route path="/timeline" element={<TimelinePage />} />
        <Route path="/intel" element={<IntelPage />} />
        <Route path="/intel/:id" element={<IntelPage />} />
        <Route path="/companies" element={<CompaniesPage />} />
        <Route path="/positions" element={<PositionsPage />} />
        <Route path="*" element={<Navigate to="/applications" replace />} />
      </Route>
    </Routes>
  );
}
