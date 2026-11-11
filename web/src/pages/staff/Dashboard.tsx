// Operations dashboard: approval workload against SLA, cases by state, and the newest cases.
import { AlarmClock, ClipboardCheck, FolderOpen, Gauge } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge, Card, ErrorNote, PageHeader, Spinner, stateTone } from "../../components/ui";
import type { StaffCase, Stats } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { humanize, timeAgo } from "../../lib/format";
import { useApi } from "../../lib/useApi";

const ORDER = ["new", "in_progress", "pending_approval", "escalated", "approved", "rejected", "actioned", "resolved", "closed", "reopened"];

function Kpi({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number | string; tone?: string }) {
  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 text-sm text-zinc-500">
        {icon}
        {label}
      </div>
      <div className={"mt-2 text-3xl font-semibold tracking-tight " + (tone ?? "")}>{value}</div>
    </Card>
  );
}

export default function Dashboard() {
  const { session } = useAuth();
  const { data: stats, error } = useApi<Stats>(`/stats?as=${session?.persona.username}`, 10_000);
  const { data: cases } = useApi<StaffCase[]>("/cases?limit=8", 10_000);
  const open = stats ? Object.entries(stats.cases_by_state).filter(([s]) => !["resolved", "closed"].includes(s)).reduce((n, [, v]) => n + v, 0) : 0;
  const total = stats ? Object.values(stats.cases_by_state).reduce((a, b) => a + b, 0) : 0;

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title={`Good day, ${session?.persona.display_name.split(" ")[0]}`} subtitle="Live view of the queue. Refreshes every 10 seconds." />
      {error != null && <ErrorNote error={error} />}
      {!stats && !error && <Spinner />}
      {stats && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi icon={<ClipboardCheck className="size-4" />} label="Waiting for you" value={stats.approvals.mine} />
          <Kpi icon={<Gauge className="size-4" />} label="Pending approvals" value={stats.approvals.pending} />
          <Kpi
            icon={<AlarmClock className="size-4" />}
            label="Past SLA"
            value={stats.approvals.overdue}
            tone={stats.approvals.overdue ? "text-red-600 dark:text-red-400" : ""}
          />
          <Kpi icon={<FolderOpen className="size-4" />} label="Open cases" value={open} />
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-1">
          <h2 className="font-semibold">Cases by state</h2>
          <div className="mt-4 space-y-3">
            {stats &&
              ORDER.filter((s) => stats.cases_by_state[s]).map((s) => {
                const n = stats.cases_by_state[s] ?? 0;
                return (
                  <Link key={s} to={`/staff/cases?state=${s}`} className="block">
                    <div className="flex justify-between text-sm">
                      <span>{humanize(s)}</span>
                      <span className="tabular-nums text-zinc-500">{n}</span>
                    </div>
                    <div className="mt-1 h-2 rounded-full bg-zinc-100 dark:bg-zinc-800">
                      <div className="h-2 rounded-full bg-brand-500" style={{ width: `${(n / Math.max(total, 1)) * 100}%` }} />
                    </div>
                  </Link>
                );
              })}
            {stats && total === 0 && <p className="text-sm text-zinc-500">No cases yet.</p>}
          </div>
        </Card>

        <Card className="lg:col-span-2">
          <div className="flex items-center justify-between p-5 pb-3">
            <h2 className="font-semibold">Latest cases</h2>
            <Link to="/staff/cases" className="text-sm text-brand-700 hover:underline dark:text-brand-300">
              View all
            </Link>
          </div>
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {cases?.map((c) => (
              <li key={c.id}>
                <Link to={`/staff/cases/${c.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                  <span className="w-14 font-mono text-xs text-zinc-400">#{c.id}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{c.summary}</span>
                    <span className="text-xs text-zinc-500">
                      {c.customer_name ?? "No customer"} · {humanize(c.queue)} · {timeAgo(c.created_at)}
                    </span>
                  </span>
                  <Badge tone={stateTone(c.state)}>{humanize(c.state)}</Badge>
                </Link>
              </li>
            ))}
            {cases?.length === 0 && <li className="px-5 py-8 text-center text-sm text-zinc-500">Nothing here yet. Raise one from the customer portal.</li>}
          </ul>
        </Card>
      </div>
    </div>
  );
}
