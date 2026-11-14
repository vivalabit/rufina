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
        submission: {
          tailored_resume: {
            documentId: " stored-resume ",
            version: 3,
          },
          cover_letter: {
            documentId: "",
            version: -1,
          },
        },
        userPreferences: "Keep the letter concise.",
      }),
    ).toEqual({
      documentTypes: ["cover_letter"],
      language: "Auto",
      languageChoice: "Auto",
      formatting: {
        pageSize: "A4",
        resumeTemplateId: "modern_single",
        resumeMaxPages: "auto",
        coverLetterTemplateId: "modern_single",
      },
      submission: {
        tailored_resume: { documentId: "stored-resume", version: 3 },
        cover_letter: null,
      },
      latestGeneration: null,
      userPreferences: "Keep the letter concise.",
    });
  });

  it.each([
    "swiss_classic",
    "classic_single",
    "modern_single",
    "swiss_local_german",
    "modern_two_column",
  ])("restores the gallery template %s", (resumeTemplateId) => {
    expect(normalizeDocumentPreparationSettings({
      formatting: { resumeTemplateId: ` ${resumeTemplateId} ` },
    }).formatting.resumeTemplateId).toBe(resumeTemplateId);
  });

  it.each(["unknown", "", null])(
    "falls back to the default template for unsupported value %s",
    (resumeTemplateId) => {
      expect(normalizeDocumentPreparationSettings({
        formatting: { resumeTemplateId },
      }).formatting.resumeTemplateId).toBe("swiss_classic");
    },
  );

  it.each([
    ["roman", "swiss_classic"],
    ["ishchenko_classic", "swiss_classic"],
    ["moderncv_banking", "modern_single"],
  ])("maps the earlier generator template %s to %s", (saved, expected) => {
    expect(normalizeDocumentPreparationSettings({
      formatting: { resumeTemplateId: saved },
    }).formatting.resumeTemplateId).toBe(expected);
  });

  it("normalizes old mismatched settings and cannot send different document styles", () => {
    const settings = {
      ...defaultDocumentPreparationSettings,
      formatting: {
        ...defaultDocumentPreparationSettings.formatting,
        resumeTemplateId: "classic_single",
        coverLetterTemplateId: "modern_single",
      },
    };
    expect(normalizeDocumentPreparationSettings(settings).formatting).toMatchObject({
      resumeTemplateId: "classic_single", coverLetterTemplateId: "classic_single",
    });
    const request = generationRequestFromSettings(settings);
    expect(request.formattingParameters.tailored_resume.templateId).toBe("classic_single");
    expect(request.formattingParameters.cover_letter.templateId).toBe("classic_single");
  });

  it("ignores a language saved by earlier versions and follows the explicit choice", () => {
    expect(normalizeDocumentPreparationSettings({ language: "German" }).languageChoice).toBe("Auto");
    expect(generationRequestFromSettings({
      ...defaultDocumentPreparationSettings,
      language: "German",
    }).language).toBe("Auto");
    expect(generationRequestFromSettings({
      ...defaultDocumentPreparationSettings,
      languageChoice: "German",
    }).language).toBe("German");
  });

  it("restores a valid per-document generation result", () => {
    const latestGeneration = {
      executionId: "generation-12",
      state: "completed" as const,
      documentResults: [
        {
          documentType: "tailored_resume" as const,
          state: "completed" as const,
          files: [
            {
              fileName: "tailored-cv.pdf",
              contentType: "application/pdf",
              downloadUrl: "/generated/tailored-cv.pdf",
            },
          ],
          error: null,
        },
        {
          documentType: "cover_letter" as const,
          state: "failed" as const,
          files: [],
          error: {
            code: "render_failed",
            message: "The cover letter could not be rendered.",
            retryable: true,
          },
        },
      ],
      error: null,
    };

    expect(normalizeDocumentPreparationSettings({ latestGeneration }))
      .toEqual(expect.objectContaining({ latestGeneration }));
    expect(normalizeDocumentPreparationSettings({
      latestGeneration: {
        ...latestGeneration,
        documentResults: [{
          documentType: "cover_letter",
          state: "completed",
          files: [],
          error: null,
        }],
      },
    }).latestGeneration).toBeNull();
  });

  it("sends formatting only for selected document types", () => {
    const request = generationRequestFromSettings({
      ...defaultDocumentPreparationSettings,
      documentTypes: ["tailored_resume"],
      language: "German",
      formatting: {
        pageSize: "Letter",
        resumeTemplateId: "swiss_classic",
        resumeMaxPages: 1,
        coverLetterTemplateId: "unused-template",
      },
      userPreferences: "  Keep it concise.  ",
    });

    expect(request).toEqual({
      documentTypes: ["tailored_resume"],
      language: "Auto",
      formattingParameters: {
        tailored_resume: {
          pageSize: "Letter",
          templateId: "swiss_classic",
          maxPages: 1,
        },
      },
      userPreferences: "Keep it concise.",
    });
  });
});
