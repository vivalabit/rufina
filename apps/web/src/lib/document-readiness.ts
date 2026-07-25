type GeneratedDocumentVersionLike = {
  version: number;
  factualValidation?: { status?: string };
  visualValidation?: { status?: string };
  hasRenderedDocx?: boolean;
  hasRenderedArtifact?: boolean;
};

type GeneratedDocumentLike = {
  currentVersion: number;
  versions: GeneratedDocumentVersionLike[];
};

export function getDocumentVersionDownloadWarnings(
  version: GeneratedDocumentVersionLike | undefined,
  isOutdated = false,
) {
  const warnings: string[] = [];

  if (isOutdated) warnings.push("its generation fingerprint is outdated");
  if (version?.factualValidation?.status !== "passed") {
    warnings.push("factual validation has not passed");
  }
  if (version?.visualValidation?.status !== "passed") {
    warnings.push("automated structural checks have not passed");
  }
  if (
    version?.hasRenderedArtifact !== true
    && version?.hasRenderedDocx !== true
  ) {
    warnings.push("a rendered document artifact is not available");
  }

  return warnings;
}

export function getGeneratedDocumentReadiness(
  document: GeneratedDocumentLike | null | undefined,
  isOutdated: boolean,
) {
  if (!document) {
    return {
      ready: false,
      label: "Not generated",
      currentVersion: undefined,
      warnings: ["the document has not been generated"],
    };
  }

  const currentVersion = document.versions.find(
    (version) => version.version === document.currentVersion,
  );
  const warnings = getDocumentVersionDownloadWarnings(
    currentVersion,
    isOutdated,
  );
  const label = isOutdated
    ? "Outdated"
    : currentVersion?.factualValidation?.status !== "passed" ||
        currentVersion?.visualValidation?.status !== "passed"
      ? "Unvalidated"
      : currentVersion?.hasRenderedArtifact !== true
          && currentVersion?.hasRenderedDocx !== true
        ? "Artifact missing"
        : "Ready";

  return {
    ready: warnings.length === 0,
    label,
    currentVersion,
    warnings,
  };
}
