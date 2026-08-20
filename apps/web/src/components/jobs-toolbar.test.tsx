import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";

import { JobsToolbar } from "@/components/jobs-toolbar";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("renders the requested action order and opens auto-searches locally", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
    }),
  );

  render(
    <JobsToolbar
      savedJobsCount={2}
      archivedJobsCount={3}
      showSavedJobs={false}
      showArchivedJobs={false}
      isAnalysisMenuOpen={false}
      bulkAnalysisScope={null}
      recentAnalysisCount={4}
      missingAnalysisCount={5}
      onAddVacancy={vi.fn()}
      onSearchVacancies={vi.fn()}
      onToggleSavedJobs={vi.fn()}
      onToggleArchivedJobs={vi.fn()}
      onAnalysisMenuOpenChange={vi.fn()}
      onRunAnalysis={vi.fn()}
      onVacanciesChanged={vi.fn()}
    />,
  );

  const toolbar = screen.getByLabelText("Jobs actions");
  expect(
    within(toolbar)
      .getAllByRole("button")
      .map((button) => button.getAttribute("aria-label") || button.textContent?.trim()),
  ).toEqual([
    "Add vacancy",
    "Search vacancies",
    "Saved Jobs (2)",
    "Archived (3)",
    "Auto Search",
    "Vacancy Filter",
    "Analysis",
  ]);

  fireEvent.click(within(toolbar).getByRole("button", { name: "Auto Search" }));
  expect(
    screen.getByRole("dialog", { name: "Automatic searches" }),
  ).toBeInTheDocument();

  fireEvent.keyDown(window, { key: "Escape" });
  expect(
    screen.queryByRole("dialog", { name: "Automatic searches" }),
  ).not.toBeInTheDocument();

  fireEvent.click(
    within(toolbar).getByRole("button", { name: "Vacancy Filter" }),
  );
  expect(
    screen.getByRole("dialog", { name: "Vacancy Filter" }),
  ).toBeInTheDocument();

  fireEvent.keyDown(window, { key: "Escape" });
  expect(
    screen.queryByRole("dialog", { name: "Vacancy Filter" }),
  ).not.toBeInTheDocument();
});

it("shows the bulk analysis menu outside the scrolling action row", () => {
  const onRunAnalysis = vi.fn();

  function ControlledToolbar() {
    const [isOpen, setIsOpen] = useState(false);
    return (
      <JobsToolbar
        savedJobsCount={0}
        archivedJobsCount={0}
        showSavedJobs={false}
        showArchivedJobs={false}
        isAnalysisMenuOpen={isOpen}
        bulkAnalysisScope={null}
        recentAnalysisCount={2}
        missingAnalysisCount={3}
        onAddVacancy={vi.fn()}
        onSearchVacancies={vi.fn()}
        onToggleSavedJobs={vi.fn()}
        onToggleArchivedJobs={vi.fn()}
        onAnalysisMenuOpenChange={setIsOpen}
        onRunAnalysis={onRunAnalysis}
        onVacanciesChanged={vi.fn()}
      />
    );
  }

  render(<ControlledToolbar />);

  const actionRow = screen.getByLabelText("Jobs actions");
  fireEvent.click(within(actionRow).getByRole("button", { name: "Analysis" }));

  const menu = screen.getByRole("menu", { name: "Bulk AI analysis" });
  expect(menu).toBeVisible();
  expect(actionRow).not.toContainElement(menu);

  fireEvent.click(
    within(menu).getByRole("menuitem", {
      name: /Vacancies without current analysis/,
    }),
  );
  expect(onRunAnalysis).toHaveBeenCalledWith("missing");
});
