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
      language: "English",
      formatting: {
        pageSize: "A4",
        resumeTemplateId: "moderncv_banking",
        resumeMaxPages: 2,
        coverLetterTemplateId: "letter-template",
      },
      submission: {
        tailored_resume: { documentId: "stored-resume", version: 3 },
        cover_letter: null,
      },
      latestGeneration: null,
      userPreferences: "Keep the letter concise.",
    });
  });

  it.each(["classic_single", "modern_single", "modern_two_column", "unknown", "", null])(
    "keeps the existing Banking layout for legacy or unsupported template %s",
    (resumeTemplateId) => {
      expect(normalizeDocumentPreparationSettings({
        formatting: { resumeTemplateId },
      }).formatting.resumeTemplateId).toBe("moderncv_banking");
    },
  );

  it("restores the selected generation template", () => {
    expect(normalizeDocumentPreparationSettings({
      formatting: { resumeTemplateId: " ishchenko_classic " },
    }).formatting.resumeTemplateId).toBe("ishchenko_classic");
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
        resumeTemplateId: "ishchenko_classic",
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
          templateId: "ishchenko_classic",
          maxPages: 1,
        },
      },
      userPreferences: "Keep it concise.",
    });
  });
});
