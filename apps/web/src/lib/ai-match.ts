export const currentAiMatchVersion = "ai-match-v4";

type AiMatchLike = {
  version?: unknown;
  revision?: unknown;
  fingerprint?: unknown;
  score?: unknown;
  reasons?: unknown;
  gaps?: unknown;
} | null | undefined;

export type AiMatchAnalysisStatus = "missing" | "outdated" | "current";

export function getAiMatchAnalysisStatus(aiMatch: AiMatchLike): AiMatchAnalysisStatus {
  if (!aiMatch) return "missing";

  return aiMatch.version === currentAiMatchVersion
    && isAuthoritativeRevision(aiMatch.revision, aiMatch.fingerprint)
    && typeof aiMatch.score === "number"
    && Array.isArray(aiMatch.reasons)
    && Array.isArray(aiMatch.gaps)
    ? "current"
    : "outdated";
}

function isAuthoritativeRevision(revision: unknown, fingerprint: unknown) {
  return (
    typeof revision === "string"
    && Boolean(revision.trim())
    && typeof fingerprint === "string"
    && /^[a-f0-9]{64}$/i.test(fingerprint)
  );
}
