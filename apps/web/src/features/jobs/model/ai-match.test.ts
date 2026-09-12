import { describe, expect, it } from "vitest";

import {
  buildRecommendationPlan,
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
        version: "ai-match-v4",
        cacheKey: "cache",
        source: "openai_api",
        score: 82,
        confidence: "high",
        breakdown: {},
        reasons: [],
        gaps: [],
      },
    });

    expect(formatMatchValue(matchedJob)).toBe("82%");
  });

  it("keeps stored job recommendations independent from match analysis", () => {
    const matchedJob = job({
      recommendations: [
        {
          text: "Emphasize the platform example",
          gain: "+4%",
        },
      ],
      aiMatch: {
        version: "ai-match-v4",
        cacheKey: "cache",
        source: "openai_api",
        score: 82,
        confidence: "high",
        breakdown: {},
        reasons: [],
        gaps: [],
      },
    });

    expect(buildRecommendationPlan(matchedJob)).toEqual([
      { text: "Emphasize the platform example", gain: "+4%" },
    ]);
  });
});
