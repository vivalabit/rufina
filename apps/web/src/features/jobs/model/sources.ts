import { directCompanyCatalog } from "@/lib/direct-company-catalog";
import type { Job } from "@/shared/types/job";

export function isDirectCompanyJobId(jobId: string) {
  return directCompanyCatalog.some((company) =>
    jobId.startsWith(`${company.id}-`),
  );
}

export function isImportedJob(job: Job) {
  return (
    job.id.startsWith("linkedin-") ||
    job.id.startsWith("indeed-") ||
    job.id.startsWith("jobs_ch-") ||
    isDirectCompanyJobId(job.id)
  );
}

export function isManualJob(job: Job) {
  return job.id.startsWith("manual-job-");
}

export function isUserManagedJob(job: Job) {
  return isImportedJob(job) || isManualJob(job);
}
