import { aiMatchFixture } from "@/test/ai-match-fixture";
import { describe, expect, it } from "vitest";

import {
  formatMatchValue,
  getDisplayMatch,
} from "@/features/jobs/model/ai-match";
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
    match: 82,
    logo: "linkedin",
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

describe("job AI-match selectors", () => {
  it("does not display static scores for imported or manual jobs", () => {
    expect(formatMatchValue(job())).toBe("Not scored");
    expect(getDisplayMatch(job({ id: "manual-job-1", logo: "manual" }))).toBe(0);
  });

  it("displays authoritative backend scores", () => {
    const matchedJob = job({
      aiMatch: {
        ...aiMatchFixture,
        version: "ai-match-v5",
        cacheKey: "cache",
        source: "openai_api",
        score: 82,
      },
    });

    expect(formatMatchValue(matchedJob)).toBe("82%");
  });

  it("uses the match score when the legacy job score differs", () => {
    const matchedJob = job({ match: 10, aiMatch: aiMatchFixture });
    expect(formatMatchValue(matchedJob)).toBe("82%");
    expect(getDisplayMatch(matchedJob)).toBe(82);
  });
});
