// @vitest-environment jsdom
// Renders the AI decision trail from a REAL API response (aiTrail.fixture.json, captured from /cases/{id}/ai-trail).
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { AiTrail as Trail } from "../lib/api";
import { AiTrail } from "./AiTrail";
import fixture from "./aiTrail.fixture.json";

afterEach(cleanup);

describe("AiTrail", () => {
  it("shows the masked input, the model's justification and the rules that decided", () => {
    render(<AiTrail data={fixture as unknown as Trail} error={null} loading={false} />);
    expect(screen.getAllByText(/\[PHONE\]/).length).toBeGreaterThan(0); // input and the search the model ran
    expect(document.body.textContent).toContain("PHONE masked ×1");
    expect(screen.getByText(/contains "stolen", a fraud indicator/)).toBeTruthy();
    expect(screen.getByText(/R1 · FRAUD_SUSPECTED/)).toBeTruthy();
    expect(document.body.textContent).not.toContain("0411"); // the raw phone number is nowhere on the page
  });

  it("expands to the exact conversation, including the system instructions", () => {
    render(<AiTrail data={fixture as unknown as Trail} error={null} loading={false} />);
    fireEvent.click(screen.getByText(/Exact conversation with the model/));
    expect(screen.getByText("system instructions (versioned prompt)")).toBeTruthy();
    expect(screen.getByText("model calls tool: search_policy")).toBeTruthy();
  });
});
