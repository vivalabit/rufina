import {
  isImportedJob,
  isManualJob,
} from "@/features/jobs/model/sources";
import { getAiMatchAnalysisStatus } from "@/lib/ai-match";
import { isAiBackend } from "@/lib/ai-source";
import type { Job } from "@/shared/types/job";

export type AiMatchPresentationState =
  | "calculating"
  | "current"
  | "outdated"
  | "failed"
  | "missing";

export type AiMatchPresentation = {
  state: AiMatchPresentationState;
  label: "Calculating" | "Calculated" | "Outdated" | "Error" | "Not calculated";
  score: number | null;
};

export function hasAiBackendMatch(job: Job) {
  return (
    !job.aiMatch?.providerError &&
    isAiBackend(job.aiMatch?.source) &&
    Number.isInteger(job.aiMatch.score) &&
    job.aiMatch.score >= 0 &&
    job.aiMatch.score <= 100
  );
}

export function hasDisplayableMatch(job: Job) {
  if (job.aiMatch?.providerError) return false;
  return (
    (!isImportedJob(job) && !isManualJob(job)) || hasAiBackendMatch(job)
  );
}

export function formatMatchValue(job: Job) {
  const presentation = getAiMatchPresentation(job);
  return presentation.score === null
    ? presentation.label
    : `${presentation.score}%`;
}

export function getDisplayMatch(job: Job) {
  return hasDisplayableMatch(job) ? (job.aiMatch?.score ?? job.match) : null;
}

export function getAiMatchPresentation(
  job: Job,
  options: { isCalculating?: boolean; isError?: boolean } = {},
): AiMatchPresentation {
  if (options.isCalculating) {
    return { state: "calculating", label: "Calculating", score: null };
  }
  if (options.isError) {
    return { state: "failed", label: "Error", score: null };
  }

  const analysisStatus = getAiMatchAnalysisStatus(job.aiMatch);
  if (analysisStatus === "failed") {
    return { state: "failed", label: "Error", score: null };
  }
  if (analysisStatus === "outdated") {
    return {
      state: "outdated",
      label: "Outdated",
      score: getDisplayMatch(job),
    };
  }
  if (analysisStatus === "current") {
    return {
      state: "current",
      label: "Calculated",
      score: getDisplayMatch(job),
    };
  }

  const staticScore = getDisplayMatch(job);
  if (staticScore !== null && !isImportedJob(job) && !isManualJob(job)) {
    return { state: "current", label: "Calculated", score: staticScore };
  }
  return { state: "missing", label: "Not calculated", score: null };
}
