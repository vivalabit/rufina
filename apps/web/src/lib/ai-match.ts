export const currentAiMatchVersion = "ai-match-v6";

type AiMatchLike = {
  version?: unknown;
  revision?: unknown;
  fingerprint?: unknown;
  profileHash?: unknown;
  vacancyHash?: unknown;
  score?: unknown;
  providerError?: unknown;
} | null | undefined;

export type AiMatchAnalysisStatus = "missing" | "outdated" | "failed" | "current";

export function getAiMatchAnalysisStatus(aiMatch: AiMatchLike): AiMatchAnalysisStatus {
  if (!aiMatch) return "missing";
  if (typeof aiMatch.providerError === "string" && aiMatch.providerError.trim()) {
    return "failed";
  }

  return aiMatch.version === currentAiMatchVersion
    && isAuthoritativeRevision(aiMatch.revision, aiMatch.fingerprint)
    && isSha256(aiMatch.profileHash)
    && isSha256(aiMatch.vacancyHash)
    && typeof aiMatch.score === "number"
    && Number.isInteger(aiMatch.score)
    && aiMatch.score >= 0
    && aiMatch.score <= 100
    ? "current"
    : "outdated";
}

function isSha256(value: unknown) {
  return typeof value === "string" && /^[a-f0-9]{64}$/i.test(value);
}

function isAuthoritativeRevision(revision: unknown, fingerprint: unknown) {
  return (
    typeof revision === "string"
    && Boolean(revision.trim())
    && isSha256(fingerprint)
  );
}
