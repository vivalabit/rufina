import { getAiSourceLabel } from "@/lib/ai-source";
import {
  isImportedJob,
  isManualJob,
} from "@/features/jobs/model/sources";
import type { Job } from "@/shared/types/job";

export function getAiMatchSourceLabel(job: Job) {
  if (
    job.aiMatch?.source === "openclaw_codex" ||
    job.aiMatch?.source === "openai_api"
  ) {
    return getAiSourceLabel(job.aiMatch.source);
  }
  if (job.aiMatch?.source === "local") return "Legacy local score";
  if (isImportedJob(job) || isManualJob(job)) return "Not scored";
  return "Static score";
}

export function getAiMatchSourceStatus(job: Job) {
  if (!job.aiMatch?.providerError) return "";
  return "Provider fallback/error";
}

export function getAiMatchSourceDisplay(job: Job) {
  const sourceLabel = getAiMatchSourceLabel(job);
  const sourceStatus = getAiMatchSourceStatus(job);
  return sourceStatus ? `${sourceLabel} · ${sourceStatus}` : sourceLabel;
}

export function hasAiBackendMatch(job: Job) {
  return (
    job.aiMatch?.source === "openclaw_codex" ||
    job.aiMatch?.source === "openai_api"
  );
}

export function hasDisplayableMatch(job: Job) {
  return (
    (!isImportedJob(job) && !isManualJob(job)) || hasAiBackendMatch(job)
  );
}

export function formatMatchValue(job: Job) {
  return hasDisplayableMatch(job) ? `${getDisplayMatch(job)}%` : "Not scored";
}

export function getDisplayMatch(job: Job) {
  return hasDisplayableMatch(job) ? (job.aiMatch?.score ?? job.match) : 0;
}
