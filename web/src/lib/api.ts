// Typed API client. Every call goes to /api (same origin; see vite.config.ts) with the bearer token.
//
// LEARNING NOTES
// - The token lives in sessionStorage: it survives a page refresh but not closing the tab, and it isn't sent
//   automatically like a cookie would be (so no CSRF). The trade-off: any script on the page could read it,
//   which is why the page loads no third-party scripts. Production: the identity provider's PKCE flow.
// - Errors carry the HTTP status, so pages can react to *meaning*: 401 -> sign in again, 403 -> "not allowed".
//   The server decides every permission; the UI only reflects its answers.
import { SseParser } from "./sse";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const TOKEN_KEY = "agentops.token";
export const tokens = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const t = tokens.get();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const r = await fetch(`/api${path}`, { ...init, headers });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = await r.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    if (r.status === 401) window.dispatchEvent(new Event("agentops:unauthorized"));
    throw new ApiError(r.status, detail);
  }
  return r.json() as Promise<T>;
}

export const get = <T>(path: string) => request<T>(path);
export const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

/** POST to an SSE endpoint; calls onDelta for each text chunk and resolves with the final `done` payload. */
export async function stream<T>(path: string, body: unknown, onDelta: (text: string) => void): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${tokens.get() ?? ""}` },
    body: JSON.stringify(body),
  });
  if (!r.ok || !r.body) throw new ApiError(r.status, r.statusText);
  const parser = new SseParser();
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let done: T | undefined;
  for (;;) {
    const { value, done: finished } = await reader.read();
    if (finished) break;
    for (const ev of parser.push(value)) {
      if (ev.event === "delta") onDelta(ev.data);
      else if (ev.event === "done") done = JSON.parse(ev.data) as T;
    }
  }
  if (done === undefined) throw new ApiError(500, "stream ended without a result");
  return done;
}

// --- shapes returned by the API (mirrors src/agentops/api.py and portal.py) ---------------------------------
export type Persona = {
  username: string;
  display_name: string;
  roles: string[];
  kind: "customer" | "staff";
  blurb: string;
  customer_id: string | null;
};

export type PortalCase = {
  id: number;
  reference: string;
  topic: string;
  status: string;
  status_detail: string;
  step: number;
  message: string;
  created_at: string;
  updated_at: string;
  expected_by: string | null;
  timeline?: { at: string; status: string; detail: string }[];
};

export type StaffCase = {
  id: number;
  customer_id: string | null;
  customer_name: string | null;
  state: string;
  queue: string;
  priority: string;
  summary: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  approval_id: number | null;
  approval_status: string | null;
  approver: string | null;
  sla_due: string | null;
  escalated_at: string | null;
};

export type Approval = {
  id: number;
  case_id: number;
  action: string;
  domain: string;
  requested_by: string;
  assigned_to: string;
  status: string;
  created_at: string;
  sla_due: string;
  reminded_at: string | null;
  escalated_at: string | null;
  decided_by: string | null;
  decided_at: string | null;
  reason: string | null;
  summary?: string;
  priority?: string;
  customer_id?: string | null;
  customer_name?: string | null;
};

export type Decision = {
  queue: string;
  priority: string;
  reason_codes: string[];
  actions: string[];
  needs_approval: boolean;
  flags_set: string[];
  suppressed_actions: string[];
  candidate_actions: string[];
  policy_version: string;
};

export type CaseDetail = StaffCase & {
  decision: Decision | null;
  approvals: Approval[];
  customer: { customer_id: string; name: string; lifecycle_stage: string; vulnerable: boolean; active_flags: string[] } | null;
  allowed_transitions: string[];
};

export type Stats = {
  cases_by_state: Record<string, number>;
  approvals: { pending: number; overdue: number; mine: number; decided_24h: number };
};

export type AuditEvent = {
  id: number;
  ts: string;
  event: string;
  actor: string;
  case_id: string | null;
  reason_code: string | null;
  policy_version: string | null;
  prompt_version: string | null;
  trace_id: string | null;
  data: Record<string, unknown>;
};

export type CopilotDone = {
  text?: string;
  sources: string[];
  referred_to?: string | null;
  ttft_ms?: number | null;
  session_id: string;
  answered_by?: "live" | "offline" | "offline-fallback" | "guardrail" | "referral" | "no_match";
};

// --- AI decision trail (GET /cases/{id}/ai-trail; staff only) ---------------------------------------------------
export type TrailPart = {
  part_kind: "user-prompt" | "tool-call" | "tool-return" | "text" | "system-prompt" | "retry-prompt" | string;
  content?: unknown;
  tool_name?: string;
  args?: unknown;
};
export type TrailMessage = { kind: "request" | "response"; instructions?: string | null; parts: TrailPart[]; model_name?: string | null };
export type AiTrail = {
  trace: {
    ts: string;
    actor: string;
    trace_id: string | null;
    prompt_version: string;
    model: string;
    route_reason: string | null;
    failed_models: string[];
    redacted_input: string;
    redactions: Record<string, number>;
    messages: TrailMessage[];
    output: {
      category: string;
      severity: string;
      summary: string;
      recommended_action: string;
      needs_human: boolean;
      confidence: number;
      citations: string[];
      rationale: string;
    };
    decision: Decision | null;
    input_tokens: number | null;
    output_tokens: number | null;
    cost_usd: string | number | null;
    latency_ms: string | number | null;
  } | null;
  rules_fired: { id: string | null; reason_code: string; when: Record<string, unknown> | null; then: Record<string, unknown> | null }[];
  policy_version: string;
  audit: AuditEvent[];
};
