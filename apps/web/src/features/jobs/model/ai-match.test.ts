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
        version: "ai-match-v3",
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

  it("builds recommendations only from source-backed evidence", () => {
    const matchedJob = job({
      aiMatch: {
        version: "ai-match-v3",
        cacheKey: "cache",
        source: "openai_api",
        score: 82,
        confidence: "high",
        breakdown: {},
        reasons: [],
        gaps: [],
        applicationGuide: {
          language: "English",
          positioning: "Lead with delivery evidence",
          cvImprovements: [],
          coverLetterStrategy: [],
          risks: [],
          keywords: [],
          applicationQuestions: [],
          finalChecklist: [],
          evidenceMatrix: [
            {
              requirement: "TypeScript",
              importance: "required",
              status: "verified",
              evidence: "Built a platform",
              action: "Use the platform example",
              sources: [{ id: "cv", label: "CV", excerpt: "Built a platform" }],
            },
          ],
        },
      },
    });

    expect(buildRecommendationPlan(matchedJob)).toEqual([
      expect.objectContaining({
        text: "Use the platform example",
        gain: "verified evidence",
      }),
    ]);
  });
});
