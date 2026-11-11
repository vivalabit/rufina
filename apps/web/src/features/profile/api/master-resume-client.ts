import type { AiBackend } from "@/lib/ai-source";
import { resolveApiUrl } from "@/shared/api/config";
import type { WorkTechnology, WorkResponsibility, WorkProject } from "@/shared/types/profile";
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
    stack?: WorkTechnology[];
    responsibilities?: WorkResponsibility[];
    projects?: WorkProject[];
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
  profileRevision: number;
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
  backend: AiBackend;
};

export type MasterResumeConfirmationResponse = {
  masterResumeId: string;
  version: number;
  sourceFileId: string;
  masterResume: MasterResume;
  createdAt: string;
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

export async function confirmMasterResumeImport(
  sourceFileId: string,
  masterResume: MasterResume,
  expectedProfileRevision: number,
  signal?: AbortSignal,
) {
  return (await apiClient.json<MasterResumeConfirmationResponse>({
    path: "/profile/import-master-resume/confirm",
    method: "POST",
    json: {
      sourceFileId,
      masterResume,
      expectedProfileRevision,
      confirmedSections: MASTER_RESUME_REVIEW_SECTIONS,
    },
    signal,
    errorMessage: "Saving imported information failed",
  }, (value) => requireShape<MasterResumeConfirmationResponse>(
    value,
    "masterResumeId",
    "Saving imported information returned an invalid response",
  ))).data;
}

export type ImportSource = {
  id: string;
  fileName: string;
  sizeBytes: number;
  createdAt: string;
  downloadUrl: string;
  status: "pending" | "imported" | "stored";
  profileVersion: number | null;
  canReview: boolean;
};

export async function fetchImportHistory(signal?: AbortSignal) {
  return (await apiClient.json<ImportSource[]>({ path: "/profile/imports", cache: "no-store", signal,
    errorMessage: "Import history could not be loaded" }, (value) => {
      if (!Array.isArray(value)) throw new ApiDecodeError("Invalid import history", 200, JSON.stringify(value));
      return (value as ImportSource[]).map((source) => ({ ...source, downloadUrl: resolveApiUrl(source.downloadUrl) }));
    })).data;
}

export async function uploadImportSource(file: File) {
  return (await apiClient.json<ImportSource>({ path: "/profile/imports", method: "POST", query: { file_name: file.name },
    headers: { "Content-Type": file.type || "application/octet-stream" }, body: file,
    timeoutMs: 180_000, errorMessage: "Resume upload failed" })).data;
}

export async function previewResumeImport(sourceId: string) {
  return (await apiClient.json<MasterResumeImportResponse>({ path: `/profile/imports/${encodeURIComponent(sourceId)}/preview`, method: "POST",
    timeoutMs: 180_000, errorMessage: "Resume import failed. Your original file is saved in import history." })).data;
}
