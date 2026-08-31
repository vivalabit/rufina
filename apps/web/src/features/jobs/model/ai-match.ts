import { legacyAiMatchVersion } from "@/lib/ai-match";
import { getAiSourceLabel } from "@/lib/ai-source";
import {
  isImportedJob,
  isManualJob,
} from "@/features/jobs/model/sources";
import type { Job, JobRecommendation } from "@/shared/types/job";

const aiMatchBreakdownItems = [
  { key: "role_fit", label: "Role", max: 20 },
  { key: "skills_fit", label: "Skills", max: 30 },
  { key: "experience_fit", label: "Experience", max: 15 },
  { key: "preferences_fit", label: "Preferences", max: 15 },
  { key: "constraints_fit", label: "Constraints", max: 10 },
  { key: "industry_fit", label: "Industry", max: 5 },
  { key: "evidence_fit", label: "Evidence", max: 5 },
];

export function getAiMatchBreakdownItems(job: Job) {
  const breakdown = job.aiMatch?.breakdown ?? {};
  return aiMatchBreakdownItems.map(({ key, label, max }) => {
    const value = Math.max(
      0,
      Math.min(max, Math.round(Number(breakdown[key] ?? 0))),
    );
    return {
      key,
      label,
      value,
      max,
      progress: Math.round((value / max) * 100),
    };
  });
}

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
  return hasDisplayableMatch(job) ? `${job.match}%` : "Not scored";
}

export function getDisplayMatch(job: Job) {
  return hasDisplayableMatch(job) ? job.match : 0;
}

export function buildAiMatchRawExplanation(job: Job) {
  if (job.aiMatch?.rawExplanation) return job.aiMatch.rawExplanation;
  if (job.aiMatch?.explanation) return job.aiMatch.explanation;
  if (job.aiMatch?.providerError) {
    return `Provider fallback: ${job.aiMatch.providerError}`;
  }
  if (!hasDisplayableMatch(job)) {
    return "AI match has not been calculated for this vacancy yet.";
  }

  const source = getAiMatchSourceLabel(job);
  const reasons = job.aiMatch?.reasons.length
    ? job.aiMatch.reasons.join("; ")
    : "no AI-generated reasons are available";
  const gaps = job.aiMatch?.gaps.length
    ? job.aiMatch.gaps.join("; ")
    : "no major gaps detected";

  return `${source} calculated a ${job.match}% match for ${job.title} at ${job.company}. Reasons: ${reasons}. Gaps: ${gaps}.`;
}

export function getProfileImprovementItems(job: Job) {
  const evidence = job.aiMatch?.applicationGuide?.evidenceMatrix ?? [];
  return evidence
    .filter(
      (item) =>
        ["verified", "transferable"].includes(item.status) &&
        item.sources?.length,
    )
    .map(
      (item) =>
        `${item.action} Sources: ${item.sources
          ?.map((source) => `${source.label} — “${source.excerpt}”`)
          .join("; ")}.`,
    )
    .slice(0, 5);
}

export function buildRecommendationPlan(job: Job): JobRecommendation[] {
  const evidence = job.aiMatch?.applicationGuide?.evidenceMatrix ?? [];
  return evidence
    .filter(
      (item) =>
        ["verified", "transferable"].includes(item.status) &&
        item.sources?.length,
    )
    .map((item) => ({
      text: item.action,
      gain:
        item.status === "verified"
          ? "verified evidence"
          : "transferable evidence",
      why: `${item.requirement}: ${item.evidence}`,
      impact: `Sources: ${item.sources
        ?.map((source) => source.label)
        .join(", ")}`,
      action: item.sources
        ?.map((source) => `${source.label}: “${source.excerpt}”`)
        .join(" · "),
    }))
    .slice(0, 9);
}

export function sanitizeLegacyLocalAiMatch(job: Job): Job {
  if (
    job.aiMatch?.source !== "local" ||
    job.aiMatch.version === legacyAiMatchVersion
  ) {
    return job;
  }

  const { aiMatch: legacyAiMatch, ...jobWithoutLegacyAiMatch } = job;
  void legacyAiMatch;
  return {
    ...jobWithoutLegacyAiMatch,
    match: 50,
  };
}
