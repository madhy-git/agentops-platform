// My approvals: the regulated actions waiting for THIS person (domain routing + least-loaded assignment), each
// with the customer's message and an SLA countdown. Approve runs the action exactly once; reject sends the case
// back to the team. Neither can be done by the person who requested it (separation of duties, checked in code
// and by a database constraint).
import { AlarmClock, CheckCircle2, ClipboardCheck, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, EmptyState, ErrorNote, PageHeader, Spinner } from "../../components/ui";
import { post, type Approval } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { humanize, slaLabel, timeAgo } from "../../lib/format";
import { useApi } from "../../lib/useApi";

function ApprovalCard({ a, onDone }: { a: Approval; onDone: (msg: string) => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const sla = slaLabel(a.sla_due);

  async function decide(approve: boolean) {
    setBusy(approve ? "approve" : "reject");
    setError(null);
    try {
      const r = await post<{ effect: string | null }>(`/approvals/${a.id}/decision`, { approve, reason });
      onDone(approve ? `Approved #${a.case_id}${r.effect ? `: ${r.effect}` : ""}` : `Rejected #${a.case_id}; case sent back to the team`);
    } catch (e) {
      setError(e);
      setBusy(null);
    }
  }

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-semibold">{humanize(a.action)}</span>
            <Badge tone="violet">{humanize(a.domain)}</Badge>
            {a.priority === "urgent" && <Badge tone="red">Urgent</Badge>}
            {a.escalated_at && <Badge tone="amber">Escalated to you</Badge>}
          </div>
          <p className="mt-1 text-sm text-zinc-500">
            <Link to={`/staff/cases/${a.case_id}`} className="font-mono text-brand-700 hover:underline dark:text-brand-300">
              Case #{a.case_id}
            </Link>{" "}
            · {a.customer_name ?? "no customer"} · requested by {a.requested_by} {timeAgo(a.created_at)}
          </p>
        </div>
        <span className={"flex items-center gap-1.5 text-sm font-medium " + (sla.overdue ? "text-red-600 dark:text-red-400" : "text-zinc-600 dark:text-zinc-300")}>
          <AlarmClock className="size-4" /> {sla.text}
        </span>
      </div>
      {a.summary && <p className="mt-3 rounded-xl bg-zinc-50 p-3 text-sm dark:bg-zinc-950">{a.summary}</p>}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason (recorded in the audit trail)"
          className="min-w-56 flex-1 rounded-xl bg-zinc-50 px-3 py-2 text-sm ring-1 ring-zinc-200 outline-none focus:ring-2 focus:ring-brand-500 dark:bg-zinc-950 dark:ring-zinc-800"
        />
        <Button variant="danger" loading={busy === "reject"} disabled={!!busy} onClick={() => void decide(false)}>
          <XCircle className="size-4" /> Reject
        </Button>
        <Button loading={busy === "approve"} disabled={!!busy} onClick={() => void decide(true)}>
          <CheckCircle2 className="size-4" /> Approve
        </Button>
      </div>
      {error != null && <div className="mt-3"><ErrorNote error={error} /></div>}
    </Card>
  );
}

export default function Approvals() {
  const { session } = useAuth();
  const { data, error, loading, reload } = useApi<Approval[]>(`/approvals/mine?as=${session?.persona.username}`, 10_000);
  const [toast, setToast] = useState<string | null>(null);

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        title="My approvals"
        subtitle="Routed to you by domain. Nothing is ever auto-approved: past the SLA it escalates to a manager instead."
      />
      {toast && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-brand-50 p-3 text-sm text-brand-800 ring-1 ring-brand-200 dark:bg-brand-950 dark:text-brand-200 dark:ring-brand-800">
          <CheckCircle2 className="size-4" /> {toast}
        </div>
      )}
      {loading && <Spinner />}
      {error != null && <ErrorNote error={error} />}
      {data?.length === 0 && (
        <Card>
          <EmptyState icon={<ClipboardCheck className="size-6" />} title="You're all caught up">
            Nothing is waiting for {session?.persona.display_name}. Try "Viewing as" a fraud specialist after raising a
            stolen-card request in the customer portal.
          </EmptyState>
        </Card>
      )}
      <div className="space-y-4">
        {data?.map((a) => (
          <ApprovalCard
            key={a.id}
            a={a}
            onDone={(msg) => {
              setToast(msg);
              reload();
            }}
          />
        ))}
      </div>
    </div>
  );
}
