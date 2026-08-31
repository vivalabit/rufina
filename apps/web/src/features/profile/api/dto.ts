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

export type ResumeExperienceImportResponse = { experience?: Array<Partial<ExperienceEntry>>; message?: string; detail?: string };
export type ResumeEducationImportResponse = { education?: Array<Partial<EducationEntry>>; message?: string; detail?: string };
export type ResumeSkillsImportResponse = { skills?: string[]; message?: string; detail?: string };
