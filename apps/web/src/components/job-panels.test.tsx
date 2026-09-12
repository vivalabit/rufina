import { aiMatchFixture } from "@/test/ai-match-fixture";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { JobMainPanel } from "@/components/job-main-panel";
import {
  JobDetails,
  MatchPanel,
  SalaryInsights,
} from "@/components/job-summary-panels";
import { ManualJobDialog } from "@/components/manual-job-dialog";
import { demoJobs } from "@/features/jobs/model/demo-jobs";

it("renders the selected vacancy panels from job props", () => {
  const job = demoJobs[0];

  render(
    <>
      <JobMainPanel job={job} tab="Overview" />
      <JobDetails job={job} />
      <SalaryInsights job={job} />
    </>,
  );

  expect(screen.getByRole("heading", { name: "Job Description" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Job Details" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Salary Insights" })).toBeInTheDocument();
  expect(screen.getAllByText(job.location).length).toBeGreaterThan(0);
});

it("opens match score details", () => {
  const onReviewFullAnalysis = vi.fn();

  render(
    <>
      <MatchPanel
        job={demoJobs[0]}
        onReviewFullAnalysis={onReviewFullAnalysis}
      />
    </>,
  );

  fireEvent.click(screen.getByRole("button", { name: /view score details/i }));

  expect(onReviewFullAnalysis).toHaveBeenCalledOnce();
});

it("keeps the manual vacancy dialog controlled", () => {
  const onChange = vi.fn();
  const onSave = vi.fn();

  render(
    <ManualJobDialog
      draft={{
        title: "Product Designer",
        company: "Acme",
        location: "Zurich",
        applyUrl: "https://example.com/job",
        overview: "Design a complex product experience.",
      }}
      onChange={onChange}
      onClose={vi.fn()}
      onSave={onSave}
    />,
  );

  fireEvent.change(screen.getByLabelText("Role title *"), {
    target: { value: "Staff Designer" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add and analyze" }));

  expect(onChange).toHaveBeenCalledWith("title", "Staff Designer");
  expect(onSave).toHaveBeenCalledOnce();
});

it("shows suitability and calculation metadata without legacy analysis", () => {
  const job = { ...demoJobs[0], aiMatch: aiMatchFixture };
  render(<JobMainPanel job={job} tab="AI Match" />);
  expect(screen.getByText("82%")).toBeInTheDocument();
  expect(screen.getByText("Updated")).toBeInTheDocument();
  expect(screen.getByText("Source")).toBeInTheDocument();
  expect(screen.queryByText(/reasons|gaps|confidence|recommendations|explanation/i)).not.toBeInTheDocument();
});
