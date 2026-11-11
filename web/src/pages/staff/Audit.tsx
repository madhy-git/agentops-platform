// Audit trail (managers and compliance): the append-only record of every step, filterable by case. Rows can't
// be edited or deleted, not even by the app (a database trigger refuses), which is what makes it evidence.
import { ChevronDown, ChevronRight, ScrollText, Search } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Badge, Card, EmptyState, ErrorNote, PageHeader, Spinner, type Tone } from "../../components/ui";
import type { AuditEvent } from "../../lib/api";
import { dateTime, humanize } from "../../lib/format";
import { useApi } from "../../lib/useApi";

function tone(event: string): Tone {
  if (/blocked|denied|failed/.test(event)) return "red";
  if (/approval/.test(event)) return "amber";
  if (/executed|decided|flag/.test(event)) return "violet";
  if (/case_/.test(event)) return "blue";
  return "neutral";
}

export default function Audit() {
  const [params, setParams] = useSearchParams();
  const caseId = params.get("case_id") ?? "";
  const [draft, setDraft] = useState(caseId);
  const [open, setOpen] = useState<number | null>(null);
  const { data, error, loading } = useApi<AuditEvent[]>(`/audit${caseId ? `?case_id=${encodeURIComponent(caseId)}` : ""}`);
  const rows = data ? [...data].reverse() : null; // newest first

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Audit trail"
        subtitle="Append-only. Every event carries a trace id that links to its OpenTelemetry trace."
        actions={
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setParams(draft ? { case_id: draft } : {});
            }}
            className="flex items-center gap-2 rounded-xl bg-white px-3 py-1.5 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-zinc-700"
          >
            <Search className="size-4 text-zinc-400" />
            <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Filter by case id" className="w-36 bg-transparent text-sm outline-none" />
          </form>
        }
      />
      {loading && <Spinner />}
      {error != null && <ErrorNote error={error} />}
      {rows?.length === 0 && (
        <Card>
          <EmptyState icon={<ScrollText className="size-6" />} title="No events" />
        </Card>
      )}
      {rows && rows.length > 0 && (
        <Card className="overflow-hidden">
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {rows.map((e) => (
              <li key={e.id}>
                <button onClick={() => setOpen(open === e.id ? null : e.id)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                  {open === e.id ? <ChevronDown className="size-4 text-zinc-400" /> : <ChevronRight className="size-4 text-zinc-400" />}
                  <span className="w-32 shrink-0 text-xs text-zinc-500 tabular-nums">{dateTime(e.ts)}</span>
                  <Badge tone={tone(e.event)}>{humanize(e.event)}</Badge>
                  <span className="truncate text-zinc-600 dark:text-zinc-300">{e.actor}</span>
                  {e.reason_code && <span className="truncate font-mono text-xs text-zinc-500">{e.reason_code}</span>}
                  <span className="ml-auto shrink-0">
                    {e.case_id && (
                      <Link to={`/staff/cases/${e.case_id}`} onClick={(ev) => ev.stopPropagation()} className="font-mono text-xs text-brand-700 hover:underline dark:text-brand-300">
                        #{e.case_id}
                      </Link>
                    )}
                  </span>
                </button>
                {open === e.id && (
                  <div className="bg-zinc-50 px-11 py-3 text-xs dark:bg-zinc-950">
                    <div className="grid gap-1 text-zinc-500 sm:grid-cols-3">
                      <span>policy: {e.policy_version ?? "n/a"}</span>
                      <span>prompt: {e.prompt_version ?? "n/a"}</span>
                      <span className="truncate">trace: {e.trace_id ?? "n/a"}</span>
                    </div>
                    <pre className="mt-2 overflow-x-auto rounded-lg bg-white p-3 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-zinc-800">{JSON.stringify(e.data, null, 2)}</pre>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
