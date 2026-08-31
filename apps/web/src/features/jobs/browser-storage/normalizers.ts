import { sanitizeLegacyLocalAiMatch } from "@/features/jobs/model/ai-match";
import { isDirectCompanyJobId } from "@/features/jobs/model/sources";
import type { Job } from "@/shared/types/job";

export function normalizeStoredJobs(value: unknown) {
  if (!Array.isArray(value)) return [];

  return value.flatMap((job): Job[] => {
    if (!job || typeof job !== "object") return [];
    const candidate = job as Partial<Job>;
    const isValidJob =
      typeof candidate.id === "string" &&
      typeof candidate.company === "string" &&
      typeof candidate.title === "string" &&
      typeof candidate.location === "string" &&
      typeof candidate.type === "string" &&
      typeof candidate.salary === "string" &&
      typeof candidate.posted === "string" &&
      typeof candidate.experience === "string" &&
      typeof candidate.department === "string" &&
      typeof candidate.match === "number" &&
      (candidate.logo === "stripe" ||
        candidate.logo === "figma" ||
        candidate.logo === "linkedin" ||
        candidate.logo === "indeed" ||
        candidate.logo === "jobs_ch" ||
        candidate.logo === "company" ||
        candidate.logo === "manual") &&
      typeof candidate.overview === "string" &&
      Array.isArray(candidate.responsibilities) &&
      Array.isArray(candidate.requirements) &&
      Array.isArray(candidate.skills);

    if (!isValidJob) return [];

    return [
      sanitizeLegacyLocalAiMatch({
        ...(candidate as Job),
        logo: normalizeStoredJobLogo(candidate as Job),
        archived: Boolean(candidate.archived),
        archivedAt:
          typeof candidate.archivedAt === "string"
            ? candidate.archivedAt
            : undefined,
      }),
    ];
  });
}

export function normalizeStoredJobLogo(job: Job): Job["logo"] {
  if (job.id.startsWith("linkedin-")) return "linkedin";
  if (job.id.startsWith("indeed-")) return "indeed";
  if (job.id.startsWith("jobs_ch-")) return "jobs_ch";
  if (isDirectCompanyJobId(job.id)) return "company";
  return job.logo;
}

export function normalizeStoredJobIds(value: unknown) {
  if (!Array.isArray(value)) return [];

  return Array.from(
    new Set(
      value.filter(
        (id): id is string =>
          typeof id === "string" && id.trim().length > 0,
      ),
    ),
  );
}
