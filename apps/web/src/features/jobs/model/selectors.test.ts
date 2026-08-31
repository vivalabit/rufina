import { describe, expect, it } from "vitest";

import { defaultJobFilters } from "@/features/jobs/model/constants";
import {
  getBulkAnalysisCandidates,
  matchesJobFilters,
  parseSalaryAmount,
  selectAvailableJobs,
  selectFilteredJobs,
} from "@/features/jobs/model/selectors";
import type { Job } from "@/shared/types/job";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "linkedin-job-1",
    company: "Example",
    title: "Engineer",
    location: "Zurich, Switzerland",
    type: "Full-time",
    salary: "CHF 110k - 130k",
    posted: "2h ago",
    experience: "Senior",
    department: "Engineering",
    match: 50,
    logo: "linkedin",
    overview: "Hybrid engineering role",
    responsibilities: [],
    requirements: [],
    skills: [],
    salaryAverage: "CHF 120k",
    salaryMin: "CHF 110k",
    salaryMax: "CHF 130k",
    recommendations: [],
    companyInfo: "",
    reviews: [],
    similarJobs: [],
    ...overrides,
  };
}

describe("job selectors", () => {
  it("normalizes salary values with a thousands suffix", () => {
    expect(parseSalaryAmount("CHF 110k - 130k")).toBe(130_000);
    expect(parseSalaryAmount("N/A")).toBe(0);
  });

  it("projects archived and deleted jobs without mutating the source", () => {
    const source = [job({ id: "one" }), job({ id: "two" })];
    const result = selectAvailableJobs(source, ["one"], ["two"]);

    expect(result).toEqual([{ ...source[0], archived: true }]);
    expect(source[0].archived).toBeUndefined();
  });

  it("filters by salary, experience, and work format", () => {
    expect(
      matchesJobFilters(job(), {
        ...defaultJobFilters,
        remote: "hybrid",
        salary: "120000",
        experience: "senior",
      }),
    ).toBe(true);
  });

  it("uses a fixed clock for recent bulk-analysis candidates", () => {
    const nowMs = Date.parse("2026-08-31T12:00:00.000Z");
    const recent = job({
      id: "recent",
      addedAt: "2026-08-31T11:00:00.000Z",
    });
    const old = job({ id: "old", addedAt: "2026-08-29T11:00:00.000Z" });

    expect(getBulkAnalysisCandidates([recent, old], "recent", nowMs)).toEqual([
      recent,
    ]);
  });

  it("searches and sorts with a fixed clock", () => {
    const nowMs = Date.parse("2026-08-31T12:00:00.000Z");
    const older = job({ id: "older", title: "React Engineer", posted: "2d ago" });
    const newer = job({ id: "newer", title: "React Lead", posted: "1h ago" });

    expect(
      selectFilteredJobs({
        jobs: [older, newer],
        filters: defaultJobFilters,
        query: "react",
        savedJobIds: [],
        showArchivedJobs: false,
        showSavedJobs: false,
        sortBy: "Time",
        nowMs,
      }).map((item) => item.id),
    ).toEqual(["newer", "older"]);
  });
});
