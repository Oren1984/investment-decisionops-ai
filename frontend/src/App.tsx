import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { isDemo } from "./api/client";
import type { AuthStatus } from "./api/types";
import { AppShell } from "./components/layout/AppShell";
import { ErrorState, Loading } from "./components/ui";
import { useApi } from "./hooks/useApi";
import { AcceptInvitePage, LoginPage, SetupPage } from "./pages/Auth";

const Overview = lazy(() => import("./pages/Overview"));
const Markets = lazy(() => import("./pages/Markets"));
const PortfolioPage = lazy(() => import("./pages/Portfolio"));
const Decisions = lazy(() => import("./pages/Decisions"));
const DecisionNew = lazy(() => import("./pages/DecisionNew"));
const DecisionDetail = lazy(() => import("./pages/DecisionDetail"));
const AgentWorkspace = lazy(() => import("./pages/AgentWorkspace"));
const Orders = lazy(() => import("./pages/Orders"));
const OrderDetail = lazy(() => import("./pages/OrderDetail"));
const Collaboration = lazy(() => import("./pages/Collaboration"));
const MeetingCompanion = lazy(() => import("./pages/MeetingCompanion"));
const Library = lazy(() => import("./pages/Library"));
const Settings = lazy(() => import("./pages/Settings"));
const Help = lazy(() => import("./pages/Help"));
const Shared = lazy(() => import("./pages/Shared"));

export function useAuth() {
  return useApi<AuthStatus>(["auth"], "/auth/status", { staleTime: 60_000 });
}

export default function App() {
  const auth = useAuth();
  if (auth.isLoading) return <Loading label="Starting…" />;
  if (auth.error) {
    return (
      <main className="mx-auto max-w-lg p-6">
        <h1 className="mb-3 text-lg font-semibold">DecisionOps is starting or unavailable</h1>
        <ErrorState error={auth.error} retry={() => auth.refetch()} />
        <p className="mt-3 text-sm text-muted">On first start the database migrations and synthetic seed take a minute. Check <code>docker compose ps</code>.</p>
      </main>
    );
  }
  const status = auth.data!;
  const role = isDemo ? "demo" : status.user?.role;

  if (!isDemo && status.setup_required) {
    return (
      <Routes>
        <Route path="*" element={<SetupPage />} />
      </Routes>
    );
  }
  if (!status.authenticated) {
    return (
      <Routes>
        <Route path="/invite/:token" element={<AcceptInvitePage />} />
        <Route path="/help/*" element={<Suspense fallback={<Loading />}><main className="mx-auto max-w-4xl p-4"><Help /></main></Suspense>} />
        <Route path="*" element={<LoginPage />} />
      </Routes>
    );
  }

  return (
    <AppShell role={role ?? "owner"} user={status.user}>
      <Suspense fallback={<Loading />}>
        {role === "collaborator" ? (
          <Routes>
            <Route path="/" element={<Navigate to="/shared" replace />} />
            <Route path="/shared/*" element={<Shared />} />
            <Route path="/meetings/:id" element={<MeetingCompanion />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/help" element={<Help />} />
            <Route path="/help/:slug" element={<Help />} />
            <Route path="*" element={<Navigate to="/shared" replace />} />
          </Routes>
        ) : (
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/markets" element={<Markets />} />
            <Route path="/portfolio" element={<PortfolioPage />} />
            <Route path="/decisions" element={<Decisions />} />
            <Route path="/decisions/new" element={<DecisionNew />} />
            <Route path="/decisions/:id" element={<DecisionDetail />} />
            <Route path="/decisions/:id/runs/:runId" element={<AgentWorkspace />} />
            <Route path="/orders" element={<Orders />} />
            <Route path="/orders/:id" element={<OrderDetail />} />
            <Route path="/collaboration" element={<Collaboration />} />
            <Route path="/meetings/:id" element={<MeetingCompanion />} />
            <Route path="/library" element={<Library />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/help" element={<Help />} />
            <Route path="/help/:slug" element={<Help />} />
            <Route path="/shared/*" element={<Shared />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        )}
      </Suspense>
    </AppShell>
  );
}

function NotFound() {
  return (
    <div className="py-10">
      <h1 className="text-lg font-semibold">Page not found</h1>
      <p className="mt-1 text-sm text-muted">Use the navigation to continue.</p>
    </div>
  );
}
