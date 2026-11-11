// Raise a request. The message goes through the full pipeline: PII redaction, injection guard, triage, rules,
// a case, and (for regulated actions like blocking a card) a specialist's approval.
import { CheckCircle2, Lock } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Progress } from "../../components/Progress";
import { Badge, Button, Card, cx, ErrorNote, PageHeader, stateTone } from "../../components/ui";
import { post, type PortalCase } from "../../lib/api";
import { dateTime } from "../../lib/format";
import { TOPICS } from "./topics";

export default function NewRequest() {
  const [params] = useSearchParams();
  const initial = TOPICS.find((t) => t.id === params.get("topic"));
  const [topic, setTopic] = useState(initial?.id ?? "");
  const [message, setMessage] = useState(initial?.template ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState<PortalCase | null>(null);

  function choose(id: string) {
    setTopic(id);
    const t = TOPICS.find((x) => x.id === id);
    if (t && (!message || TOPICS.some((x) => x.template === message))) setMessage(t.template);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setCreated(await post<PortalCase>("/portal/requests", { message }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <Card className="mx-auto max-w-xl p-8 text-center">
        <CheckCircle2 className="mx-auto size-12 text-brand-500" />
        <h1 className="mt-4 text-2xl font-semibold">Request received</h1>
        <p className="mt-1 text-zinc-500">
          Your reference is <span className="font-mono font-medium text-zinc-800 dark:text-zinc-200">{created.reference}</span>
        </p>
        <div className="mt-6 rounded-2xl bg-zinc-50 p-4 text-left dark:bg-zinc-950">
          <div className="flex items-center justify-between">
            <span className="font-medium">{created.topic}</span>
            <Badge tone={stateTone(created.status)}>{created.status}</Badge>
          </div>
          <p className="mt-1 text-sm text-zinc-500">{created.status_detail}</p>
          {created.expected_by && (
            <p className="mt-1 text-sm text-zinc-500">We aim to respond by {dateTime(created.expected_by)}.</p>
          )}
          <div className="mt-4">
            <Progress step={created.step} />
          </div>
        </div>
        <div className="mt-6 flex justify-center gap-2">
          <Link to={`/portal/requests/${created.id}`}>
            <Button>Track this request</Button>
          </Link>
          <Link to="/portal">
            <Button variant="secondary">Back to my requests</Button>
          </Link>
        </div>
      </Card>
    );
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="New request" subtitle="Tell us what's happening. A specialist reviews anything that affects your account." />
      <form onSubmit={submit} className="space-y-6">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {TOPICS.map((t) => (
            <button
              type="button"
              key={t.id}
              onClick={() => choose(t.id)}
              className={cx(
                "flex items-start gap-3 rounded-2xl p-4 text-left ring-1 transition",
                topic === t.id
                  ? "bg-brand-50 ring-2 ring-brand-500 dark:bg-brand-950"
                  : "bg-white ring-zinc-200 hover:ring-brand-300 dark:bg-zinc-900 dark:ring-zinc-800",
              )}
            >
              <t.icon className={cx("mt-0.5 size-5 shrink-0", topic === t.id ? "text-brand-600" : "text-zinc-400")} />
              <span>
                <span className="block text-sm font-medium">{t.title}</span>
                <span className="block text-xs text-zinc-500">{t.text}</span>
              </span>
            </button>
          ))}
        </div>
        <Card className="p-5">
          <label htmlFor="msg" className="text-sm font-medium">
            Your message
          </label>
          <textarea
            id="msg"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            rows={5}
            maxLength={2000}
            required
            minLength={3}
            placeholder="Describe what happened, in your own words."
            className="mt-2 w-full resize-y rounded-xl bg-zinc-50 p-3 text-sm ring-1 ring-zinc-200 outline-none focus:ring-2 focus:ring-brand-500 dark:bg-zinc-950 dark:ring-zinc-800"
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <p className="flex items-center gap-1.5 text-xs text-zinc-500">
              <Lock className="size-3.5" /> Phone numbers, emails and card numbers are masked before anyone sees them.
            </p>
            <Button type="submit" loading={busy} disabled={message.trim().length < 3}>
              Submit request
            </Button>
          </div>
        </Card>
        {error != null && <ErrorNote error={error} />}
      </form>
    </div>
  );
}
