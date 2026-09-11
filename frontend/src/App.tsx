import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { ApplicationFormPage } from "./pages/ApplicationFormPage";
import { ApplicationsPage } from "./pages/ApplicationsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { SmartEntryPage } from "./pages/SmartEntryPage";
import { TimelinePage } from "./pages/TimelinePage";
import { IntelPage } from "./pages/IntelPage";
import { PlannerPage } from "./pages/PlannerPage";
import { BriefingPage } from "./pages/BriefingPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/applications" element={<ApplicationsPage />} />
        <Route path="/applications/new" element={<ApplicationFormPage />} />
        <Route path="/applications/:id/edit" element={<ApplicationFormPage />} />
        <Route path="/smart-entry" element={<SmartEntryPage />} />
        <Route path="/smart-entry/:id" element={<SmartEntryPage />} />
        <Route path="/timeline" element={<TimelinePage />} />
        <Route path="/intel" element={<IntelPage />} />
        <Route path="/intel/:id" element={<IntelPage />} />
        <Route path="/planner" element={<PlannerPage />} />
        <Route path="/planner/:id" element={<PlannerPage />} />
        <Route path="/daily-briefings" element={<BriefingPage />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}
