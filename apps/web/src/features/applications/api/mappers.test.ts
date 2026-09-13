import { describe, expect, it } from "vitest";

import type { ApplicationEvent } from "@/shared/types/application";

import {
  applicationPayloadForApi,
  applicationEventToApiPayload,
  generatedDocumentToApplicationDocument,
  normalizeStoredApplications,
  workspaceSourceToApplicationDocument,
} from "./mappers";

describe("application API mappers", () => {
  it("normalizes and serializes document preparation settings", () => {
    const [application] = normalizeStoredApplications([{
      id: "application-1",
      status: "draft",
      appliedAt: "2026-09-13T10:00:00.000Z",
      nextStep: "",
      notes: "",
      job: {
        id: "job-1",
        title: "Designer",
        company: "Acme",
        location: "Zurich",
        type: "Full-time",
        salary: "",
        posted: "Today",
        experience: "",
        department: "Design",
        match: 0,
        logo: "company",
        overview: "Design products.",
        responsibilities: [],
        requirements: [],
        skills: [],
      },
      documentPreparation: {
        documentTypes: ["cover_letter"],
        language: "German",
        formatting: {
          pageSize: "A4",
          resumeTemplateId: "modern_single",
          resumeMaxPages: 1,
          coverLetterTemplateId: "standard-letter",
        },
        latestGeneration: {
          executionId: "generation-restored",
          state: "failed",
          documentResults: [{
            documentType: "cover_letter",
            state: "failed",
            files: [],
            error: {
              code: "generator_unavailable",
              message: "Document generation is not configured yet.",
              retryable: false,
            },
          }],
          error: {
            code: "generator_unavailable",
            message: "Document generation is not configured yet.",
            retryable: false,
          },
        },
        userPreferences: "Use a direct tone.",
      },
    }]);

    expect(application.documentPreparation).toMatchObject({
      documentTypes: ["cover_letter"],
      language: "German",
      formatting: { coverLetterTemplateId: "standard-letter" },
      latestGeneration: { executionId: "generation-restored" },
    });
    expect(applicationPayloadForApi(application)).toMatchObject({
      documentPreparation: application.documentPreparation,
    });
  });

  it("maps workspace source metadata and resolves its URL", () => {
    expect(
      workspaceSourceToApplicationDocument({
        id: "source-1",
        applicationId: "application-1",
        category: "Application Attachment",
        title: "Resume",
        language: "English",
        fileName: "resume.pdf",
        fileSize: "",
        sizeBytes: 2048,
        fileType: "application/pdf",
        uploadedAt: "2026-08-31T10:00:00.000Z",
        downloadUrl: "/documents/source-1",
      }),
    ).toMatchObject({
      id: "source-source-1",
      sourceId: "source-1",
      fileSize: "2 KB",
      downloadUrl: "http://localhost:8000/documents/source-1",
    });
  });

  it("maps only the current generated version and encodes the download ID", () => {
    expect(
      generatedDocumentToApplicationDocument(
        {
          id: "document/1",
          title: "Tailored resume",
          type: "tailored_resume",
          currentVersion: 2,
          updatedAt: "2026-08-31T10:00:00.000Z",
          versions: [
            {
              version: 1,
              artifact: {
                fileName: "old.docx",
                contentType: "application/old",
              },
            },
            { version: 2, artifact: null },
          ],
        },
      ),
    ).toMatchObject({
      fileName: "Tailored resume.docx",
      fileType:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      downloadUrl: "http://localhost:8000/documents/document%2F1/download",
    });
  });

  it("wraps events using the API snake-case application key", () => {
    const event: ApplicationEvent = {
      id: "event-1",
      applicationId: "application-1",
      type: "interview",
      status: "scheduled",
      title: "Interview",
      startsAt: "2026-09-01T10:00:00.000Z",
      durationMinutes: 30,
      timezone: "Europe/Zurich",
      location: "Remote",
      notes: "",
    };

    expect(applicationEventToApiPayload(event)).toEqual({
      id: "event-1",
      application_id: "application-1",
      data: event,
    });
  });
});
