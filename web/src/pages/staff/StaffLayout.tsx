// Staff workspace frame: sidebar navigation (what you see depends on your roles), "Viewing as", page outlet.
import { BookOpenText, ClipboardCheck, FolderKanban, LayoutDashboard, ScrollText } from "lucide-react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { ErrorBoundary } from "../../components/ErrorBoundary";
import { PersonaSwitcher } from "../../components/PersonaSwitcher";
import { Badge, cx, Logo } from "../../components/ui";
import type { Stats } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useApi } from "../../lib/useApi";

export default function StaffLayout() {
  const location = useLocation(); // a new page gets a fresh boundary, so navigating away clears an error
  const { hasRole, session } = useAuth();
  // Re-fetch when the person changes: "my approvals" belongs to whoever you're viewing as.
  const { data: stats } = useApi<Stats>(`/stats?as=${session?.persona.username}`, 15_000);
  const nav = [
    { to: "/staff", label: "Dashboard", icon: LayoutDashboard, end: true, show: true },
    { to: "/staff/cases", label: "Cases", icon: FolderKanban, show: true },
    {
      to: "/staff/approvals",
      label: "My approvals",
      icon: ClipboardCheck,
      show: !hasRole("compliance"),
      count: stats?.approvals.mine,
    },
    { to: "/staff/copilot", label: "Policy copilot", icon: BookOpenText, show: !hasRole("compliance") },
    { to: "/staff/audit", label: "Audit trail", icon: ScrollText, show: hasRole("manager", "compliance") },
  ];

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-zinc-200 bg-white px-3 py-5 md:flex dark:border-zinc-800 dark:bg-zinc-900">
        <Link to="/" className="px-2">
          <Logo />
        </Link>
        <p className="mt-6 px-3 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">Staff workspace</p>
        <nav className="mt-2 flex flex-col gap-0.5">
          {nav
            .filter((n) => n.show)
            .map(({ to, label, icon: Icon, end, count }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cx(
                    "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium",
                    isActive
                      ? "bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300"
                      : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800",
                  )
                }
              >
                <Icon className="size-4" />
                <span className="flex-1">{label}</span>
                {!!count && <Badge tone="amber">{count}</Badge>}
              </NavLink>
            ))}
        </nav>
        <div className="mt-auto rounded-xl bg-zinc-50 p-3 text-xs text-zinc-500 dark:bg-zinc-950">
          Roles: {session?.persona.roles.join(", ")}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-3 border-b border-zinc-200 bg-white/80 px-4 backdrop-blur sm:px-8 dark:border-zinc-800 dark:bg-zinc-950/80">
          <nav className="flex gap-1 overflow-x-auto md:hidden">
            {nav
              .filter((n) => n.show)
              .map(({ to, icon: Icon, end, label }) => (
                <NavLink key={to} to={to} end={end} aria-label={label} className={({ isActive }) => cx("rounded-lg p-2", isActive ? "bg-brand-50 text-brand-700" : "text-zinc-500")}>
                  <Icon className="size-5" />
                </NavLink>
              ))}
          </nav>
          <div className="hidden text-sm text-zinc-500 md:block">Wattle Bank operations (fictional)</div>
          <PersonaSwitcher kind="staff" home="/staff" />
        </header>
        <main className="flex-1 px-4 py-8 sm:px-8">
          <ErrorBoundary key={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
