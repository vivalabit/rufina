import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { JobMainPanel } from "@/components/job-main-panel";
import {
  JobDetails,
  MatchPanel,
  RecommendationsPanel,
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

it("forwards actions from match and recommendation panels", () => {
  const onReviewFullAnalysis = vi.fn();
  const onViewAllRecommendations = vi.fn();

  render(
    <>
      <MatchPanel
        job={demoJobs[0]}
        onReviewFullAnalysis={onReviewFullAnalysis}
      />
      <RecommendationsPanel
        job={demoJobs[0]}
        onViewAllRecommendations={onViewAllRecommendations}
      />
    </>,
  );

  fireEvent.click(screen.getByRole("button", { name: /review full analysis/i }));
  fireEvent.click(screen.getByRole("button", { name: /view all recommendations/i }));

  expect(onReviewFullAnalysis).toHaveBeenCalledOnce();
  expect(onViewAllRecommendations).toHaveBeenCalledOnce();
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
