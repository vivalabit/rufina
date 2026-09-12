import { aiMatchFixture } from "@/test/ai-match-fixture";
import { describe, expect, it } from "vitest";

import {
  formatMatchValue,
  getAiMatchPresentation,
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
    expect(formatMatchValue(job())).toBe("Not calculated");
    expect(getDisplayMatch(job({ id: "manual-job-1", logo: "manual" }))).toBeNull();
  });

  it("displays authoritative backend scores", () => {
    const matchedJob = job({
      aiMatch: {
        ...aiMatchFixture,
        version: "ai-match-v6",
        cacheKey: "c".repeat(64),
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

  it("distinguishes failed, missing, and zero scores", () => {
    const zeroScore = job({
      match: 0,
      aiMatch: { ...aiMatchFixture, score: 0 },
    });
    const failed = job({
      match: 0,
      aiMatch: {
        ...aiMatchFixture,
        score: 0,
        providerError: "Provider timed out",
      },
    });

    expect(formatMatchValue(zeroScore)).toBe("0%");
    expect(getDisplayMatch(zeroScore)).toBe(0);
    expect(formatMatchValue(failed)).toBe("Error");
    expect(getDisplayMatch(failed)).toBeNull();
    expect(formatMatchValue(job())).toBe("Not calculated");
  });

  it("presents current, calculating, outdated, failed, and missing states", () => {
    const current = job({ aiMatch: aiMatchFixture });
    const outdated = job({
      aiMatch: { ...aiMatchFixture, version: "ai-match-v5" },
    });
    const failed = job({
      aiMatch: { ...aiMatchFixture, providerError: "Provider timed out" },
    });

    expect(getAiMatchPresentation(current)).toEqual({
      state: "current",
      label: "Calculated",
      score: 82,
    });
    expect(getAiMatchPresentation(current, { isCalculating: true })).toEqual({
      state: "calculating",
      label: "Calculating",
      score: null,
    });
    expect(getAiMatchPresentation(outdated)).toEqual({
      state: "outdated",
      label: "Outdated",
      score: 82,
    });
    expect(getAiMatchPresentation(failed)).toEqual({
      state: "failed",
      label: "Error",
      score: null,
    });
    expect(getAiMatchPresentation(job())).toEqual({
      state: "missing",
      label: "Not calculated",
      score: null,
    });
  });
});
