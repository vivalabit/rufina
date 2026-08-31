import { describe, expect, it } from "vitest";

import {
  normalizeStoredJobIds,
  normalizeStoredJobs,
} from "@/features/jobs/browser-storage/normalizers";
import type { Job } from "@/shared/types/job";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "linkedin-job-1",
    company: "Example",
    title: "Engineer",
    location: "Zurich",
    type: "Full-time",
    salary: "N/A",
    posted: "1h ago",
    experience: "Mid-level",
    department: "Engineering",
    match: 50,
    logo: "manual",
    overview: "",
    responsibilities: [],
    requirements: [],
    skills: [],
    salaryAverage: "N/A",
    salaryMin: "N/A",
    salaryMax: "N/A",
    recommendations: [],
    companyInfo: "",
    reviews: [],
    similarJobs: [],
    ...overrides,
  };
}

describe("stored job normalization", () => {
  it("rejects incomplete values and normalizes source logos", () => {
    const [linkedInJob, directCompanyJob] = normalizeStoredJobs([
      { title: "Incomplete" },
      job(),
      job({ id: "sbb-job-42" }),
    ]);

    expect(linkedInJob.logo).toBe("linkedin");
    expect(directCompanyJob.logo).toBe("company");
  });

  it("sanitizes unsupported local AI metadata", () => {
    const [normalized] = normalizeStoredJobs([
      job({
        aiMatch: {
          version: "ai-match-v2",
          cacheKey: "legacy",
          source: "local",
          score: 91,
          confidence: "medium",
          breakdown: {},
          reasons: [],
          gaps: [],
        },
      }),
    ]);

    expect(normalized.aiMatch).toBeUndefined();
    expect(normalized.match).toBe(50);
    expect(normalized.archived).toBe(false);
  });

  it("deduplicates valid stored IDs without trimming their values", () => {
    expect(normalizeStoredJobIds(["one", "one", " two ", "", null])).toEqual([
      "one",
      " two ",
    ]);
  });
});
