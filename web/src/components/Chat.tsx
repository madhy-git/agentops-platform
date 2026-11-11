// Streaming chat, shared by the customer help assistant and the staff policy copilot.
//
// LEARNING NOTES
// - Text appears as it streams (SSE deltas), so the first words show in ~100 ms instead of after the whole
//   answer. The "time to first token" the copilot reports is exactly that delay (docs/slo.md).
// - Citations like [POL-FAQ-01#1] are turned into chips, and the final `done` event lists the sources the
//   answer actually cited. A referral (staff only) renders as a banner: guidance exists, but not for you.
import { ArrowUp, BookOpen, Sparkles, UserRound } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { stream, type CopilotDone } from "../lib/api";
import { Markdown } from "./Markdown";
import { Badge, Button, cx, ErrorNote } from "./ui";

type Turn = { who: "user" | "assistant"; text: string; done?: CopilotDone; streaming?: boolean };


export function Chat({
  endpoint,
  suggestions,
  placeholder,
  emptyTitle,
  emptyText,
  referralNote,
}: {
  endpoint: string;
  suggestions: string[];
  placeholder: string;
  emptyTitle: string;
  emptyText: ReactNode;
  referralNote?: (to: string) => ReactNode;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [session, setSession] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLInputElement>(null);

  // Braces matter: an effect's return value is its cleanup, and React CALLS it before the next update. Newer
  // Chrome returns a Promise from scrollIntoView(), so `() => el.scrollIntoView()` handed React a Promise to call:
  // "R is not a function" in production ("destroy is not a function" in dev). Found on the live copilot page.
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  async function ask(question: string) {
    if (!question.trim() || busy) return;
    setInput("");
    setError(null);
    setBusy(true);
    setTurns((t) => [...t, { who: "user", text: question }, { who: "assistant", text: "", streaming: true }]);
    const update = (fn: (last: Turn) => Turn) =>
      setTurns((t) => [...t.slice(0, -1), fn(t[t.length - 1] as Turn)]);
    try {
      const done = await stream<CopilotDone>(endpoint, { question, session_id: session }, (delta) =>
        update((last) => ({ ...last, text: last.text + delta })),
      );
      setSession(done.session_id);
      update((last) => ({ ...last, streaming: false, done }));
    } catch (e) {
      setError(e);
      setTurns((t) => t.slice(0, -1));
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void ask(input);
  }

  return (
    <div className="flex h-full min-h-[28rem] flex-col">
      <div className="flex-1 space-y-5 overflow-y-auto p-1">
        {turns.length === 0 && (
          <div className="flex flex-col items-center gap-4 py-10 text-center">
            <div className="rounded-2xl bg-brand-50 p-3 text-brand-600 dark:bg-brand-950 dark:text-brand-300">
              <Sparkles className="size-6" />
            </div>
            <div>
              <p className="font-semibold">{emptyTitle}</p>
              <p className="mt-1 max-w-md text-sm text-zinc-500">{emptyText}</p>
            </div>
            <div className="flex max-w-xl flex-wrap justify-center gap-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  // Fills the box rather than sending: people want to read, maybe edit, then press send.
                  onClick={() => {
                    setInput(s);
                    box.current?.focus();
                  }}
                  className="rounded-full bg-white px-3 py-1.5 text-sm ring-1 ring-zinc-200 hover:bg-zinc-50 dark:bg-zinc-900 dark:ring-zinc-700 dark:hover:bg-zinc-800"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={cx("flex gap-3", t.who === "user" && "flex-row-reverse")}>
            <div
              className={cx(
                "flex size-8 shrink-0 items-center justify-center rounded-full",
                t.who === "user" ? "bg-zinc-200 dark:bg-zinc-700" : "bg-brand-600 text-white",
              )}
            >
              {t.who === "user" ? <UserRound className="size-4" /> : <Sparkles className="size-4" />}
            </div>
            <div className={cx("max-w-[80%] space-y-2", t.who === "user" && "text-right")}>
              <div
                className={cx(
                  "inline-block rounded-2xl px-4 py-2.5 text-left text-sm leading-relaxed",
                  t.who === "user"
                    ? "bg-brand-600 text-white"
                    : "bg-white ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-zinc-800",
                  t.streaming && "typing-cursor",
                )}
              >
                {t.who === "assistant" ? <Markdown text={t.text} /> : t.text}
              </div>
              {t.done && t.done.sources.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <BookOpen className="size-3.5 text-zinc-400" />
                  {t.done.sources.map((s) => (
                    <Badge key={s} tone="brand">
                      {s}
                    </Badge>
                  ))}
                  {t.done.ttft_ms != null && (
                    <span className="text-xs text-zinc-400">· first token {Math.round(t.done.ttft_ms)} ms</span>
                  )}
                </div>
              )}
              {t.done && (
                <div className="text-xs text-zinc-400">
                  {t.done.answered_by === "guardrail"
                    ? "Declined by a safety check (no AI involved)"
                    : t.done.answered_by === "no_match"
                    ? "No matching policy found, so no AI answer was generated"
                    : t.done.answered_by === "referral"
                    ? "Restricted for your role, so no AI answer was generated"
                    : t.done.answered_by === "live"
                    ? "Answered by Gemini (live model)"
                    : t.done.answered_by === "offline-fallback"
                      ? "Gemini unavailable: offline answer"
                      : "Offline model (no AI)"}
                </div>
              )}
              {t.done?.referred_to && referralNote && referralNote(t.done.referred_to)}
            </div>
          </div>
        ))}
        <div ref={end} />
      </div>
      {error != null && <ErrorNote error={error} />}
      <form onSubmit={submit} className="mt-4 flex items-center gap-2 rounded-2xl bg-white p-2 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-zinc-700">
        <input
          ref={box}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={placeholder}
          maxLength={500}
          className="flex-1 bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-zinc-400"
        />
        <Button type="submit" loading={busy} disabled={!input.trim()} aria-label="Send" className="rounded-xl px-2.5">
          {!busy && <ArrowUp className="size-4" />}
        </Button>
      </form>
    </div>
  );
}
