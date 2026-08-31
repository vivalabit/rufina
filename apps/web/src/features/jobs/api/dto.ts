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
