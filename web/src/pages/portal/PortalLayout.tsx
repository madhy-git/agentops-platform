// Customer portal frame: top navigation, signed-in customer, page outlet.
import { HelpCircle, Home, Plus } from "lucide-react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { ErrorBoundary } from "../../components/ErrorBoundary";
import { PersonaSwitcher } from "../../components/PersonaSwitcher";
import { cx, Logo } from "../../components/ui";

const NAV = [
  { to: "/portal", label: "My requests", icon: Home, end: true },
  { to: "/portal/new", label: "New request", icon: Plus },
  { to: "/portal/help", label: "Help", icon: HelpCircle },
];

export default function PortalLayout() {
  const location = useLocation(); // a new page gets a fresh boundary, so navigating away clears an error
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-zinc-200/70 bg-white/80 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80">
        <div className="mx-auto flex h-16 max-w-5xl items-center gap-6 px-4 sm:px-6">
          <Link to="/">
            <Logo />
          </Link>
          <nav className="flex flex-1 gap-1 overflow-x-auto">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cx(
                    "flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium whitespace-nowrap",
                    isActive
                      ? "bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300"
                      : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-900",
                  )
                }
              >
                <Icon className="size-4" />
                <span className="hidden sm:inline">{label}</span>
              </NavLink>
            ))}
          </nav>
          <PersonaSwitcher kind="customer" home="/portal" />
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <ErrorBoundary key={location.pathname}>
            <Outlet />
          </ErrorBoundary>
      </main>
    </div>
  );
}
