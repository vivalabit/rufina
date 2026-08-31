import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import {
  getJobSourceLabel,
  JobMatchRing,
  JobRoleIcon,
} from "@/components/job-visuals";
import { demoJobs } from "@/features/jobs/model/demo-jobs";
import type { Job } from "@/shared/types/job";

it("renders the inferred role, source badge, and static match score", () => {
  const job = demoJobs[0];

  render(
    <>
      <JobRoleIcon job={job} />
      <JobMatchRing job={job} />
    </>,
  );

  expect(
    screen.getByRole("img", { name: "Product Design role · Stripe" }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("92% AI match")).toHaveTextContent("92%");
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
      <JobMatchRing job={manualJob} />
    </>,
  );

  expect(screen.getByAltText("SBB CFF FFS logo")).toBeInTheDocument();
  expect(getJobSourceLabel(directCompanyJob)).toBe("SBB CFF FFS");
  expect(screen.getByLabelText("AI match not scored")).toHaveTextContent("AI");
});
