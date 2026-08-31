import { getAiMatchAnalysisStatus } from "@/lib/ai-match";
import { recentJobWindowMs } from "@/features/jobs/model/constants";
import { getDisplayMatch } from "@/features/jobs/model/ai-match";
import { isUserManagedJob } from "@/features/jobs/model/sources";
import type {
  BulkAnalysisScope,
  JobFilters,
  JobSortBy,
} from "@/features/jobs/model/types";
import type { Job } from "@/shared/types/job";

export function mergeJobs(importedJobs: Job[], currentJobs: Job[]) {
  const importedIds = new Set(importedJobs.map((job) => job.id));
  return [
    ...importedJobs,
    ...currentJobs.filter((job) => !importedIds.has(job.id)),
  ];
}

export function keepStoredUserJobs(jobs: Job[]) {
  return jobs.filter(isUserManagedJob);
}

export function hasActiveJobFilters(filters: JobFilters) {
  return Object.values(filters).some((value) => value !== "Any");
}

export function parseSalaryAmount(value: string) {
  if (!value || value === "N/A") return 0;

  const hasThousandsSuffix = /k/i.test(value);
  const amounts = value.match(/\d+(?:[,.]\d+)?/g)?.map((amount) => {
    const normalizedAmount = Number.parseFloat(amount.replace(/,/g, ""));
    if (Number.isNaN(normalizedAmount)) return 0;
    return hasThousandsSuffix ? normalizedAmount * 1000 : normalizedAmount;
  });

  return amounts?.length ? Math.max(...amounts) : 0;
}

export function getJobSalaryAmount(job: Job) {
  return (
    parseSalaryAmount(job.salaryAverage) ||
    parseSalaryAmount(job.salaryMax) ||
    parseSalaryAmount(job.salary)
  );
}

export function getRelativePostedTime(value: string, nowMs: number) {
  const normalizedValue = value.trim().toLowerCase();
  const relativeMatch = normalizedValue.match(/^(\d+)\s*([hdw])(?:\s+ago)?$/);
  if (!relativeMatch) return 0;

  const amount = Number.parseInt(relativeMatch[1], 10);
  const unit = relativeMatch[2];
  const multiplier =
    unit === "h"
      ? 60 * 60 * 1000
      : unit === "d"
        ? 24 * 60 * 60 * 1000
        : 7 * 24 * 60 * 60 * 1000;

  return nowMs - amount * multiplier;
}

export function getJobPostedTime(job: Job, nowMs: number) {
  const parsedDate = Date.parse(job.posted);
  if (!Number.isNaN(parsedDate)) return parsedDate;

  return getRelativePostedTime(job.posted, nowMs);
}

export function getBulkAnalysisCandidates(
  jobsToCheck: Job[],
  scope: BulkAnalysisScope,
  nowMs: number,
) {
  const recentCutoff = nowMs - recentJobWindowMs;

  return jobsToCheck.filter((job) => {
    if (job.archived) return false;
    if (scope === "missing") {
      return getAiMatchAnalysisStatus(job.aiMatch) !== "current";
    }

    const addedAt = Date.parse(job.addedAt ?? "");
    return !Number.isNaN(addedAt) && addedAt >= recentCutoff;
  });
}

export function getJobExperienceYears(job: Job) {
  const normalizedExperience = job.experience.toLowerCase();
  const explicitYears = normalizedExperience.match(/\d+/)?.[0];

  if (explicitYears) return Number.parseInt(explicitYears, 10);
  if (
    normalizedExperience.includes("director") ||
    normalizedExperience.includes("lead") ||
    normalizedExperience.includes("principal")
  ) {
    return 7;
  }
  if (normalizedExperience.includes("senior")) return 5;
  if (normalizedExperience.includes("mid")) return 3;
  if (normalizedExperience.includes("associate")) return 1;
  if (
    normalizedExperience.includes("entry") ||
    normalizedExperience.includes("junior") ||
    normalizedExperience.includes("intern")
  ) {
    return 0;
  }

  return null;
}

export function matchesExperienceFilter(job: Job, filter: string) {
  if (filter === "Any") return true;

  const years = getJobExperienceYears(job);
  const normalizedExperience = job.experience.toLowerCase();

  if (filter === "entry") {
    return (
      (years !== null && years <= 2) ||
      normalizedExperience.includes("entry") ||
      normalizedExperience.includes("junior") ||
      normalizedExperience.includes("associate") ||
      normalizedExperience.includes("intern")
    );
  }

  if (filter === "mid") {
    return (
      (years !== null && years >= 2 && years < 5) ||
      normalizedExperience.includes("mid")
    );
  }

  if (filter === "senior") {
    return (
      (years !== null && years >= 5) ||
      normalizedExperience.includes("senior") ||
      normalizedExperience.includes("director") ||
      normalizedExperience.includes("lead") ||
      normalizedExperience.includes("principal")
    );
  }

  return true;
}

export function matchesRemoteFilter(job: Job, filter: string) {
  if (filter === "Any") return true;

  const searchableText = [
    job.location,
    job.type,
    job.overview,
    job.department,
  ]
    .join(" ")
    .toLowerCase();

  if (filter === "remote") return searchableText.includes("remote");
  if (filter === "hybrid") return searchableText.includes("hybrid");
  if (filter === "onsite") {
    return (
      searchableText.includes("on-site") ||
      searchableText.includes("onsite") ||
      searchableText.includes("office") ||
      (!searchableText.includes("remote") &&
        !searchableText.includes("hybrid"))
    );
  }

  return true;
}

export function matchesJobFilters(job: Job, filters: JobFilters) {
  const salaryAmount = getJobSalaryAmount(job);

  return (
    (filters.location === "Any" ||
      job.location.toLowerCase().includes(filters.location.toLowerCase())) &&
    matchesRemoteFilter(job, filters.remote) &&
    (filters.salary === "Any" ||
      (filters.salary === "listed"
        ? salaryAmount > 0
        : salaryAmount >= Number.parseInt(filters.salary, 10))) &&
    matchesExperienceFilter(job, filters.experience) &&
    (filters.type === "Any" || job.type === filters.type) &&
    (filters.match === "Any" ||
      getDisplayMatch(job) >= Number.parseInt(filters.match, 10))
  );
}

export function selectAvailableJobs(
  jobList: Job[],
  archivedJobIds: string[],
  deletedJobIds: string[],
) {
  return jobList
    .filter((job) => !deletedJobIds.includes(job.id))
    .map((job) => ({
      ...job,
      archived: job.archived || archivedJobIds.includes(job.id),
    }));
}

export function countArchivedJobs(jobs: Job[]) {
  return jobs.filter((job) => job.archived).length;
}

export function countSavedJobs(jobs: Job[], savedJobIds: string[]) {
  return jobs.filter(
    (job) => !job.archived && savedJobIds.includes(job.id),
  ).length;
}

export function selectJobFilterOptions(
  jobs: Job[],
  field: "location" | "type",
) {
  return Array.from(
    new Set(jobs.map((job) => job[field].trim()).filter(Boolean)),
  )
    .sort((a, b) => a.localeCompare(b))
    .map((value) => ({ value, label: value }));
}

type FilteredJobsInput = {
  jobs: Job[];
  filters: JobFilters;
  query: string;
  savedJobIds: string[];
  showArchivedJobs: boolean;
  showSavedJobs: boolean;
  sortBy: JobSortBy;
  nowMs: number;
};

export function selectFilteredJobs({
  jobs,
  filters,
  query,
  savedJobIds,
  showArchivedJobs,
  showSavedJobs,
  sortBy,
  nowMs,
}: FilteredJobsInput) {
  const normalizedQuery = query.trim().toLowerCase();
  const jobsForCurrentMode = jobs
    .filter((job) => Boolean(job.archived) === showArchivedJobs)
    .filter((job) => !showSavedJobs || savedJobIds.includes(job.id))
    .filter((job) => matchesJobFilters(job, filters));
  const results = normalizedQuery
    ? jobsForCurrentMode.filter((job) =>
        [job.title, job.company, job.location, job.type, job.salary].some(
          (value) => value.toLowerCase().includes(normalizedQuery),
        ),
      )
    : jobsForCurrentMode;

  return [...results].sort((left, right) => {
    if (sortBy === "Time") {
      return (
        getJobPostedTime(right, nowMs) - getJobPostedTime(left, nowMs)
      );
    }
    if (sortBy === "Salary") {
      return getJobSalaryAmount(right) - getJobSalaryAmount(left);
    }
    return getDisplayMatch(right) - getDisplayMatch(left);
  });
}
