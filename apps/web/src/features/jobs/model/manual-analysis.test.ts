import { describe, expect, it, vi } from "vitest";

import {
  analyzeManualJobDescription,
  createManualJobFromDraft,
} from "@/features/jobs/model/manual-analysis";
import type { ManualJobDraft } from "@/features/jobs/model/types";

const draft: ManualJobDraft = {
  title: "Senior TypeScript Engineer",
  company: " Example AG ",
  location: " Zurich ",
  applyUrl: "example.com/jobs/42",
  overview:
    "Full-time role. You will build React applications and collaborate with stakeholders. You must have 5+ years of TypeScript experience and fluent English.",
};

describe("manual job analysis", () => {
  it("derives vacancy fields from the description", () => {
    const analysis = analyzeManualJobDescription(draft);

    expect(analysis.type).toBe("Full-time");
    expect(analysis.experience).toBe("Senior");
    expect(analysis.skills).toEqual(
      expect.arrayContaining(["TypeScript", "React", "Communication", "English"]),
    );
    expect(analysis.responsibilities).toContain(
      "You will build React applications and collaborate with stakeholders",
    );
  });

  it("uses injected identity and time providers", () => {
    const createId = vi.fn(() => "manual-job-fixed");
    const job = createManualJobFromDraft(draft, {
      createId,
      now: () => "2026-08-31T12:00:00.000Z",
    });

    expect(createId).toHaveBeenCalledWith("manual-job");
    expect(job).toMatchObject({
      id: "manual-job-fixed",
      company: "Example AG",
      location: "Zurich",
      applyUrl: "https://example.com/jobs/42",
      sourceUrl: "https://example.com/jobs/42",
      addedAt: "2026-08-31T12:00:00.000Z",
      logo: "manual",
      match: 50,
    });
  });
});
