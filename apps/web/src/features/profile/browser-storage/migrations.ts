import { decodeDataUrl, isInlineDataUrl } from "@/shared/browser-storage/data-url";
import type { CandidateProfile } from "@/shared/types/profile";

import type { ProfileFilePayload } from "../api/dto";
import { profileStorageKey } from "./keys";

export type LegacyStoredCandidateProfile = Omit<
  Partial<CandidateProfile>,
  "documents"
> & {
  resume_data_url?: string;
  resumeDataUrl?: string;
  documents?: string | unknown[];
};

export type LegacyProfileFileUploadMetadata = {
  kind: ProfileFilePayload["kind"];
  fileName: string;
  title?: string;
  category?: string;
  language?: string;
  issuer?: string;
  notes?: string;
  legacyDocumentId?: string;
  replaceExisting?: boolean;
};

export type LegacyProfileFileUploader = (
  file: Blob,
  metadata: LegacyProfileFileUploadMetadata,
) => Promise<ProfileFilePayload>;

export type LegacyProfileMigrationDependencies = {
  uploadFile: LegacyProfileFileUploader;
  isPermanentUploadError: (error: unknown) => boolean;
};

type LegacyProfileStorage = Pick<Storage, "getItem" | "removeItem">;

export function readLegacyStoredCandidateProfile(
  storage: LegacyProfileStorage,
): LegacyStoredCandidateProfile | null {
  try {
    const rawProfile = storage.getItem(profileStorageKey);
    if (!rawProfile) return null;
    const value = JSON.parse(rawProfile) as unknown;
    return value && typeof value === "object"
      ? value as LegacyStoredCandidateProfile
      : null;
  } catch {
    storage.removeItem(profileStorageKey);
    return null;
  }
}

async function matchesServerFile(
  blob: Blob,
  serverFile: ProfileFilePayload,
): Promise<boolean> {
  if (!globalThis.crypto?.subtle || !serverFile.contentSha256) return false;
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    await blob.arrayBuffer(),
  );
  const hash = Array.from(
    new Uint8Array(digest),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
  return hash === serverFile.contentSha256.toLowerCase();
}

export async function migrateLegacyProfileFiles(
  legacyProfile: LegacyStoredCandidateProfile,
  existingFiles: ProfileFilePayload[],
  dependencies: LegacyProfileMigrationDependencies,
): Promise<string[]> {
  const warnings: string[] = [];
  const serverResume = existingFiles.find((file) => file.kind === "primary_resume");
  const serverAvatar = existingFiles.find((file) => file.kind === "avatar");

  async function uploadLegacyFile(
    blob: Blob,
    metadata: LegacyProfileFileUploadMetadata,
    label: string,
  ): Promise<ProfileFilePayload | null> {
    try {
      return await dependencies.uploadFile(blob, metadata);
    } catch (error) {
      if (dependencies.isPermanentUploadError(error)) {
        warnings.push(
          `${label} was removed because it is not a safe supported file.`,
        );
        return null;
      }
      throw error;
    }
  }

  const legacyResumeDataUrl =
    legacyProfile.resume_data_url ?? legacyProfile.resumeDataUrl;
  if (isInlineDataUrl(legacyResumeDataUrl)) {
    let resumeBlob: Blob | null = null;
    try {
      resumeBlob = decodeDataUrl(legacyResumeDataUrl as string);
    } catch {
      warnings.push("Malformed legacy resume was removed instead of being uploaded.");
    }
    if (
      resumeBlob
      && (!serverResume || !(await matchesServerFile(resumeBlob, serverResume)))
    ) {
      const resumeFileName = legacyProfile.resume_file_name?.trim() || "resume.pdf";
      await uploadLegacyFile(
        resumeBlob,
        {
          kind: serverResume ? "supporting_document" : "primary_resume",
          fileName: resumeFileName,
          title: serverResume ? `Legacy resume · ${resumeFileName}` : resumeFileName,
          category: "CV / Resume",
          legacyDocumentId: serverResume ? "legacy-primary-resume" : undefined,
          replaceExisting: false,
        },
        "Legacy resume",
      );
    }
  }

  if (isInlineDataUrl(legacyProfile.avatar_url)) {
    let blob: Blob | null = null;
    try {
      blob = decodeDataUrl(legacyProfile.avatar_url as string);
    } catch {
      warnings.push("Malformed legacy avatar was removed instead of being uploaded.");
    }
    const avatarExtensions: Record<string, string> = {
      "image/png": "png",
      "image/jpeg": "jpg",
      "image/webp": "webp",
      "image/gif": "gif",
    };
    const extension = blob ? avatarExtensions[blob.type.toLowerCase()] : undefined;
    if (blob && extension) {
      const matchesServer = serverAvatar
        ? await matchesServerFile(blob, serverAvatar)
        : false;
      if (!matchesServer) {
        await uploadLegacyFile(
          blob,
          {
            kind: serverAvatar ? "supporting_document" : "avatar",
            fileName: `avatar.${extension}`,
            title: serverAvatar ? "Legacy profile avatar" : "Profile avatar",
            category: serverAvatar ? "Other" : "Avatar",
            legacyDocumentId: serverAvatar ? "legacy-profile-avatar" : undefined,
            replaceExisting: false,
          },
          "Legacy avatar",
        );
      }
    } else if (blob) {
      warnings.push(
        `Unsupported legacy avatar type ${blob.type || "unknown"} was removed.`,
      );
    }
  }

  const serializedDocuments: unknown = legacyProfile.documents;
  if (
    (typeof serializedDocuments === "string" && serializedDocuments.trim())
    || Array.isArray(serializedDocuments)
  ) {
    let parsed: unknown;
    if (Array.isArray(serializedDocuments)) {
      parsed = serializedDocuments;
    } else {
      try {
        parsed = JSON.parse(serializedDocuments as string) as unknown;
      } catch {
        warnings.push("Malformed legacy profile document metadata was removed.");
      }
    }
    if (Array.isArray(parsed)) {
      for (const [index, value] of parsed.entries()) {
        if (!value || typeof value !== "object") continue;
        const document = value as Record<string, unknown>;
        const dataUrl = document.data_url ?? document.dataUrl;
        if (!isInlineDataUrl(dataUrl)) continue;
        const fileName =
          typeof document.file_name === "string" && document.file_name.trim()
            ? document.file_name.trim()
            : typeof document.fileName === "string" && document.fileName.trim()
              ? document.fileName.trim()
              : `legacy-document-${index + 1}`;
        const legacyDocumentId =
          typeof document.id === "string" && document.id.trim()
            ? document.id.trim()
            : `legacy-profile-document-${index + 1}`;
        let blob: Blob | null = null;
        try {
          blob = decodeDataUrl(dataUrl as string);
        } catch {
          warnings.push(`Malformed legacy profile document ${fileName} was removed.`);
        }
        if (!blob) continue;
        await uploadLegacyFile(
          blob,
          {
            kind: "supporting_document",
            fileName,
            title: typeof document.title === "string" ? document.title : fileName,
            category:
              typeof document.category === "string" ? document.category : "Other",
            language:
              typeof document.language === "string" ? document.language : "",
            issuer: typeof document.issuer === "string" ? document.issuer : "",
            notes: typeof document.notes === "string" ? document.notes : "",
            legacyDocumentId,
          },
          `Legacy profile document ${fileName}`,
        );
      }
    }
  }
  return warnings;
}

export function hasLegacyProfileInlineFiles(
  legacyProfile: LegacyStoredCandidateProfile,
): boolean {
  if (
    isInlineDataUrl(
      legacyProfile.resume_data_url ?? legacyProfile.resumeDataUrl,
    )
  ) {
    return true;
  }
  if (isInlineDataUrl(legacyProfile.avatar_url)) return true;

  const serializedDocuments: unknown = legacyProfile.documents;
  if (
    serializedDocuments === null
    || serializedDocuments === undefined
    || serializedDocuments === ""
  ) {
    return false;
  }
  try {
    const documents = Array.isArray(serializedDocuments)
      ? serializedDocuments
      : JSON.parse(String(serializedDocuments)) as unknown;
    return Array.isArray(documents) && documents.some((value) => (
      Boolean(value)
      && typeof value === "object"
      && isInlineDataUrl(
        (value as Record<string, unknown>).data_url
        ?? (value as Record<string, unknown>).dataUrl,
      )
    ));
  } catch {
    // Malformed serialized document state still needs the migration path so it
    // can be logged and scrubbed instead of silently bypassed.
    return true;
  }
}
