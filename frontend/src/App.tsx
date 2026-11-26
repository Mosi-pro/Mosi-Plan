import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { CreateProvider } from "./components/dialogs";
import { AppLayout } from "./components/layout";
import { ToastProvider } from "./components/toast";
import { Spinner, TooltipProvider } from "./components/ui";
import { VoiceProvider } from "./components/voice";
import { AuthProvider, useAuth } from "./hooks/auth";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";

const Assistant = lazy(() => import("./pages/Assistant"));
const CalendarPage = lazy(() => import("./pages/Calendar"));
const Tasks = lazy(() => import("./pages/Tasks"));
const Projects = lazy(() => import("./pages/Projects"));
const ProjectDetail = lazy(() => import("./pages/ProjectDetail"));
const WeeklyPlan = lazy(() => import("./pages/WeeklyPlan"));
const Memory = lazy(() => import("./pages/Memory"));
const Settings = lazy(() => import("./pages/settings/Settings"));

function Shell() {
  const { user, loading } = useAuth();
  if (loading) return <div className="h-full grid place-items-center"><Spinner className="h-5 w-5" /></div>;
  if (!user) return <Login />;
  return (
    <CreateProvider>
      <VoiceProvider>
        <AppLayout>
          <Suspense fallback={<div className="py-20 grid place-items-center"><Spinner /></div>}>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/assistent" element={<Assistant />} />
              <Route path="/kalender" element={<CalendarPage />} />
              <Route path="/aufgaben" element={<Tasks />} />
              <Route path="/projekte" element={<Projects />} />
              <Route path="/projekte/:id" element={<ProjectDetail />} />
              <Route path="/wochenplan" element={<WeeklyPlan />} />
              <Route path="/gedaechtnis" element={<Memory />} />
              <Route path="/einstellungen" element={<Navigate to="/einstellungen/profil" replace />} />
              <Route path="/einstellungen/:section" element={<Settings />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </AppLayout>
      </VoiceProvider>
    </CreateProvider>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <TooltipProvider>
        <AuthProvider>
          <Shell />
        </AuthProvider>
      </TooltipProvider>
    </ToastProvider>
  );
}
