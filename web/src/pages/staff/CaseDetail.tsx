// One case, staff view: what the customer said, what the RULES decided (reason codes, actions, flags), the
// approval trail, the customer's protective flags, and the state moves this person may make.
//
// LEARNING NOTE: the transition buttons come from the API's `allowed_transitions` (the state machine in
// workflow/cases.py), so the UI can't offer a move the server would reject. Manager-only moves still return 403
// for others; the UI shows that message instead of hiding it, so the rule is visible.
import { ArrowLeft, Flag, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Button, Card, ErrorNote, Spinner, stateTone } from "../../components/ui";
import { AiTrail, AiTrailCard } from "../../components/AiTrail";
import { post, type AiTrail as Trail, type CaseDetail as Detail } from "../../lib/api";
import { dateTime, humanize } from "../../lib/format";
import { useApi } from "../../lib/useApi";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-4 py-2 text-sm">
      <dt className="w-36 shrink-0 text-zinc-500">{label}</dt>
      <dd className="min-w-0 flex-1">{children}</dd>
    </div>
  );
}

export default function CaseDetail() {
  const { id } = useParams();
  const { data: c, error, loading, reload } = useApi<Detail>(`/cases/${id}`, 10_000);
  const trail = useApi<Trail>(`/cases/${id}/ai-trail`, 15_000);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);

  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setActionError(null);
    try {
      await fn();
      reload();
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <Link to="/staff/cases" className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">
        <ArrowLeft className="size-4" /> Cases
      </Link>
      {loading && <Spinner />}
      {error != null && <ErrorNote error={error} />}
      {c && (
        <>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="font-mono text-sm text-zinc-500">Case #{c.id}</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight">{humanize(c.queue)}</h1>
              <p className="mt-1 text-sm text-zinc-500">
                Opened {dateTime(c.created_at)} by {c.created_by} · priority {c.priority}
              </p>
            </div>
            <Badge tone={stateTone(c.state)} className="text-sm">
              {humanize(c.state)}
            </Badge>
          </div>
          {actionError != null && <ErrorNote error={actionError} />}

          <div className="grid gap-6 lg:grid-cols-3">
            <div className="space-y-6 lg:col-span-2">
              <Card className="p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Customer message (redacted)</h2>
                <p className="mt-2 rounded-xl bg-zinc-50 p-3 text-sm dark:bg-zinc-950">{c.summary}</p>
              </Card>

              {c.decision && (
                <Card className="p-5">
                  <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-zinc-500">
                    <ShieldCheck className="size-4" /> Rules decision · policy {c.decision.policy_version}
                  </h2>
                  <dl className="mt-2 divide-y divide-zinc-100 dark:divide-zinc-800">
                    <Row label="Reason codes">
                      <div className="flex flex-wrap gap-1">
                        {c.decision.reason_codes.map((r) => (
                          <Badge key={r} tone="violet">
                            {r}
                          </Badge>
                        ))}
                      </div>
                    </Row>
                    <Row label="Actions">{c.decision.actions.map(humanize).join(", ") || "none"}</Row>
                    <Row label="Needs approval">{c.decision.needs_approval ? "Yes: a specialist must approve" : "No"}</Row>
                    {c.decision.flags_set.length > 0 && <Row label="Flags set">{c.decision.flags_set.map(humanize).join(", ")}</Row>}
                    {c.decision.suppressed_actions.length > 0 && (
                      <Row label="Suppressed">{c.decision.suppressed_actions.map(humanize).join(", ")}</Row>
                    )}
                    {c.decision.candidate_actions.length > 0 && (
                      <Row label="Next best actions">{c.decision.candidate_actions.map(humanize).join(", ")}</Row>
                    )}
                  </dl>
                </Card>
              )}

              <AiTrailCard>
                <AiTrail data={trail.data} error={trail.error} loading={trail.loading} />
              </AiTrailCard>

              <Card className="p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Approvals</h2>
                {c.approvals.length === 0 && <p className="mt-2 text-sm text-zinc-500">No approval needed.</p>}
                <ul className="mt-2 space-y-3">
                  {c.approvals.map((a) => (
                    <li key={a.id} className="rounded-xl bg-zinc-50 p-3 text-sm dark:bg-zinc-950">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium">{humanize(a.action)}</span>
                        <Badge tone={stateTone(a.status)}>{humanize(a.status)}</Badge>
                      </div>
                      <p className="mt-1 text-zinc-500">
                        Requested by {a.requested_by} · assigned to {a.assigned_to} · SLA {dateTime(a.sla_due)}
                        {a.escalated_at && " · escalated"}
                      </p>
                      {a.decided_by && (
                        <p className="mt-1 text-zinc-500">
                          {humanize(a.status)} by {a.decided_by} at {dateTime(a.decided_at!)}
                          {a.reason && `: "${a.reason}"`}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              </Card>
            </div>

            <div className="space-y-6">
              {c.customer && (
                <Card className="p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Customer</h2>
                  <p className="mt-2 font-medium">{c.customer.name}</p>
                  <p className="text-sm text-zinc-500">
                    {c.customer.customer_id} · {humanize(c.customer.lifecycle_stage)}
                  </p>
                  {c.customer.vulnerable && <Badge tone="amber" className="mt-2">Vulnerable customer</Badge>}
                  <h3 className="mt-4 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">
                    <Flag className="size-3.5" /> Protective flags
                  </h3>
                  {c.customer.active_flags.length === 0 && <p className="mt-1 text-sm text-zinc-500">None active.</p>}
                  <ul className="mt-2 space-y-2">
                    {c.customer.active_flags.map((f) => (
                      <li key={f} className="flex items-center justify-between gap-2">
                        <Badge tone="red">{humanize(f)}</Badge>
                        <Button
                          variant="ghost"
                          className="px-2 py-1 text-xs"
                          loading={busy === `flag-${f}`}
                          onClick={() => act(`flag-${f}`, () => post(`/customers/${c.customer!.customer_id}/flags/${f}/clear`))}
                        >
                          Clear
                        </Button>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-3 text-xs text-zinc-400">Only the matching specialist can clear a flag; others get a 403.</p>
                </Card>
              )}

              <Card className="p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Move case</h2>
                <div className="mt-3 flex flex-wrap gap-2">
                  {c.allowed_transitions.map((t) => (
                    <Button key={t} variant="secondary" loading={busy === t} onClick={() => act(t, () => post(`/cases/${c.id}/transition`, { to: t }))}>
                      {humanize(t)}
                    </Button>
                  ))}
                </div>
                <p className="mt-3 text-xs text-zinc-400">
                  Approve and reject happen in "My approvals", so the separation-of-duties checks always run.
                </p>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
