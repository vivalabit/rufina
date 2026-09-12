import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { aiMatchFixture } from "@/test/ai-match-fixture";
import {
  getJobSourceLabel,
  JobMatchIndicator,
  JobRoleIcon,
} from "@/components/job-visuals";
import { demoJobs } from "@/features/jobs/model/demo-jobs";
import type { Job } from "@/shared/types/job";

it("renders the inferred role, source badge, and static match score", () => {
  const job = demoJobs[0];

  render(
    <>
      <JobRoleIcon job={job} />
      <JobMatchIndicator job={job} />
    </>,
  );

  expect(
    screen.getByRole("img", { name: "Product Design role · Stripe" }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("AI match: 92% · Calculated")).toHaveTextContent("92%");
  expect(getJobSourceLabel(job)).toBe("Stripe");
});

it("uses direct-company metadata and keeps unscored manual jobs explicit", () => {
  const directCompanyJob: Job = {
    ...demoJobs[0],
    id: "sbb-vacancy-1",
    company: "SBB CFF FFS",
    logo: "company",
  };
  const manualJob: Job = {
    ...demoJobs[0],
    id: "manual-job-vacancy-1",
    logo: "manual",
  };

  render(
    <>
      <JobRoleIcon job={directCompanyJob} compact />
      <JobMatchIndicator job={manualJob} />
    </>,
  );

  expect(screen.getByAltText("SBB CFF FFS logo")).toBeInTheDocument();
  expect(getJobSourceLabel(directCompanyJob)).toBe("SBB CFF FFS");
  expect(screen.getByLabelText("AI match: — · Not calculated")).toHaveTextContent("—");
});

it("shows calculating, outdated, error, and zero-score states distinctly", () => {
  const currentJob: Job = {
    ...demoJobs[0],
    aiMatch: { ...aiMatchFixture, score: 0 },
  };
  const outdatedJob: Job = {
    ...demoJobs[0],
    aiMatch: { ...aiMatchFixture, version: "ai-match-v5" },
  };

  render(
    <>
      <JobMatchIndicator job={currentJob} />
      <JobMatchIndicator job={currentJob} isCalculating />
      <JobMatchIndicator job={outdatedJob} />
      <JobMatchIndicator job={currentJob} isError />
    </>,
  );

  expect(screen.getByLabelText("AI match: 0% · Calculated")).toBeInTheDocument();
  expect(screen.getByLabelText("AI match: — · Calculating")).toBeInTheDocument();
  expect(screen.getByLabelText("AI match: 82% · Outdated")).toBeInTheDocument();
  expect(screen.getByLabelText("AI match: — · Error")).toBeInTheDocument();
});
