import { requestJson } from "@/lib/api-client";
import { apiBaseUrl } from "@/shared/api/config";
import type { PersistedEntityDto } from "@/shared/api/dto";
import type { Job } from "@/shared/types/job";

import type { AiMatchJobStatus, JobStatePatch, JobStatePayload } from "./dto";

export async function fetchJobs(signal?: AbortSignal) {
  return (await requestJson<PersistedEntityDto[]>(
    `${apiBaseUrl}/jobs`,
    { cache: "no-store", signal },
    { errorMessage: "Vacancies could not be loaded" },
  )).data;
}

export async function upsertJobs(jobs: Job[], signal?: AbortSignal) {
  return (await requestJson<PersistedEntityDto[]>(
    `${apiBaseUrl}/jobs`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jobs: jobs.map((job) => ({ id: job.id, data: job })) }),
      signal,
    },
    { errorMessage: "Vacancies could not be saved" },
  )).data;
}

export async function fetchJobStates(signal?: AbortSignal) {
  return (await requestJson<JobStatePayload[]>(
    `${apiBaseUrl}/jobs/state`,
    { cache: "no-store", signal },
    { errorMessage: "Job state could not be loaded" },
  )).data;
}

export async function importLegacyJobStates(
  jobs: Array<{ jobId: string; saved: boolean; archived: boolean; dismissed: boolean }>,
  signal?: AbortSignal,
) {
  return (await requestJson<JobStatePayload[]>(
    `${apiBaseUrl}/jobs/state/import`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jobs }),
      signal,
    },
    { errorMessage: "Legacy job state could not be imported" },
  )).data;
}

export async function patchJobState(
  jobId: string,
  patch: JobStatePatch,
  revision: number,
  signal?: AbortSignal,
) {
  return (await requestJson<JobStatePayload>(
    `${apiBaseUrl}/jobs/${encodeURIComponent(jobId)}/state`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "If-Match": `"${revision}"`,
      },
      body: JSON.stringify({ ...patch, revision }),
      signal,
    },
    { errorMessage: "Job state could not be saved" },
  )).data;
}

export async function deleteJob(jobId: string, signal?: AbortSignal) {
  await requestJson<null>(
    `${apiBaseUrl}/jobs/${encodeURIComponent(jobId)}`,
    { method: "DELETE", signal },
    { errorMessage: "Vacancy could not be deleted" },
  );
}

export async function startAiMatch(jobs: Job[], force: boolean, signal?: AbortSignal) {
  return (await requestJson<AiMatchJobStatus>(
    `${apiBaseUrl}/jobs/ai-match/run${force ? "?force=true" : ""}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jobs: jobs.map((job) => ({ id: job.id, data: job })) }),
      signal,
    },
    { errorMessage: "AI match run could not start" },
  )).data;
}

export async function matchJobs(jobs: Job[], force: boolean, signal?: AbortSignal) {
  return (await requestJson<PersistedEntityDto[]>(
    `${apiBaseUrl}/jobs/ai-match${force ? "?force=true" : ""}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jobs: jobs.map((job) => ({ id: job.id, data: job })) }),
      signal,
    },
    { errorMessage: "AI analysis failed" },
  )).data;
}

export async function fetchAiMatchStatus(signal?: AbortSignal) {
  return (await requestJson<AiMatchJobStatus>(
    `${apiBaseUrl}/jobs/ai-match/status`,
    { cache: "no-store", signal },
    { errorMessage: "AI match status check failed" },
  )).data;
}
