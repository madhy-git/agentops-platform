// The customer's four-step progress bar. `step` comes from the API (portal.py STATUS), never computed here,
// so the portal and the timeline can't disagree about where a request is.
import { Check } from "lucide-react";
import { cx } from "./ui";

const STEPS = ["Received", "Reviewed", "Specialist", "Done"];

export function Progress({ step, compact }: { step: number; compact?: boolean }) {
  return (
    <ol className="flex items-center gap-1.5" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
      {STEPS.map((label, i) => (
        <li key={label} className="flex flex-1 flex-col gap-1.5">
          <div className={cx("h-1.5 rounded-full", i <= step ? "bg-brand-500" : "bg-zinc-200 dark:bg-zinc-800")} />
          {!compact && (
            <span className={cx("flex items-center gap-1 text-xs", i <= step ? "text-brand-700 dark:text-brand-300" : "text-zinc-400")}>
              {i < step && <Check className="size-3" />}
              {label}
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}
