import { describe, expect, it } from "vitest";

import {
  defaultDocumentPreparationSettings,
  generationRequestFromSettings,
  normalizeDocumentPreparationSettings,
} from "./document-preparation";

describe("document preparation settings", () => {
  it("provides a complete default document pack", () => {
    expect(normalizeDocumentPreparationSettings(undefined)).toEqual(
      defaultDocumentPreparationSettings,
    );
  });

  it("keeps only supported persisted values", () => {
    expect(
      normalizeDocumentPreparationSettings({
        documentTypes: ["cover_letter", "unknown", "cover_letter"],
        language: "French",
        formatting: {
          pageSize: "Legal",
          resumeTemplateId: " modern_single ",
          resumeMaxPages: 12,
          coverLetterTemplateId: "letter-template",
        },
        userPreferences: "Keep the letter concise.",
      }),
    ).toEqual({
      documentTypes: ["cover_letter"],
      language: "English",
      formatting: {
        pageSize: "A4",
        resumeTemplateId: "modern_single",
        resumeMaxPages: 2,
        coverLetterTemplateId: "letter-template",
      },
      userPreferences: "Keep the letter concise.",
    });
  });

  it("sends formatting only for selected document types", () => {
    const request = generationRequestFromSettings({
      ...defaultDocumentPreparationSettings,
      documentTypes: ["tailored_resume"],
      language: "German",
      formatting: {
        pageSize: "Letter",
        resumeTemplateId: "modern_single",
        resumeMaxPages: 1,
        coverLetterTemplateId: "unused-template",
      },
      userPreferences: "  Keep it concise.  ",
    });

    expect(request).toEqual({
      documentTypes: ["tailored_resume"],
      language: "German",
      formattingParameters: {
        tailored_resume: {
          pageSize: "Letter",
          templateId: "modern_single",
          maxPages: 1,
        },
      },
      userPreferences: "Keep it concise.",
    });
  });
});
