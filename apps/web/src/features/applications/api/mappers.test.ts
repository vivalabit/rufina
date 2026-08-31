import { describe, expect, it } from "vitest";

import type { ApplicationEvent } from "@/shared/types/application";

import {
  applicationEventToApiPayload,
  generatedDocumentToApplicationDocument,
  workspaceSourceToApplicationDocument,
} from "./mappers";

describe("application API mappers", () => {
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
        "http://localhost:8000",
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
