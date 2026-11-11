// Server-Sent Events parser for POST streams (copilot and customer assistant).
//
// LEARNING NOTES
// - The browser's built-in EventSource only does GET and can't send an Authorization header, so streaming
//   endpoints that need a bearer token are read with fetch() + a ReadableStream, parsed here by hand.
// - SSE is line-based: "event: <name>", one or more "data: <text>" lines, then a blank line ends the event.
//   Network chunks don't respect those boundaries (one chunk can hold half a line), so the parser keeps a
//   buffer and only emits complete events. That's the bug a naive `chunk.split("\n")` has.
// - The server sends "\r\n" line endings (sse-starlette), so both "\r\n" and "\n" are accepted.

export type SseEvent = { event: string; data: string };

export class SseParser {
  private buffer = "";
  private event = "message";
  private data: string[] = [];

  /** Feed a network chunk; returns the events completed by it (zero or more). */
  push(chunk: string): SseEvent[] {
    this.buffer += chunk;
    const out: SseEvent[] = [];
    let nl: number;
    while ((nl = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, nl).replace(/\r$/, "");
      this.buffer = this.buffer.slice(nl + 1);
      if (line === "") {
        if (this.data.length) out.push({ event: this.event, data: this.data.join("\n") });
        this.event = "message";
        this.data = [];
      } else if (line.startsWith("event:")) {
        this.event = line.slice(6).trimStart();
      } else if (line.startsWith("data:")) {
        // Exactly one optional space after the colon is part of the syntax; the rest is content
        // (the copilot streams words with trailing spaces, which must survive).
        const v = line.slice(5);
        this.data.push(v.startsWith(" ") ? v.slice(1) : v);
      }
      // Lines starting with ":" are comments/keep-alives (sse-starlette sends ": ping"); ignored.
    }
    return out;
  }
}
