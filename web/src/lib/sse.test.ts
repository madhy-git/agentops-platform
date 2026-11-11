import { describe, expect, it } from "vitest";
import { SseParser } from "./sse";

describe("SseParser", () => {
  it("emits events only when complete, across arbitrary chunk boundaries", () => {
    const p = new SseParser();
    const stream = "event: delta\r\ndata: Card \r\n\r\nevent: delta\r\ndata: disputes \r\n\r\nevent: done\r\ndata: {\"sources\":[]}\r\n\r\n";
    // Feed one character at a time: the worst case a network can produce.
    const events = [...stream].flatMap((ch) => p.push(ch));
    expect(events).toEqual([
      { event: "delta", data: "Card " },
      { event: "delta", data: "disputes " },
      { event: "done", data: '{"sources":[]}' },
    ]);
  });

  it("ignores keep-alive comments", () => {
    expect(new SseParser().push(": ping\r\n\r\nevent: delta\ndata: hi\n\n")).toEqual([{ event: "delta", data: "hi" }]);
  });
});
