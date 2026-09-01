import type { PersistedEntityDto } from "@/shared/api/dto";

export type AiMatchJobStatus = {
  runId: string;
  status: "idle" | "queued" | "running" | "completed" | "failed";
  total: number;
  processed: number;
  updatedJobs: PersistedEntityDto[];
  failedJobs?: Array<{ id: string; error: string }>;
  error?: string | null;
};

export type JobStatePayload = {
  jobId: string;
  saved: boolean;
  archived: boolean;
  dismissed: boolean;
  savedAt: string | null;
  archivedAt: string | null;
  dismissedAt: string | null;
  updatedAt: string;
  revision: number;
};

export type JobStatePatch = Partial<Pick<JobStatePayload, "saved" | "archived" | "dismissed">>;
