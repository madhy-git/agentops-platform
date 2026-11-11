// "How the AI triaged this": the decision trail for one case, staff only.
//
// LEARNING NOTES
// - Each step shows evidence, not a summary of it: the exact text the model received (after PII masking), the
//   instructions, every tool call and what came back, the validated output, then the rules that fired on top.
//   That's what lets a reviewer answer "why did this case go to fraud?" without trusting anyone's say-so.
// - The model's justification is shown as a CLAIM, next to the evidence it should match. Models can give
//   plausible reasons that aren't how they actually decided; the trail makes that checkable.
// - The final authority is visible too: the model recommends a category and action, the rules (versioned,
//   deterministic) decide queue, actions, flags and whether a human must approve.
import { ArrowRight, Bot, ChevronDown, ChevronRight, FileSearch, Gavel, ScrollText, ShieldCheck, Sparkles, UserRound } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { AiTrail as Trail, TrailMessage, TrailPart } from "../lib/api";
import { dateTime, humanize } from "../lib/format";
import { Badge, Card, cx, ErrorNote, Spinner } from "./ui";

function Step({ n, icon, title, children }: { n: number; icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <li className="relative flex gap-4 pb-7 last:pb-0">
      <span className="absolute top-9 left-[17px] h-[calc(100%-2.25rem)] w-px bg-zinc-200 last:hidden dark:bg-zinc-800" />
      <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700 ring-1 ring-brand-200 dark:bg-brand-950 dark:text-brand-300 dark:ring-brand-800">
        {icon}
      </div>
      <div className="min-w-0 flex-1 pt-1.5">
        <p className="text-sm font-semibold">
          <span className="mr-1.5 text-zinc-400">{n}.</span>
          {title}
        </p>
        <div className="mt-2 space-y-2 text-sm">{children}</div>
      </div>
    </li>
  );
}

function Json({ value }: { value: unknown }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <pre className="max-h-64 overflow-auto rounded-lg bg-zinc-50 p-3 text-xs leading-relaxed whitespace-pre-wrap ring-1 ring-zinc-200 dark:bg-zinc-950 dark:ring-zinc-800">
      {text}
    </pre>
  );
}

function Part({ part }: { part: TrailPart }) {
  switch (part.part_kind) {
    case "user-prompt":
      return (
        <div>
          <Badge tone="blue">customer message (redacted)</Badge>
          <Json value={part.content} />
        </div>
      );
    case "tool-call":
      return (
        <div>
          <Badge tone="violet">
            {part.tool_name === "final_result" ? "model's final answer (structured output)" : `model calls tool: ${part.tool_name}`}
          </Badge>
          <Json value={part.args} />
        </div>
      );
    case "tool-return":
      return (
        <div>
          <Badge tone="neutral">{part.tool_name === "final_result" ? "output accepted (schema validated)" : `tool result: ${part.tool_name}`}</Badge>
          <Json value={part.content} />
        </div>
      );
    default:
      return (
        <div>
          <Badge tone="neutral">{part.part_kind}</Badge>
          <Json value={part.content ?? part.args} />
        </div>
      );
  }
}

function Transcript({ messages }: { messages: TrailMessage[] }) {
  const [open, setOpen] = useState(false);
  const instructions = messages.find((m) => m.instructions)?.instructions;
  return (
    <div className="rounded-xl ring-1 ring-zinc-200 dark:ring-zinc-800">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-medium">
        {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        Exact conversation with the model ({messages.length} messages)
      </button>
      {open && (
        <div className="space-y-4 border-t border-zinc-200 p-3 dark:border-zinc-800">
          {instructions && (
            <div>
              <Badge tone="amber">system instructions (versioned prompt)</Badge>
              <Json value={instructions} />
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={cx("space-y-2 border-l-2 pl-3", m.kind === "request" ? "border-sky-300" : "border-violet-300")}>
              <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">
                {m.kind === "request" ? <UserRound className="size-3.5" /> : <Bot className="size-3.5" />}
                {m.kind === "request" ? "sent to the model" : `model replied${m.model_name ? ` (${m.model_name})` : ""}`}
              </p>
              {m.parts.map((p, j) => (
                <Part key={j} part={p} />
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Kv({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex gap-3">
      <span className="w-40 shrink-0 text-zinc-500">{k}</span>
      <span className="min-w-0">{v}</span>
    </div>
  );
}

export function AiTrail({ data, error, loading }: { data: Trail | null; error: unknown; loading: boolean }) {
  if (loading) return <Spinner label="Loading AI decision trail" />;
  if (error != null) return <ErrorNote error={error} />;
  const t = data?.trace;
  if (!t)
    return <p className="text-sm text-zinc-500">No AI trail for this case (it was created before the trail existed, or without triage).</p>;
  const o = t.output;
  const d = t.decision;
  const searched = t.messages.flatMap((m) => m.parts).filter((p) => p.part_kind === "tool-call" && p.tool_name !== "final_result");

  return (
    <ol>
      <Step n={1} icon={<UserRound className="size-4" />} title="What the AI received">
        <p className="rounded-lg bg-zinc-50 p-3 dark:bg-zinc-950">{t.redacted_input}</p>
        <div className="flex flex-wrap gap-1.5">
          {Object.keys(t.redactions).length ? (
            Object.entries(t.redactions).map(([k, n]) => (
              <Badge key={k} tone="amber">
                {k} masked ×{n}
              </Badge>
            ))
          ) : (
            <Badge tone="neutral">no personal data found to mask</Badge>
          )}
          <Badge tone="brand">
            <ShieldCheck className="size-3" /> injection check passed
          </Badge>
        </div>
        <p className="text-xs text-zinc-500">Only this masked text is stored or sent to a model; the original never is.</p>
      </Step>

      <Step n={2} icon={<Sparkles className="size-4" />} title="Which model, and why">
        <Kv k="Model" v={<span className="font-mono">{t.model}</span>} />
        <Kv k="Routing reason" v={t.route_reason ?? "n/a"} />
        <Kv k="Prompt version" v={`triage ${t.prompt_version}`} />
        {t.failed_models.length > 0 && <Kv k="Fell back from" v={<span className="text-red-600">{t.failed_models.join(", ")}</span>} />}
      </Step>

      <Step n={3} icon={<FileSearch className="size-4" />} title="What the model looked up">
        {searched.length === 0 && <p className="text-zinc-500">No tools called.</p>}
        {searched.map((p, i) => (
          <p key={i}>
            <span className="font-mono text-xs">{p.tool_name}</span> <span className="text-zinc-500">with</span>{" "}
            <span className="font-mono text-xs">{JSON.stringify(p.args)}</span>
          </p>
        ))}
        <Transcript messages={t.messages} />
      </Step>

      <Step n={4} icon={<Bot className="size-4" />} title="What the model recommended">
        <div className="flex flex-wrap gap-1.5">
          <Badge tone="violet">category: {o.category}</Badge>
          <Badge tone={o.severity === "high" ? "red" : o.severity === "medium" ? "amber" : "neutral"}>severity: {o.severity}</Badge>
          <Badge tone="neutral">confidence: {Math.round(o.confidence * 100)}%</Badge>
          <Badge tone="neutral">action: {humanize(o.recommended_action)}</Badge>
          {o.needs_human && <Badge tone="amber">asks for a human</Badge>}
        </div>
        <div className="rounded-lg border-l-4 border-violet-300 bg-violet-50/60 p-3 dark:bg-violet-950/30">
          <p className="text-xs font-semibold uppercase tracking-wide text-violet-700 dark:text-violet-300">Model's justification</p>
          <p className="mt-1">{o.rationale || <span className="text-zinc-500">No justification given.</span>}</p>
          <p className="mt-2 text-xs text-zinc-500">
            This is the model's own explanation: compare it with the message in step 1. It isn't proof of how the model decided.
          </p>
        </div>
        {o.citations.length > 0 && <Kv k="Policies cited" v={o.citations.join(", ")} />}
      </Step>

      <Step n={5} icon={<Gavel className="size-4" />} title={`What the rules decided (policy ${data!.policy_version})`}>
        <p className="text-zinc-500">The model only recommends. These deterministic rules decide the outcome:</p>
        <ul className="space-y-1.5">
          {data!.rules_fired.map((r) => (
            <li key={r.reason_code} className="flex flex-wrap items-center gap-1.5">
              <Badge tone="violet">
                {r.id} · {r.reason_code}
              </Badge>
              <span className="font-mono text-xs text-zinc-500">when {JSON.stringify(r.when)}</span>
              <ArrowRight className="size-3 text-zinc-400" />
              <span className="font-mono text-xs text-zinc-500">{JSON.stringify(r.then)}</span>
            </li>
          ))}
        </ul>
        {d && (
          <>
            <Kv k="Queue / priority" v={`${humanize(d.queue)} · ${d.priority}`} />
            <Kv k="Actions authorised" v={d.actions.map(humanize).join(", ") || "none"} />
            <Kv
              k="Human approval"
              v={d.needs_approval || o.needs_human ? "Required before any action runs" : "Not required"}
            />
            {d.flags_set.length > 0 && <Kv k="Flags set" v={d.flags_set.map(humanize).join(", ")} />}
          </>
        )}
      </Step>

      <Step n={6} icon={<ScrollText className="size-4" />} title="Audit trail for this case">
        <ul className="divide-y divide-zinc-100 rounded-lg ring-1 ring-zinc-200 dark:divide-zinc-800 dark:ring-zinc-800">
          {data!.audit.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-2 px-3 py-1.5 text-xs">
              <span className="w-28 shrink-0 text-zinc-500 tabular-nums">{dateTime(e.ts)}</span>
              <Badge tone="neutral">{humanize(e.event)}</Badge>
              <span className="text-zinc-600 dark:text-zinc-300">{e.actor}</span>
              {e.reason_code && <span className="font-mono text-zinc-500">{e.reason_code}</span>}
              {"to_state" in e.data && <span className="text-zinc-500">→ {String(e.data.to_state)}</span>}
            </li>
          ))}
        </ul>
        <p className="text-xs text-zinc-500">
          {t.input_tokens ?? 0} tokens in · {t.output_tokens ?? 0} out · {Number(t.latency_ms ?? 0).toFixed(0)} ms
          {t.trace_id && <> · trace <span className="font-mono">{t.trace_id.slice(0, 16)}…</span></>}
        </p>
      </Step>
    </ol>
  );
}

export function AiTrailCard({ children }: { children: ReactNode }) {
  return (
    <Card className="p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-zinc-500">
        <Sparkles className="size-4" /> How the AI triaged this case
        <Badge tone="neutral" className="ml-auto normal-case tracking-normal">staff only</Badge>
      </h2>
      {children}
    </Card>
  );
}
