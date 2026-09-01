import { requestJson } from "@/lib/api-client";
import { apiBaseUrl } from "@/shared/api/config";
import type { CandidateProfile } from "@/shared/types/profile";

import type { LegacyProfileFileUploadMetadata } from "../browser-storage/migrations";
import type {
  ProfileFilePayload,
  ResumeEducationImportResponse,
  ResumeExperienceImportResponse,
  ResumeSkillsImportResponse,
} from "./dto";

export class ProfileFileUploadError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ProfileFileUploadError";
    this.status = status;
  }
}

export async function fetchProfile(signal?: AbortSignal) {
  const result = await requestJson<Partial<CandidateProfile>>(
    `${apiBaseUrl}/profile`,
    { cache: "no-store", signal },
    { errorMessage: "Profile could not be loaded" },
  );
  return { profile: result.data, etag: result.etag };
}

export async function putProfile(
  profile: Partial<CandidateProfile>,
  etag: string | null,
  signal?: AbortSignal,
) {
  const result = await requestJson<Partial<CandidateProfile>>(
    `${apiBaseUrl}/profile`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        ...(etag ? { "If-Match": etag } : {}),
      },
      body: JSON.stringify(profile),
      signal,
    },
    { errorMessage: "Profile could not be saved" },
  );
  return { profile: result.data, etag: result.etag };
}

export async function fetchProfileFiles(signal?: AbortSignal) {
  return (await requestJson<ProfileFilePayload[]>(
    `${apiBaseUrl}/profile/files`,
    { cache: "no-store", signal },
    { errorMessage: "Profile files could not be loaded" },
  )).data;
}

export async function uploadProfileFile(
  file: Blob,
  metadata: LegacyProfileFileUploadMetadata,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    kind: metadata.kind,
    file_name: metadata.fileName,
  });
  if (metadata.legacyDocumentId) query.set("legacyDocumentId", metadata.legacyDocumentId);
  if (metadata.replaceExisting !== undefined) {
    query.set("replaceExisting", String(metadata.replaceExisting));
  }
  for (const [key, value] of Object.entries({
    title: metadata.title,
    category: metadata.category,
    language: metadata.language,
    issuer: metadata.issuer,
    notes: metadata.notes,
  })) {
    if (value) query.set(key, value);
  }

  try {
    return (await requestJson<ProfileFilePayload>(
      `${apiBaseUrl}/profile/files?${query}`,
      {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
        signal,
      },
      { errorMessage: "Profile file could not be uploaded" },
    )).data;
  } catch (error) {
    if (error && typeof error === "object" && "status" in error && typeof error.status === "number") {
      throw new ProfileFileUploadError(
        error instanceof Error ? error.message : "Profile file could not be uploaded",
        error.status,
      );
    }
    throw error;
  }
}

export async function patchProfileFile(
  fileId: string,
  metadata: Record<string, string>,
  signal?: AbortSignal,
) {
  return (await requestJson<ProfileFilePayload>(
    `${apiBaseUrl}/profile/files/${encodeURIComponent(fileId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(metadata),
      signal,
    },
    { errorMessage: "Profile file could not be saved" },
  )).data;
}

export async function deleteProfileFile(fileId: string, signal?: AbortSignal) {
  await requestJson<null>(
    `${apiBaseUrl}/profile/files/${encodeURIComponent(fileId)}`,
    { method: "DELETE", signal },
    { errorMessage: "Profile file could not be deleted" },
  );
}

async function importFromResume<T>(path: string, profileFileId: string, signal?: AbortSignal) {
  return (await requestJson<T>(
    `${apiBaseUrl}/profile/${path}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_file_id: profileFileId }),
      signal,
    },
    { errorMessage: "Profile data could not be imported" },
  )).data;
}

export const importProfileExperience = (profileFileId: string, signal?: AbortSignal) =>
  importFromResume<ResumeExperienceImportResponse>(
    "import-experience-from-resume",
    profileFileId,
    signal,
  );

export const importProfileEducation = (profileFileId: string, signal?: AbortSignal) =>
  importFromResume<ResumeEducationImportResponse>(
    "import-education-from-resume",
    profileFileId,
    signal,
  );

export const importProfileSkills = (profileFileId: string, signal?: AbortSignal) =>
  importFromResume<ResumeSkillsImportResponse>(
    "import-skills-from-resume",
    profileFileId,
    signal,
  );
