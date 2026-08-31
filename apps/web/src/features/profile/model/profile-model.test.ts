import { describe, expect, it } from "vitest";

import { defaultCandidateProfile, defaultJobPreferences } from "./defaults";
import {
  parseDocumentEntries,
  parseExperienceEntries,
  serializeDocumentEntries,
} from "./entries";
import {
  formatPreferenceSummary,
  normalizeJobPreferences,
} from "./preferences";
import { getProfileCompletionItems } from "./selectors";

const createId = (prefix: string) => `${prefix}-generated`;

describe("profile entries", () => {
  it("normalizes structured experience with an injected id factory", () => {
    const entries = parseExperienceEntries(
      JSON.stringify([{ title: " Backend Engineer ", company: " Example AG " }]),
      createId,
    );

    expect(entries).toEqual([
      expect.objectContaining({
        id: "experience-generated",
        title: "Backend Engineer",
        company: "Example AG",
      }),
    ]);
  });

  it("keeps legacy document ids deterministic and omits pending files", () => {
    const entries = parseDocumentEntries(
      JSON.stringify([{ title: "Certificate", file_name: "certificate.pdf" }]),
      createId,
    );

    expect(entries[0]?.id).toBe("legacy-document-0");
    entries[0].pending_file = new File(["content"], "certificate.pdf");
    expect(JSON.parse(serializeDocumentEntries(entries, createId))).toEqual([
      expect.not.objectContaining({ pending_file: expect.anything() }),
    ]);
  });
});

describe("profile preferences and completion", () => {
  it("deduplicates preferences and preserves Swiss permit details", () => {
    const preferences = normalizeJobPreferences({
      desired_roles: ["Engineer", " engineer ", "Developer"],
      work_authorization: "Swiss permit",
      swiss_permit_status: " B permit ",
    });

    expect(preferences.desired_roles).toEqual(["engineer", "Developer"]);
    expect(preferences.swiss_permit_status).toBe("B permit");
    expect(formatPreferenceSummary(preferences)).toContainEqual({
      label: "Authorization",
      values: ["Swiss permit (B permit)"],
    });
  });

  it("treats a safe external profile URL as a completed contact link", () => {
    const profile = {
      ...defaultCandidateProfile,
      linkedin: "linkedin.com/in/candidate",
      job_preferences: JSON.stringify(defaultJobPreferences),
    };

    const contactItem = getProfileCompletionItems(profile, createId)
      .find((item) => item.label === "Contact link");

    expect(contactItem?.complete).toBe(true);
  });
});
