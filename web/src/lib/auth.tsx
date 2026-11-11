// Who the app is acting as, shared with every page through React context. There is no sign-in screen: entering
// an area signs in as that area's default demo person, and the header's "Viewing as" switcher changes person.
//
// LEARNING NOTES
// - "No login" is a UX choice, not a security one. Behind the scenes every request still carries a signed token
//   (from /auth/dev-login), and the API still decides every permission from it. That's why switching from the
//   officer to the fraud specialist changes what you can approve, and why customers still can't read staff data.
// - `kind` and `roles` here only decide which screens to SHOW. Editing them in devtools unlocks nothing but
//   a page full of 403s.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { post, tokens, type Persona } from "./api";

export const DEFAULT_PERSONA = { customer: "jordan.brown", staff: "officer-1" } as const;
export type Kind = keyof typeof DEFAULT_PERSONA;

type Session = { persona: Persona } | null;
type AuthCtx = {
  session: Session;
  /** Act as this demo person (gets a fresh token). */
  switchTo: (username: string) => Promise<Persona>;
  /** Make sure we're acting as someone of this kind; signs in as the default person if not. */
  ensure: (kind: Kind) => Promise<void>;
  hasRole: (...roles: string[]) => boolean;
};

const Ctx = createContext<AuthCtx | null>(null);
const PERSONA_KEY = "agentops.persona";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session>(() => {
    const raw = sessionStorage.getItem(PERSONA_KEY);
    return raw && tokens.get() ? { persona: JSON.parse(raw) as Persona } : null;
  });
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const inflight = useRef<Promise<Persona> | null>(null);

  const switchTo = useCallback(async (username: string) => {
    const r = await post<{ token: string; persona: Persona }>("/auth/dev-login", { username });
    tokens.set(r.token);
    sessionStorage.setItem(PERSONA_KEY, JSON.stringify(r.persona));
    setSession({ persona: r.persona });
    return r.persona;
  }, []);

  const ensure = useCallback(
    async (kind: Kind) => {
      if (sessionRef.current?.persona.kind === kind) return;
      // StrictMode runs effects twice in development; share one request instead of minting two tokens.
      inflight.current ??= switchTo(DEFAULT_PERSONA[kind]).finally(() => (inflight.current = null));
      await inflight.current;
    },
    [switchTo],
  );

  // An expired or rejected token (401): forget it; the area's guard signs in again on the next render.
  useEffect(() => {
    const reset = () => {
      tokens.clear();
      sessionStorage.removeItem(PERSONA_KEY);
      setSession(null);
    };
    window.addEventListener("agentops:unauthorized", reset);
    return () => window.removeEventListener("agentops:unauthorized", reset);
  }, []);

  const hasRole = useCallback(
    (...roles: string[]) => !!session && roles.some((r) => session.persona.roles.includes(r)),
    [session],
  );

  return <Ctx.Provider value={{ session, switchTo, ensure, hasRole }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}
