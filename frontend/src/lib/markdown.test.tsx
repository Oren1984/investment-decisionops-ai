import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Markdown } from "./markdown";

describe("Markdown lists", () => {
  it("nests indented items under the item above and keeps the numbering", () => {
    const source = "1. First\n2. Choose a type:\n   - **Link**: paste it\n   - Simulated\n3. Third\n4. Fourth";
    const { container } = render(<MemoryRouter><Markdown source={source} /></MemoryRouter>);
    const top = container.querySelectorAll(".prose-help > ol");
    expect(top).toHaveLength(1);
    expect(top[0].querySelectorAll(":scope > li")).toHaveLength(4);
    const nested = top[0].querySelectorAll(":scope > li:nth-child(2) > ul > li");
    expect([...nested].map((li) => li.textContent)).toEqual(["Link: paste it", "Simulated"]);
  });

  it("continues a numbered list that resumes after other content", () => {
    const { container } = render(<MemoryRouter><Markdown source={"3. Third\n4. Fourth"} /></MemoryRouter>);
    expect(container.querySelector("ol")?.getAttribute("start")).toBe("3");
  });

  it("renders *italics* and leaves list markers and bold alone", () => {
    const { container } = render(<MemoryRouter><Markdown source={"Shows *Evidence incomplete* and **bold**."} /></MemoryRouter>);
    expect(container.querySelector("em")?.textContent).toBe("Evidence incomplete");
    expect(container.querySelector("strong")?.textContent).toBe("bold");
  });
});
