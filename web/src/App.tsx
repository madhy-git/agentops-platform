// Routes: / (landing), the customer portal under /portal, the staff workspace under /staff. No sign-in screen.
//
// LEARNING NOTE: `Area` signs in as the area's default demo person on entry (lib/auth.tsx). It's UX only; the
// security boundary is the API (tests/integration/test_portal.py checks every staff endpoint refuses customers).
import { useEffect, useState, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { ErrorNote, Spinner } from "./components/ui";
import { useAuth, type Kind } from "./lib/auth";
import Landing from "./pages/Landing";
import Help from "./pages/portal/Help";
import NewRequest from "./pages/portal/NewRequest";
import PortalCase from "./pages/portal/PortalCase";
import PortalHome from "./pages/portal/PortalHome";
import PortalLayout from "./pages/portal/PortalLayout";
import Approvals from "./pages/staff/Approvals";
import Audit from "./pages/staff/Audit";
import CaseDetail from "./pages/staff/CaseDetail";
import Cases from "./pages/staff/Cases";
import Copilot from "./pages/staff/Copilot";
import Dashboard from "./pages/staff/Dashboard";
import StaffLayout from "./pages/staff/StaffLayout";

function Area({ kind, children }: { kind: Kind; children: ReactNode }) {
  const { session, ensure } = useAuth();
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    ensure(kind).catch(setError);
  }, [kind, ensure, session]);
  if (error != null)
    return (
      <div className="mx-auto max-w-lg p-10">
        <ErrorNote error={error} />
        <p className="mt-3 text-sm text-zinc-500">
          The API refused demo access. It needs AGENTOPS_DEV_LOGIN=1 and no identity provider configured.
        </p>
      </div>
    );
  if (session?.persona.kind !== kind) return <Spinner label="Opening" />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route
        path="/portal"
        element={
          <Area kind="customer">
            <PortalLayout />
          </Area>
        }
      >
        <Route index element={<PortalHome />} />
        <Route path="new" element={<NewRequest />} />
        <Route path="requests/:id" element={<PortalCase />} />
        <Route path="help" element={<Help />} />
      </Route>
      <Route
        path="/staff"
        element={
          <Area kind="staff">
            <StaffLayout />
          </Area>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="cases" element={<Cases />} />
        <Route path="cases/:id" element={<CaseDetail />} />
        <Route path="approvals" element={<Approvals />} />
        <Route path="copilot" element={<Copilot />} />
        <Route path="audit" element={<Audit />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
