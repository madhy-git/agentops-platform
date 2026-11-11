// Landing page: two ways in, no sign-in. Each area opens as its default demo person (lib/auth.tsx).
import { ArrowRight, Briefcase, ShieldCheck, UserRound } from "lucide-react";
import { Link } from "react-router-dom";
import { Logo } from "../components/ui";

function Door({ to, icon, title, text, points }: { to: string; icon: React.ReactNode; title: string; text: string; points: string[] }) {
  return (
    <Link
      to={to}
      className="group flex flex-col rounded-3xl bg-white p-7 ring-1 ring-zinc-200 transition hover:-translate-y-1 hover:shadow-xl hover:ring-brand-300 dark:bg-zinc-900 dark:ring-zinc-800 dark:hover:ring-brand-700"
    >
      <div className="flex size-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300">{icon}</div>
      <h2 className="mt-5 text-xl font-semibold tracking-tight">{title}</h2>
      <p className="mt-1 text-sm text-zinc-500">{text}</p>
      <ul className="mt-4 space-y-1.5 text-sm text-zinc-600 dark:text-zinc-400">
        {points.map((p) => (
          <li key={p} className="flex gap-2">
            <span className="mt-2 size-1.5 shrink-0 rounded-full bg-wattle-500" />
            {p}
          </li>
        ))}
      </ul>
      <span className="mt-6 inline-flex items-center gap-1 text-sm font-medium text-brand-700 dark:text-brand-300">
        Open <ArrowRight className="size-4 transition group-hover:translate-x-1" />
      </span>
    </Link>
  );
}

export default function Landing() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-brand-50 via-stone-50 to-wattle-300/20 dark:from-brand-950 dark:via-zinc-950 dark:to-zinc-950">
      <div className="mx-auto max-w-5xl px-6 py-12">
        <Logo />
        <div className="mt-12 max-w-2xl">
          <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">Banking help, with a human in the loop.</h1>
          <p className="mt-4 text-lg text-zinc-600 dark:text-zinc-400">
            Customers raise and track requests themselves. Staff triage, approve and answer with an AI copilot. Every
            regulated action waits for a specialist, and every step is audited.
          </p>
        </div>
        <div className="mt-12 grid gap-5 md:grid-cols-2">
          <Door
            to="/portal"
            icon={<UserRound className="size-6" />}
            title="Customer portal"
            text="Self-service for Wattle Bank customers."
            points={["Report a lost card, dispute a charge, ask for hardship help", "Track every request step by step", "Ask the help assistant, with sources"]}
          />
          <Door
            to="/staff"
            icon={<Briefcase className="size-6" />}
            title="Staff workspace"
            text="For officers, specialists, managers and compliance."
            points={["Live case queue and dashboard", "Approve or reject within SLA", "Policy copilot and the audit trail"]}
          />
        </div>
        <p className="mt-12 flex items-center gap-2 text-xs text-zinc-500">
          <ShieldCheck className="size-4" /> Demo: fictional bank, synthetic data, offline model. Use "Viewing as" in the
          header to switch person; what you can see and do follows that person's role.
        </p>
      </div>
    </div>
  );
}
