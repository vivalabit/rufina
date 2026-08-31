import type { ApplicationDocument, ApplicationStatus } from "@/shared/types/application";

export type ApplicationSortBy = "Date applied" | "AI Match" | "Status";

export type ManualJobDraft = {
  title: string;
  company: string;
  location: string;
  applyUrl: string;
  overview: string;
};

export type ManualApplicationDraft = ManualJobDraft & {
  id?: string;
  jobId?: string;
  status: ApplicationStatus;
  documents: ApplicationDocument[];
};
