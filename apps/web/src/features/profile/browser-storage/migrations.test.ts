import { describe, expect, it, vi } from "vitest";

import type { ProfileFilePayload } from "../api/dto";
import { profileStorageKey } from "./keys";
import {
  hasLegacyProfileInlineFiles,
  migrateLegacyProfileFiles,
  readLegacyStoredCandidateProfile,
  type LegacyProfileFileUploader,
} from "./migrations";

function profileFile(
  kind: ProfileFilePayload["kind"],
  overrides: Partial<ProfileFilePayload> = {},
): ProfileFilePayload {
  return {
    id: `${kind}-id`,
    kind,
    title: "Stored file",
    category: "Other",
    language: "",
    issuer: "",
    notes: "",
    fileName: "stored-file.bin",
    sizeBytes: 4,
    contentType: "application/octet-stream",
    contentSha256: "",
    createdAt: "2026-08-31T10:00:00Z",
    updatedAt: "2026-08-31T10:00:00Z",
    downloadUrl: "/profile/files/stored-file",
    ...overrides,
  };
}

function successfulUploader(): LegacyProfileFileUploader {
  return async (_file, metadata) => profileFile(metadata.kind, {
    fileName: metadata.fileName,
  });
}

describe("profile browser-storage migrations", () => {
  it("reads an object from the legacy key and removes malformed JSON", () => {
    window.localStorage.setItem(
      profileStorageKey,
      JSON.stringify({ name: "Legacy candidate", resumeDataUrl: "data:text/plain,cv" }),
    );

    expect(readLegacyStoredCandidateProfile(window.localStorage)).toMatchObject({
      name: "Legacy candidate",
      resumeDataUrl: "data:text/plain,cv",
    });

    window.localStorage.setItem(profileStorageKey, "{malformed");

    expect(readLegacyStoredCandidateProfile(window.localStorage)).toBeNull();
    expect(window.localStorage.getItem(profileStorageKey)).toBeNull();
  });

  it("detects inline files and routes malformed document metadata through migration", () => {
    expect(hasLegacyProfileInlineFiles({ resume_data_url: "data:text/plain,cv" }))
      .toBe(true);
    expect(hasLegacyProfileInlineFiles({ avatar_url: "data:image/png,avatar" }))
      .toBe(true);
    expect(hasLegacyProfileInlineFiles({
      documents: JSON.stringify([{ dataUrl: "data:application/pdf,document" }]),
    })).toBe(true);
    expect(hasLegacyProfileInlineFiles({ documents: "{malformed" })).toBe(true);
    expect(hasLegacyProfileInlineFiles({ documents: "[]" })).toBe(false);
  });

  it("warns about malformed document metadata without uploading", async () => {
    const uploadFile = vi.fn(successfulUploader());

    const warnings = await migrateLegacyProfileFiles(
      { documents: "{malformed" },
      [],
      { uploadFile, isPermanentUploadError: () => false },
    );

    expect(warnings).toEqual([
      "Malformed legacy profile document metadata was removed.",
    ]);
    expect(uploadFile).not.toHaveBeenCalled();
  });

  it("accepts GIF avatars and preserves their extension", async () => {
    const uploadFile = vi.fn(successfulUploader());

    const warnings = await migrateLegacyProfileFiles(
      { avatar_url: "data:image/gif;base64,R0lGODlh" },
      [],
      { uploadFile, isPermanentUploadError: () => false },
    );

    expect(warnings).toEqual([]);
    expect(uploadFile).toHaveBeenCalledTimes(1);
    expect(uploadFile.mock.calls[0]?.[0].type).toBe("image/gif");
    expect(uploadFile.mock.calls[0]?.[1]).toEqual({
      kind: "avatar",
      fileName: "avatar.gif",
      title: "Profile avatar",
      category: "Avatar",
      legacyDocumentId: undefined,
      replaceExisting: false,
    });
  });

  it("rejects legacy SVG avatars before upload", async () => {
    const uploadFile = vi.fn(successfulUploader());

    const warnings = await migrateLegacyProfileFiles(
      { avatar_url: "data:image/svg+xml,%3Csvg%3E%3C/svg%3E" },
      [],
      { uploadFile, isPermanentUploadError: () => false },
    );

    expect(warnings).toEqual([
      "Unsupported legacy avatar type image/svg+xml was removed.",
    ]);
    expect(uploadFile).not.toHaveBeenCalled();
  });

  it("does not upload files whose SHA-256 already matches server singletons", async () => {
    const digestBytes = new Uint8Array(32).fill(0xab);
    const digest = digestBytes.buffer as ArrayBuffer;
    const subtle = {
      digest: vi.fn(async () => digest),
    };
    vi.stubGlobal("crypto", { subtle });
    vi.spyOn(Blob.prototype, "arrayBuffer").mockResolvedValue(
      new TextEncoder().encode("same-content").buffer as ArrayBuffer,
    );
    const uploadFile = vi.fn(successfulUploader());
    const existingFiles = [
      profileFile("primary_resume", { contentSha256: "AB".repeat(32) }),
      profileFile("avatar", { contentSha256: "ab".repeat(32) }),
    ];

    await migrateLegacyProfileFiles(
      {
        resume_data_url: "data:application/pdf,same-content",
        avatar_url: "data:image/png,same-content",
      },
      existingFiles,
      { uploadFile, isPermanentUploadError: () => false },
    );

    expect(subtle.digest).toHaveBeenCalledTimes(2);
    expect(uploadFile).not.toHaveBeenCalled();
  });

  it("keeps existing resume and avatar singletons by uploading differences as documents", async () => {
    vi.stubGlobal("crypto", {});
    const uploadFile = vi.fn(successfulUploader());
    const existingFiles = [
      profileFile("primary_resume"),
      profileFile("avatar"),
    ];

    await migrateLegacyProfileFiles(
      {
        resume_data_url: "data:application/pdf,new-resume",
        resume_file_name: "candidate.pdf",
        avatar_url: "data:image/webp,new-avatar",
      },
      existingFiles,
      { uploadFile, isPermanentUploadError: () => false },
    );

    expect(uploadFile.mock.calls.map((call) => call[1])).toEqual([
      {
        kind: "supporting_document",
        fileName: "candidate.pdf",
        title: "Legacy resume · candidate.pdf",
        category: "CV / Resume",
        legacyDocumentId: "legacy-primary-resume",
        replaceExisting: false,
      },
      {
        kind: "supporting_document",
        fileName: "avatar.webp",
        title: "Legacy profile avatar",
        category: "Other",
        legacyDocumentId: "legacy-profile-avatar",
        replaceExisting: false,
      },
    ]);
  });

  it("continues sequential documents after permanent errors and keeps stable fallback IDs", async () => {
    const permanentError = new Error("unsupported");
    const uploadOrder: string[] = [];
    const uploader: LegacyProfileFileUploader = async (_file, metadata) => {
      uploadOrder.push(metadata.fileName);
      if (metadata.fileName === "first.txt") throw permanentError;
      return profileFile(metadata.kind, { fileName: metadata.fileName });
    };
    const uploadFile = vi.fn(uploader);

    const warnings = await migrateLegacyProfileFiles(
      {
        documents: [
          { file_name: "first.txt", data_url: "data:text/plain,first" },
          { file_name: "second.txt", data_url: "data:text/plain,second" },
        ],
      },
      [],
      {
        uploadFile,
        isPermanentUploadError: (error) => error === permanentError,
      },
    );

    expect(uploadOrder).toEqual(["first.txt", "second.txt"]);
    expect(warnings).toEqual([
      "Legacy profile document first.txt was removed because it is not a safe supported file.",
    ]);
    expect(uploadFile.mock.calls.map((call) => call[1].legacyDocumentId)).toEqual([
      "legacy-profile-document-1",
      "legacy-profile-document-2",
    ]);
  });
});
