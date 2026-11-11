// "Viewing as": switch demo person within an area. Switching gets a new signed token for that person, so the
// API (not this menu) decides what they can see and do.
import { Check, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Persona } from "../lib/api";
import { useAuth, type Kind } from "../lib/auth";
import { useApi } from "../lib/useApi";
import { cx } from "./ui";

export function PersonaSwitcher({ kind, home }: { kind: Kind; home: string }) {
  const { session, switchTo } = useAuth();
  const { data } = useApi<{ personas: Persona[] }>("/auth/personas");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const me = session?.persona;

  useEffect(() => {
    const close = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  async function pick(p: Persona) {
    setOpen(false);
    if (p.username === me?.username) return;
    await switchTo(p.username);
    navigate(home); // the current page may not exist for the new person (e.g. another customer's request)
  }

  const initials = (n: string) => n.split(" ").map((w) => w[0]).join("").slice(0, 2);
  return (
    <div ref={box} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-xl px-2 py-1.5 text-left hover:bg-zinc-100 dark:hover:bg-zinc-800"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="flex size-8 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-800 dark:bg-brand-900 dark:text-brand-200">
          {me && initials(me.display_name)}
        </span>
        <span className="hidden leading-tight sm:block">
          <span className="block text-[10px] uppercase tracking-wide text-zinc-400">Viewing as</span>
          <span className="block text-sm font-medium">{me?.display_name}</span>
        </span>
        <ChevronDown className="size-4 text-zinc-400" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-30 mt-2 w-72 rounded-2xl bg-white p-1.5 shadow-xl ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-zinc-700">
          {data?.personas
            .filter((p) => p.kind === kind)
            .map((p) => (
              <button
                key={p.username}
                role="menuitem"
                onClick={() => void pick(p)}
                className={cx(
                  "flex w-full items-start gap-2 rounded-xl px-3 py-2 text-left hover:bg-zinc-50 dark:hover:bg-zinc-800",
                  p.username === me?.username && "bg-brand-50 dark:bg-brand-950",
                )}
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">{p.display_name}</span>
                  <span className="block truncate text-xs text-zinc-500">{p.blurb}</span>
                </span>
                {p.username === me?.username && <Check className="mt-0.5 size-4 text-brand-600" />}
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
