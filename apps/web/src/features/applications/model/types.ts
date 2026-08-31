import type { ApplicationDocument, ApplicationStatus } from "@/shared/types/application";
import type { ManualJobDraft } from "@/features/jobs/model/types";

export type ApplicationSortBy = "Date applied" | "AI Match" | "Status";

export type ApplicationStatusFilter = ApplicationStatus | "all";

export type ApplicationListFilter = {
  query: string;
  status: ApplicationStatusFilter;
  sortBy: ApplicationSortBy;
};

export type ManualApplicationDraft = ManualJobDraft & {
  id?: string;
  jobId?: string;
  status: ApplicationStatus;
  documents: ApplicationDocument[];
};
