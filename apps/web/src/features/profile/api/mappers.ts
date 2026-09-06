import { resolveApiUrl } from "@/shared/api/config";
import { formatFileSize } from "@/shared/formatting/files";
import type { CandidateProfile } from "@/shared/types/profile";

import { defaultCandidateProfile } from "../model/defaults";
import { normalizeDocumentEntry, serializeDocumentEntries, type ProfileIdFactory } from "../model/entries";
import { normalizeCandidateProfile } from "../model/normalizers";
import type { ProfileFilePayload } from "./dto";

export function profilePayloadForApi(profile: CandidateProfile) {
  const payload: Partial<CandidateProfile> = { ...profile };
  delete payload.documents;
  delete payload.avatar_file_id;
  delete payload.resume_file_id;
  delete payload.resume_file_name;
  delete payload.resume_file_size;
  delete payload.resume_updated_at;
  delete payload.resume_download_url;
  if (payload.avatar_url?.includes("/profile/files/")) payload.avatar_url = defaultCandidateProfile.avatar_url;
  return payload;
}

function profileFileToDocumentEntry(file: ProfileFilePayload, createId: ProfileIdFactory) {
  return normalizeDocumentEntry({
    id: file.id, title: file.title, category: file.category, language: file.language,
    issuer: file.issuer, notes: file.notes, file_name: file.fileName,
    file_size: formatFileSize(file.sizeBytes), file_type: file.contentType,
    uploaded_at: file.updatedAt, download_url: resolveApiUrl(file.downloadUrl),
  }, "", createId);
}

export function hydrateProfileFiles(profile: CandidateProfile, files: ProfileFilePayload[], createId: ProfileIdFactory): CandidateProfile {
  const resume = files.find((file) => file.kind === "primary_resume");
  const avatar = files.find((file) => file.kind === "avatar");
  const documents = files.filter((file) => file.kind === "supporting_document").map((file) => profileFileToDocumentEntry(file, createId));
  return normalizeCandidateProfile({
    ...profile,
    avatar_url: avatar ? resolveApiUrl(avatar.downloadUrl) : profile.avatar_url,
    avatar_file_id: avatar?.id ?? "", documents: serializeDocumentEntries(documents, createId),
    resume_file_id: resume?.id ?? "", resume_file_name: resume?.fileName ?? "",
    resume_file_size: resume ? formatFileSize(resume.sizeBytes) : "", resume_updated_at: resume?.updatedAt ?? "",
    resume_download_url: resume ? resolveApiUrl(resume.downloadUrl) : "",
  });
}

export function applyUploadedPrimaryResume(
  profile: CandidateProfile,
  file: Pick<ProfileFilePayload, "id" | "fileName" | "sizeBytes" | "updatedAt" | "downloadUrl">,
): CandidateProfile {
  return normalizeCandidateProfile({
    ...profile,
    resume_file_id: file.id,
    resume_file_name: file.fileName,
    resume_file_size: formatFileSize(file.sizeBytes),
    resume_updated_at: file.updatedAt,
    resume_download_url: resolveApiUrl(file.downloadUrl),
  });
}

export function mergeHydratedProfileMetadata(savedProfile: Partial<CandidateProfile>, currentProfile: CandidateProfile): CandidateProfile {
  return normalizeCandidateProfile({
    ...savedProfile,
    avatar_url: currentProfile.avatar_url.includes("/profile/files/") ? currentProfile.avatar_url : savedProfile.avatar_url,
    avatar_file_id: currentProfile.avatar_file_id, documents: currentProfile.documents,
    resume_file_id: currentProfile.resume_file_id, resume_file_name: currentProfile.resume_file_name,
    resume_file_size: currentProfile.resume_file_size, resume_updated_at: currentProfile.resume_updated_at,
    resume_download_url: currentProfile.resume_download_url,
  });
}
