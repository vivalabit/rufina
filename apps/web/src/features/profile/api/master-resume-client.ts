import { apiClient, ApiDecodeError } from "@/shared/api/client";

export const MASTER_RESUME_REVIEW_SECTIONS = [
  "contacts",
  "summary",
  "skills",
  "experience",
  "education",
  "projects",
  "certifications",
] as const;

export type MasterResumeReviewSectionName =
  (typeof MASTER_RESUME_REVIEW_SECTIONS)[number];
export type ResumeSectionName =
  | "summary"
  | "experience"
  | "skills"
  | "education"
  | "projects"
  | "certifications"
  | "languages"
  | "additional";

type EvidenceBackedText = { text: string; evidenceIds: string[] };
type ResumeBullet = EvidenceBackedText & { id: string };

export type MasterResume = {
  schemaVersion: "1.0";
  id: string;
  language: string;
  basics: {
    fullName: string;
    headline?: string;
    email?: string;
    phone?: string;
    location?: string;
    linkedin?: string;
    github?: string;
    portfolio?: string;
  };
  summary: EvidenceBackedText | null;
  experiences: Array<{
    id: string;
    company: string;
    title: string;
    employmentType?: string;
    location?: string;
    startDate?: string;
    endDate?: string;
    isCurrent?: boolean;
    bullets: ResumeBullet[];
  }>;
  skills: Array<{
    id: string;
    name: string;
    category?: string;
    evidenceIds: string[];
  }>;
  education: Array<{
    id: string;
    institution: string;
    credential: string;
    fieldOfStudy?: string;
    location?: string;
    startDate?: string;
    endDate?: string;
    details: ResumeBullet[];
  }>;
  projects: Array<{
    id: string;
    name: string;
    role?: string;
    url?: string;
    bullets: ResumeBullet[];
  }>;
  certifications: Array<{
    id: string;
    name: string;
    issuer: string;
    issuedOn?: string;
    expiresOn?: string;
    evidenceIds: string[];
  }>;
  languages: Array<{
    id: string;
    name: string;
    proficiency: string;
    evidenceIds: string[];
  }>;
  additionalSections: Array<{
    id: string;
    title: string;
    items: ResumeBullet[];
  }>;
  evidence: Array<{
    id: string;
    type: string;
    text: string;
    claimType?: string | null;
    experienceId?: string | null;
    sourceId?: string | null;
  }>;
  sectionOrder: ResumeSectionName[];
};

export type MasterResumeImportResponse = {
  sourceFileId: string;
  masterResume: MasterResume;
  source: {
    sourceFormat: "pdf" | "docx";
    layout: string;
    pageCount?: number | null;
    usedOcr: boolean;
    fragments: Array<{ id: string; text: string }>;
  };
  reviewSections: Array<{
    name: MasterResumeReviewSectionName;
    itemCount: number;
  }>;
  model: string;
  backend: "openclaw_codex" | "openai_api";
};

export type MasterResumeConfirmationResponse = {
  masterResumeId: string;
  version: number;
  sourceFileId: string;
  masterResume: MasterResume;
  createdAt: string;
};

export type ProfileResume = {
  fileId: string;
  fileName: string;
  fileSize?: string;
};

export type UploadedProfileResume = {
  id: string;
  fileName: string;
  sizeBytes: number;
  contentType: string;
  updatedAt: string;
  downloadUrl: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function requireShape<T>(value: unknown, property: string, message: string): T {
  if (!isRecord(value) || !(property in value)) {
    throw new ApiDecodeError(message, 200, JSON.stringify(value));
  }
  return value as T;
}

export async function uploadPrimaryResume(file: File, signal?: AbortSignal) {
  return (await apiClient.json<UploadedProfileResume>({
    path: "/profile/files",
    query: {
      kind: "primary_resume",
      file_name: file.name,
      title: file.name,
      category: "CV / Resume",
    },
    method: "POST",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
    signal,
    errorMessage: "Resume upload failed",
  }, (value) => requireShape<UploadedProfileResume>(
    value,
    "id",
    "Resume upload returned an invalid response",
  ))).data;
}

export async function importMasterResume(profileFileId: string, signal?: AbortSignal) {
  return (await apiClient.json<MasterResumeImportResponse>({
    path: "/profile/import-master-resume",
    method: "POST",
    json: { profileFileId },
    signal,
    timeoutMs: 180_000,
    errorMessage: "Master Resume import failed",
  }, (value) => requireShape<MasterResumeImportResponse>(
    value,
    "masterResume",
    "Master Resume import returned an invalid response",
  ))).data;
}

export async function confirmMasterResumeImport(
  sourceFileId: string,
  masterResume: MasterResume,
  signal?: AbortSignal,
) {
  return (await apiClient.json<MasterResumeConfirmationResponse>({
    path: "/profile/import-master-resume/confirm",
    method: "POST",
    json: {
      sourceFileId,
      masterResume,
      confirmedSections: MASTER_RESUME_REVIEW_SECTIONS,
    },
    signal,
    errorMessage: "Master Resume confirmation failed",
  }, (value) => requireShape<MasterResumeConfirmationResponse>(
    value,
    "masterResumeId",
    "Master Resume confirmation returned an invalid response",
  ))).data;
}
