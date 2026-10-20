import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { WorkflowBarData } from "../../api/types";
import { renderWithProviders } from "../../test-utils";
import { WorkflowBar } from "./WorkflowBar";

const base: WorkflowBarData = {
  decision_id: "d1",
  title: "Add to NVDA?",
  status: "analyzing",
  status_label: "Analyzing",
  stages: [
    { key: "scoped", label: "Scoped", state: "done" },
    { key: "researching", label: "Research", state: "done" },
    { key: "analyzing", label: "Analysis", state: "current" },
    { key: "decided", label: "Decided", state: "todo" },
  ],
  blockers: [],
  next_action: "Wait for the analysis step",
  run: { id: "r1", status: "running", mode: "model", current_step: "analysis" },
};

describe("WorkflowBar", () => {
  it("shows the current stage, next action and the live run", () => {
    renderWithProviders(<WorkflowBar data={base} />);
    expect(screen.getByText("Analysis").closest("[aria-current]")).toHaveAttribute("aria-current", "step");
    expect(screen.getByText(/Wait for the analysis step/)).toBeInTheDocument();
    expect(screen.getByText(/model run running · analysis/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Run history/ })).toHaveAttribute("href", "/decisions/d1/runs/r1");
  });

  it("surfaces blockers as an alert and marks blocked decisions", () => {
    renderWithProviders(
      <WorkflowBar data={{ ...base, status: "blocked", blockers: ["no_sources: research found no sources."], run: null }} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("no_sources");
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Run history/ })).not.toBeInTheDocument();
  });
});
