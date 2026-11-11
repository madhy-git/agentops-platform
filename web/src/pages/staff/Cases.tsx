// Case queue with state filters, plus "Triage a message" for officers taking a call or an email.
import { AlertOctagon, Plus, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Badge, Button, Card, cx, ErrorNote, PageHeader, Spinner, stateTone } from "../../components/ui";
import { post, type StaffCase } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { humanize, slaLabel, timeAgo } from "../../lib/format";
import { useApi } from "../../lib/useApi";

const FILTERS = [
  { id: "", label: "All" },
  { id: "pending_approval", label: "Pending approval" },
  { id: "in_progress", label: "In progress" },
  { id: "escalated", label: "Escalated" },
  { id: "actioned", label: "Actioned" },
  { id: "resolved", label: "Resolved" },
];

function TriageForm({ onClose }: { onClose: () => void }) {
  const [message, setMessage] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const navigate = useNavigate();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ case_id: number | null; status: string; reason: string | null }>("/triage", {
        message,
        customer_id: customerId || null,
      });
      if (r.case_id) navigate(`/staff/cases/${r.case_id}`);
      else setError(`Blocked: ${r.reason ?? r.status}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-6 p-5">
      <form onSubmit={submit} className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Triage a customer message</h2>
          <button type="button" onClick={onClose} className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={3}
          required
          placeholder="Paste or type the customer's message"
          className="w-full rounded-xl bg-zinc-50 p-3 text-sm ring-1 ring-zinc-200 outline-none focus:ring-2 focus:ring-brand-500 dark:bg-zinc-950 dark:ring-zinc-800"
        />
        <div className="flex flex-wrap items-center gap-3">
          <input
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            placeholder="Customer id (optional), e.g. CUS-00002"
            className="w-72 rounded-xl bg-zinc-50 px-3 py-2 text-sm ring-1 ring-zinc-200 outline-none focus:ring-2 focus:ring-brand-500 dark:bg-zinc-950 dark:ring-zinc-800"
          />
          <Button type="submit" loading={busy}>
            Run triage
          </Button>
        </div>
        {error != null && <ErrorNote error={error} />}
      </form>
    </Card>
  );
}

export default function Cases() {
  const [params, setParams] = useSearchParams();
  const state = params.get("state") ?? "";
  const [showTriage, setShowTriage] = useState(false);
  const { hasRole } = useAuth();
  const { data, error, loading } = useApi<StaffCase[]>(`/cases${state ? `?state=${state}` : ""}`, 10_000);
  const canTriage = !hasRole("compliance");

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Cases"
        subtitle="Every customer request, from the portal or triaged by staff."
        actions={
          canTriage && !showTriage && (
            <Button onClick={() => setShowTriage(true)}>
              <Plus className="size-4" /> Triage a message
            </Button>
          )
        }
      />
      {showTriage && <TriageForm onClose={() => setShowTriage(false)} />}

      <div className="mb-4 flex gap-1 overflow-x-auto">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            onClick={() => setParams(f.id ? { state: f.id } : {})}
            className={cx(
              "rounded-full px-3 py-1.5 text-sm font-medium whitespace-nowrap",
              state === f.id ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900" : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading && <Spinner />}
      {error != null && <ErrorNote error={error} />}
      {data && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500 dark:bg-zinc-950">
                <tr>
                  <th className="px-4 py-3 font-medium">Case</th>
                  <th className="px-4 py-3 font-medium">Customer</th>
                  <th className="px-4 py-3 font-medium">Message</th>
                  <th className="px-4 py-3 font-medium">Queue</th>
                  <th className="px-4 py-3 font-medium">State</th>
                  <th className="px-4 py-3 font-medium">Approval</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {data.map((c) => {
                  const sla = c.approval_status === "pending" && c.sla_due ? slaLabel(c.sla_due) : null;
                  return (
                    <tr key={c.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                      <td className="px-4 py-3">
                        <Link to={`/staff/cases/${c.id}`} className="font-mono text-brand-700 hover:underline dark:text-brand-300">
                          #{c.id}
                        </Link>
                        <div className="text-xs text-zinc-400">{timeAgo(c.created_at)}</div>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">{c.customer_name ?? <span className="text-zinc-400">n/a</span>}</td>
                      <td className="max-w-xs px-4 py-3">
                        <Link to={`/staff/cases/${c.id}`} className="line-clamp-2">
                          {c.summary}
                        </Link>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {humanize(c.queue)}
                        {c.priority === "urgent" && <AlertOctagon className="ml-1 inline size-3.5 text-red-500" aria-label="urgent" />}
                      </td>
                      <td className="px-4 py-3">
                        <Badge tone={stateTone(c.state)}>{humanize(c.state)}</Badge>
                      </td>
                      <td className="px-4 py-3 text-xs whitespace-nowrap">
                        {c.approval_status ? (
                          <div>
                            <span className="font-medium">{humanize(c.approval_status)}</span>
                            {c.approver && <span className="text-zinc-500"> · {c.approver}</span>}
                            {sla && <div className={sla.overdue ? "text-red-600" : "text-zinc-500"}>{sla.text}</div>}
                          </div>
                        ) : (
                          <span className="text-zinc-400">none</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {data.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-zinc-500">
                      No cases in this state.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
