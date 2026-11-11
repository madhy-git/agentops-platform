// One request, as the customer sees it: plain status, progress, and a timeline built from the audit trail.
import { ArrowLeft, Circle, CircleCheck } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { Progress } from "../../components/Progress";
import { Badge, Card, ErrorNote, Spinner, stateTone } from "../../components/ui";
import type { PortalCase as Case } from "../../lib/api";
import { dateTime } from "../../lib/format";
import { useApi } from "../../lib/useApi";

export default function PortalCase() {
  const { id } = useParams();
  const { data: c, error, loading } = useApi<Case>(`/portal/cases/${id}`, 10_000);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link to="/portal" className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">
        <ArrowLeft className="size-4" /> My requests
      </Link>
      {loading && <Spinner />}
      {error != null && <ErrorNote error={error} />}
      {c && (
        <>
          <Card className="p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-mono text-xs text-zinc-500">{c.reference}</p>
                <h1 className="mt-1 text-2xl font-semibold tracking-tight">{c.topic}</h1>
              </div>
              <Badge tone={stateTone(c.status)} className="text-sm">
                {c.status}
              </Badge>
            </div>
            <p className="mt-3 text-zinc-600 dark:text-zinc-300">{c.status_detail}</p>
            {c.expected_by && <p className="mt-1 text-sm text-zinc-500">We aim to respond by {dateTime(c.expected_by)}.</p>}
            <div className="mt-6">
              <Progress step={c.step} />
            </div>
          </Card>

          <Card className="p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">What you told us</h2>
            <p className="mt-2 rounded-xl bg-zinc-50 p-3 text-sm dark:bg-zinc-950">{c.message}</p>
          </Card>

          <Card className="p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Timeline</h2>
            <ol className="mt-4 space-y-0">
              {c.timeline?.map((t, i, all) => {
                const last = i === all.length - 1;
                return (
                  <li key={i} className="relative flex gap-3 pb-6 last:pb-0">
                    {!last && <span className="absolute top-6 left-[11px] h-full w-px bg-zinc-200 dark:bg-zinc-800" />}
                    {last ? <Circle className="size-6 shrink-0 fill-brand-100 text-brand-500 dark:fill-brand-950" /> : <CircleCheck className="size-6 shrink-0 text-brand-500" />}
                    <div>
                      <p className="font-medium">{t.status}</p>
                      <p className="text-sm text-zinc-500">{t.detail}</p>
                      <p className="mt-0.5 text-xs text-zinc-400">{dateTime(t.at)}</p>
                    </div>
                  </li>
                );
              })}
            </ol>
          </Card>
        </>
      )}
    </div>
  );
}
