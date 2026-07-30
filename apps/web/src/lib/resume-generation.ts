export type ResumeGenerationMode = "recruiter_xyz_ats" | "imaginator";

export type ResumeRenderSource =
  | { kind: "ats_final_review"; id: string }
  | { kind: "imaginator"; id: string };

export type ResumeRenderArtifactLike = {
  sourceAtsFinalReviewId?: string | null;
  sourceImaginatorResumeId?: string | null;
  provenance?: unknown;
  stageResults?: unknown;
};

function recordString(
  value: unknown,
  key: string,
): string | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const candidate = (value as Record<string, unknown>)[key];
  return typeof candidate === "string" && candidate.trim()
    ? candidate
    : null;
}

export function resumeRenderSource(
  artifact: ResumeRenderArtifactLike | null | undefined,
): ResumeRenderSource | null {
  if (artifact?.sourceImaginatorResumeId) {
    return {
      kind: "imaginator",
      id: artifact.sourceImaginatorResumeId,
    };
  }
  if (artifact?.sourceAtsFinalReviewId) {
    return {
      kind: "ats_final_review",
      id: artifact.sourceAtsFinalReviewId,
    };
  }
  return null;
}

export function resumeArtifactGenerationMode(
  artifact: ResumeRenderArtifactLike | null | undefined,
): ResumeGenerationMode {
  const explicitMode =
    recordString(artifact?.provenance, "generationMode")
    ?? recordString(artifact?.stageResults, "generationMode");
  if (
    artifact?.sourceImaginatorResumeId
    || explicitMode === "imaginator"
  ) {
    return "imaginator";
  }
  return "recruiter_xyz_ats";
}

export function resumeRenderUrl(
  apiBaseUrl: string,
  source: ResumeRenderSource,
  format: "pdf" | "docx",
  templateId: string,
): string {
  const sourcePath = source.kind === "imaginator"
    ? `/resume-tailoring/imaginator/${encodeURIComponent(source.id)}`
    : `/resume-tailoring/ats-final-review/${encodeURIComponent(source.id)}`;
  return `${apiBaseUrl}${sourcePath}/${format}?templateId=${encodeURIComponent(templateId)}`;
}

export function canReuseResumeRenderSource(
  artifact: ResumeRenderArtifactLike | null | undefined,
  {
    isOutdated,
    selectedMode,
  }: {
    isOutdated: boolean;
    selectedMode: ResumeGenerationMode;
  },
): ResumeRenderSource | null {
  const source = resumeRenderSource(artifact);
  const sourceMode = source?.kind === "imaginator"
    ? "imaginator"
    : "recruiter_xyz_ats";
  if (
    isOutdated
    || !source
    || sourceMode !== selectedMode
    || resumeArtifactGenerationMode(artifact) !== selectedMode
  ) {
    return null;
  }
  return source;
}
