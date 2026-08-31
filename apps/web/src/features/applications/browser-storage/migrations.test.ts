import { describe, expect, it, vi } from "vitest";

import type { ApplicationDocument } from "@/shared/types/application";

import {
  extractLegacyApplicationDocuments,
  migrateLegacyApplicationDocuments,
} from "./migrations";

function legacyDocument(
  overrides: Partial<ApplicationDocument> = {},
): ApplicationDocument {
  return {
    id: "legacy-document-id",
    kind: "uploaded",
    title: "Legacy resume",
    fileName: "resume.pdf",
    fileSize: "1 KB",
    fileType: "application/pdf",
    uploadedAt: "2026-08-01T10:00:00.000Z",
    downloadUrl: "",
    legacyDataUrl: "data:application/pdf;base64,QQ==",
    ...overrides,
  };
}

describe("application browser-storage migrations", () => {
  it("extracts only inline documents from non-demo applications", () => {
    const extracted = extractLegacyApplicationDocuments([
      {
        id: "application-user",
        documents: [
          {
            title: "Resume",
            data_url: "data:application/pdf;base64,QQ==",
          },
          {
            title: "Stored file",
            file_name: "stored.pdf",
            downloadUrl: "/stored.pdf",
          },
        ],
      },
      {
        id: "application-stripe-senior-product-designer",
        documents: [{ dataUrl: "data:application/pdf;base64,QQ==" }],
      },
      { id: "", documents: [] },
    ]);

    expect(Array.from(extracted.keys())).toEqual(["application-user"]);
    expect(extracted.get("application-user")).toEqual([
      expect.objectContaining({
        id: "legacy-application-document-1",
        fileName: "legacy-document-1.pdf",
      }),
    ]);
  });

  it("uploads sequentially with stable metadata and retains empty map entries", async () => {
    const order: string[] = [];
    const first = legacyDocument({ id: "first", fileName: "first.pdf" });
    const second = legacyDocument({ id: "second", fileName: "second.pdf" });
    const uploadAttachment = vi.fn(
      async (
        applicationId: string,
        _blob: Blob,
        metadata: { fileName: string; legacyDocumentId?: string },
      ) => {
        order.push(metadata.fileName);
        return legacyDocument({
          id: `uploaded-${metadata.legacyDocumentId}`,
          legacyDataUrl: undefined,
          downloadUrl: `/applications/${applicationId}/${metadata.fileName}`,
        });
      },
    );

    const result = await migrateLegacyApplicationDocuments(
      new Map([
        ["application-1", [first, second]],
        ["application-empty", [legacyDocument({ legacyDataUrl: undefined })]],
      ]),
      { uploadAttachment, isPermanentUploadError: () => false },
    );

    expect(order).toEqual(["first.pdf", "second.pdf"]);
    expect(uploadAttachment).toHaveBeenNthCalledWith(
      1,
      "application-1",
      expect.any(Blob),
      {
        fileName: "first.pdf",
        title: "Legacy resume",
        legacyDocumentId: "first",
      },
    );
    expect(result.documents.get("application-1")).toHaveLength(2);
    expect(result.documents.get("application-empty")).toEqual([]);
  });

  it("scrubs malformed and permanent failures but rethrows transient errors", async () => {
    const permanentError = new Error("unsupported");
    const transientError = new Error("offline");
    const malformed = legacyDocument({
      fileName: "malformed.pdf",
      legacyDataUrl: "data:invalid",
    });
    const unsupported = legacyDocument({ fileName: "unsafe.svg" });

    const permanentResult = await migrateLegacyApplicationDocuments(
      new Map([["application-1", [malformed, unsupported]]]),
      {
        uploadAttachment: async () => {
          throw permanentError;
        },
        isPermanentUploadError: (error) => error === permanentError,
      },
    );

    expect(permanentResult.documents.get("application-1")).toEqual([]);
    expect(permanentResult.warnings).toEqual([
      "Malformed legacy application document malformed.pdf was removed.",
      "Legacy application document unsafe.svg was removed because it is not a safe supported file.",
    ]);

    await expect(
      migrateLegacyApplicationDocuments(
        new Map([["application-1", [unsupported]]]),
        {
          uploadAttachment: async () => {
            throw transientError;
          },
          isPermanentUploadError: () => false,
        },
      ),
    ).rejects.toBe(transientError);
  });
});
