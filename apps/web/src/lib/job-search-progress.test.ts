import { expect, it } from "vitest";

import { getJobSearchProgress } from "@/lib/job-search-progress";

const runningSearch = {
  jobsFound: 0,
  jobsAlreadyKnown: 0,
  jobsScreened: 0,
  jobsAdded: 0,
  jobsAnalyzed: 0,
  completedAt: null,
};

it("describes every long-running vacancy search stage", () => {
  expect(
    getJobSearchProgress(runningSearch, "LinkedIn", 12.8, true),
  ).toMatchObject({
    phase: "parsing",
    message: "Waiting for LinkedIn parser... (12s elapsed)",
  });
  expect(
    getJobSearchProgress(
      { ...runningSearch, jobsFound: 50, jobsAlreadyKnown: 1, jobsScreened: 20 },
      "LinkedIn",
      220,
      true,
    ),
  ).toMatchObject({
    phase: "screening",
    message: "LinkedIn: screening 20 of 49 vacancies...",
    screeningTotal: 49,
  });
  expect(
    getJobSearchProgress(
      {
        ...runningSearch,
        jobsFound: 50,
        jobsAlreadyKnown: 1,
        jobsScreened: 49,
        jobsAdded: 18,
        jobsAnalyzed: 8,
      },
      "LinkedIn",
      300,
      true,
    ),
  ).toMatchObject({
    phase: "matching",
    message: "LinkedIn: AI Match 8 of 18 vacancies...",
  });
  expect(
    getJobSearchProgress(
      {
        ...runningSearch,
        jobsFound: 50,
        jobsAlreadyKnown: 1,
        jobsScreened: 49,
        jobsAdded: 18,
      },
      "LinkedIn",
      300,
      false,
    ),
  ).toMatchObject({
    phase: "finalizing",
    message: "LinkedIn: finalizing results...",
  });
});
