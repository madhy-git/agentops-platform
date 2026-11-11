// @vitest-environment jsdom
// The whole app in a simulated browser, against a fake API built from real responses. Catches crashes that only
// happen when pages, layout, polling and session handling run together.
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { AuthProvider } from "./lib/auth";

const OFFICER = { username: "officer-1", display_name: "Alex Officer", roles: ["officer"], kind: "staff", blurb: "Officer", customer_id: null };
const JORDAN = { username: "jordan.brown", display_name: "Jordan Brown", roles: ["customer"], kind: "customer", blurb: "Customer", customer_id: "CUS-00001" };
const STREAM =
  "event: delta\r\ndata: Card disputes must be lodged within 120 days \r\n\r\nevent: delta\r\ndata: [POL-DISP-01#1]. \r\n\r\n" +
  'event: done\r\ndata: {"text": "Card disputes must be lodged within 120 days [POL-DISP-01#1]. ", "sources": ["POL-DISP-01#1"], "referred_to": null, "ttft_ms": 37.0, "session_id": "s-1"}\r\n\r\n';

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
const sse = (body: string) =>
  new Response(
    new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(new TextEncoder().encode(body));
        c.close();
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" } },
  );

function fakeApi(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = String(input);
  const body = init?.body ? JSON.parse(String(init.body)) : {};
  if (url.startsWith("/api/auth/personas")) return Promise.resolve(json({ enabled: true, personas: [JORDAN, OFFICER] }));
  if (url.startsWith("/api/auth/dev-login"))
    return Promise.resolve(json({ token: "t", persona: body.username === "jordan.brown" ? JORDAN : OFFICER }));
  if (url.startsWith("/api/stats")) return Promise.resolve(json({ cases_by_state: {}, approvals: { pending: 0, overdue: 0, mine: 0, decided_24h: 0 } }));
  if (url.includes("/stream")) return Promise.resolve(sse(STREAM));
  if (url.startsWith("/api/cases")) return Promise.resolve(json([]));
  if (url.startsWith("/api/portal/cases")) return Promise.resolve(json([]));
  return Promise.resolve(new Response("not found", { status: 404 }));
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  Element.prototype.scrollIntoView = vi.fn(() => Promise.resolve()) as unknown as Element["scrollIntoView"]; // like Chrome 156: returns a Promise
  vi.spyOn(globalThis, "fetch").mockImplementation(fakeApi);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("app", () => {
  it("staff copilot: opens without a login and streams a cited answer", async () => {
    renderAt("/staff/copilot");
    const suggestion = await screen.findByText("How long does a customer have to dispute a card transaction?");
    await act(async () => fireEvent.click(suggestion));
    await act(async () => fireEvent.submit(document.querySelector("form")!)); // suggestion fills the box; send it
    await waitFor(() => expect(screen.getByText("POL-DISP-01#1")).toBeTruthy());
    expect(screen.getByText(/Card disputes must be lodged/)).toBeTruthy();
  });

  it("customer help assistant streams an answer", async () => {
    renderAt("/portal/help");
    const suggestion = await screen.findByText("How much is the foreign transaction fee?");
    await act(async () => fireEvent.click(suggestion));
    await act(async () => fireEvent.submit(document.querySelector("form")!)); // suggestion fills the box; send it
    await waitFor(() => expect(screen.getByText("POL-DISP-01#1")).toBeTruthy());
  });

  it("moving from the portal to the staff copilot switches person without crashing", async () => {
    renderAt("/portal");
    await screen.findByText(/how can we help today/i);
    cleanup();
    renderAt("/staff/copilot");
    expect(await screen.findByRole("heading", { name: "Policy copilot" })).toBeTruthy();
  });
});

describe("error boundary", () => {
  it("shows the error message instead of a blank page when a page throws", async () => {
    const { ErrorBoundary } = await import("./components/ErrorBoundary");
    vi.spyOn(console, "error").mockImplementation(() => {});
    function Boom(): never {
      throw new Error("kaboom in render");
    }
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("kaboom in render")).toBeTruthy();
    expect(screen.getByText("Try again")).toBeTruthy();
  });
});
