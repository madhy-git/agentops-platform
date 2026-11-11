// Customer home: greeting, quick actions, and every request with its live status (polled every 10 s, so an
// approval made by a specialist shows up without refreshing).
import { ChevronRight, Inbox } from "lucide-react";
import { Link } from "react-router-dom";
import { Progress } from "../../components/Progress";
import { Badge, Card, EmptyState, ErrorNote, Spinner, stateTone } from "../../components/ui";
import type { PortalCase } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { timeAgo } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { TOPICS } from "./topics";

export default function PortalHome() {
  const { session } = useAuth();
  const { data, error, loading } = useApi<PortalCase[]>("/portal/cases", 10_000);
  const first = session?.persona.display_name.split(" ")[0];
  const open = data?.filter((c) => c.step < 3).length ?? 0;

  return (
    <div className="space-y-10">
      <section className="overflow-hidden rounded-3xl bg-gradient-to-br from-brand-700 to-brand-900 p-8 text-white shadow-lg">
        <p className="text-sm text-brand-200">Welcome back</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Hi {first}, how can we help today?</h1>
        <p className="mt-2 text-brand-100">
          {open > 0 ? `You have ${open} open request${open > 1 ? "s" : ""}. We'll keep you updated here.` : "Raise a request any time; most are picked up within the hour."}
        </p>
        <div className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-5">
          {TOPICS.map((t) => (
            <Link
              key={t.id}
              to={`/portal/new?topic=${t.id}`}
              className="flex flex-col gap-2 rounded-2xl bg-white/10 p-3 text-sm ring-1 ring-white/15 transition hover:bg-white/20"
            >
              <t.icon className="size-5 text-wattle-300" />
              <span className="font-medium leading-tight">{t.title}</span>
            </Link>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">My requests</h2>
        {loading && <Spinner />}
        {error != null && <ErrorNote error={error} />}
        {data && data.length === 0 && (
          <Card>
            <EmptyState icon={<Inbox className="size-6" />} title="No requests yet">
              When you raise a request, you can follow every step here.
            </EmptyState>
          </Card>
        )}
        <div className="grid gap-3">
          {data?.map((c) => (
            <Link key={c.id} to={`/portal/requests/${c.id}`}>
              <Card className="p-5 transition hover:shadow-md hover:ring-brand-200 dark:hover:ring-brand-800">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{c.topic}</span>
                      <Badge tone={stateTone(c.status)}>{c.status}</Badge>
                    </div>
                    <p className="mt-1 truncate text-sm text-zinc-500">{c.message}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2 text-xs text-zinc-400">
                    <span>{c.reference}</span>
                    <span>· {timeAgo(c.updated_at)}</span>
                    <ChevronRight className="size-4" />
                  </div>
                </div>
                <div className="mt-4">
                  <Progress step={c.step} compact />
                </div>
              </Card>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
