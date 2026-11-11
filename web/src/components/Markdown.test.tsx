// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";

afterEach(cleanup);

describe("Markdown", () => {
  it("renders paragraphs, bullets and bold, and strips citation markers", () => {
    const { container } = render(
      <Markdown text={"Disputes must be lodged within **120 days** [POL-DISP-01#1].\n\n- Check the date [POL-DISP-01#1]\n- Then lodge it"} />,
    );
    expect(container.querySelector("strong")?.textContent).toBe("120 days");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.textContent).not.toContain("POL-DISP");
  });

  it("never turns model output into live HTML", () => {
    const { container } = render(<Markdown text={'<img src=x onerror="alert(1)"> **hi**'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror="alert(1)">');
  });
});
