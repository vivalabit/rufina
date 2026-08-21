import { describe, expect, it } from "vitest";

import { normalizeJobsChJobUrl } from "@/lib/job-url";

describe("normalizeJobsChJobUrl", () => {
  it.each([
    [
      "https://www.jobs.ch/en/vacancies/detail/vac-1/apply",
      "https://www.jobs.ch/en/vacancies/detail/vac-1/",
    ],
    [
      "https://www.jobs.ch/en/vacancies/detail/vac-1/apply/",
      "https://www.jobs.ch/en/vacancies/detail/vac-1/",
    ],
    [
      "https://jobs.ch/en/vacancies/detail/vac-1/apply?source=test#form",
      "https://jobs.ch/en/vacancies/detail/vac-1/?source=test#form",
    ],
  ])("removes a terminal apply route from %s", (value, expected) => {
    expect(normalizeJobsChJobUrl(value)).toBe(expected);
  });

  it("does not change apply routes on employer websites", () => {
    const value = "https://employer.example/jobs/vac-1/apply";
    expect(normalizeJobsChJobUrl(value)).toBe(value);
  });
});
