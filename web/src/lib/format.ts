// Small display helpers shared by both apps.

export function timeAgo(iso: string, now = Date.now()): string {
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** "in 42 min" / "overdue by 3 h": approvals are judged against their SLA, never auto-approved. */
export function slaLabel(dueIso: string, now = Date.now()): { text: string; overdue: boolean } {
  const diff = Math.round((new Date(dueIso).getTime() - now) / 60000);
  const abs = Math.abs(diff);
  const span = abs < 60 ? `${abs} min` : abs < 48 * 60 ? `${Math.round(abs / 60)} h` : `${Math.round(abs / 1440)} d`;
  return diff >= 0 ? { text: `due in ${span}`, overdue: false } : { text: `overdue by ${span}`, overdue: true };
}

export const humanize = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
