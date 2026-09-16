import type { EducationEntry, ExperienceEntry } from "@/shared/types/profile";

export type ProfileFilePayload = {
  id: string;
  kind: "primary_resume" | "supporting_document" | "avatar";
  title: string;
  category: string;
  language: string;
  issuer: string;
  notes: string;
  fileName: string;
  sizeBytes: number;
  contentType: string;
  contentSha256: string;
  createdAt: string;
  updatedAt: string;
  downloadUrl: string;
};

export type ProfileFileUploadMetadata = {
  kind: ProfileFilePayload["kind"];
  fileName: string;
  title?: string;
  category?: string;
  language?: string;
  issuer?: string;
  notes?: string;
  replaceExisting?: boolean;
};

export type ResumeExperienceImportResponse = { source_file_id?: string; experience?: Array<Partial<ExperienceEntry>>; message?: string; detail?: string };
export type ResumeEducationImportResponse = { source_file_id?: string; education?: Array<Partial<EducationEntry>>; message?: string; detail?: string };
export type ResumeSkillsImportResponse = { source_file_id?: string; skills?: string[]; message?: string; detail?: string };
