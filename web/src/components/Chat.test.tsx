// @vitest-environment jsdom
// Renders the real Chat component against a recorded server stream, in a simulated browser (jsdom).
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Chat } from "./Chat";

// Exactly what /api/copilot/stream sent (captured from the cluster), split into small network chunks.
const STREAM =
  "event: delta\r\ndata: Card \r\n\r\nevent: delta\r\ndata: disputes \r\n\r\nevent: delta\r\ndata: [POL-DISP-01#1]. \r\n\r\n" +
  'event: done\r\ndata: {"text": "Card disputes [POL-DISP-01#1]. ", "sources": ["POL-DISP-01#1"], "referred_to": null, "ttft_ms": 37.0, "session_id": "s-1"}\r\n\r\n';

function fakeStreamResponse(body: string): Response {
  const bytes = new TextEncoder().encode(body);
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      for (let i = 0; i < bytes.length; i += 7) c.enqueue(bytes.slice(i, i + 7));
      c.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Chat", () => {
  it("streams an answer, shows its source, and survives a follow-up question", async () => {
    Element.prototype.scrollIntoView = vi.fn(() => Promise.resolve()) as unknown as Element["scrollIntoView"]; // like Chrome 156: returns a Promise
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => fakeStreamResponse(STREAM));
    render(<Chat endpoint="/copilot/stream" suggestions={["How long to dispute?"]} placeholder="ask" emptyTitle="t" emptyText="e" />);

    await act(async () => fireEvent.click(screen.getByText("How long to dispute?")));
    await act(async () => fireEvent.submit(document.querySelector("form")!)); // suggestion fills the box; send it
    await waitFor(() => expect(screen.getByText("POL-DISP-01#1")).toBeTruthy());
    expect(screen.getByText(/Card disputes/)).toBeTruthy();

    const input = screen.getByPlaceholderText("ask");
    await act(async () => {
      fireEvent.change(input, { target: { value: "and a follow-up?" } });
      fireEvent.submit(input.closest("form")!);
    });
    await waitFor(() => expect(screen.getAllByText("POL-DISP-01#1")).toHaveLength(2));
    // The follow-up carries the session id from the first answer (conversation memory).
    expect(JSON.parse(fetchMock.mock.calls[1]![1]!.body as string).session_id).toBe("s-1");
  });
});

describe("Chat referral", () => {
  it("renders the referral banner when guidance is restricted", async () => {
    Element.prototype.scrollIntoView = vi.fn(() => Promise.resolve()) as unknown as Element["scrollIntoView"]; // like Chrome 156: returns a Promise
    const REFERRAL =
      "event: delta\r\ndata: More detailed guidance on this is restricted; refer the customer's case to the hardship specialist queue.\r\n\r\n" +
      'event: done\r\ndata: {"text": "More detailed guidance on this is restricted; refer the customer\'s case to the hardship specialist queue.", "sources": [], "referred_to": "the hardship specialist queue", "ttft_ms": null, "session_id": "s-2"}\r\n\r\n';
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => fakeStreamResponse(REFERRAL));
    render(
      <Chat endpoint="/copilot/stream" suggestions={["hardship?"]} placeholder="ask" emptyTitle="t" emptyText="e"
        referralNote={(to) => <div>REFER {to}</div>} />,
    );
    await act(async () => fireEvent.click(screen.getByText("hardship?")));
    await act(async () => fireEvent.submit(document.querySelector("form")!)); // suggestion fills the box; send it
    await waitFor(() => expect(screen.getByText("REFER the hardship specialist queue")).toBeTruthy());
  });
});

describe("Chat suggestions", () => {
  it("clicking a suggestion fills the box and does NOT send it", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(<Chat endpoint="/copilot/stream" suggestions={["How long to dispute?"]} placeholder="ask" emptyTitle="t" emptyText="e" />);
    fireEvent.click(screen.getByText("How long to dispute?"));
    expect((screen.getByPlaceholderText("ask") as HTMLInputElement).value).toBe("How long to dispute?");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
