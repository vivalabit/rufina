import type {
  DocumentPreparationSettings,
  GeneratedFile,
  GenerationDocumentResult,
  GenerationDocumentState,
  GenerationError,
  PersistedGenerationResult,
  PreparationDocumentType,
  PreparationLanguage,
  PreparationPageSize,
  PreparationResumeMaxPages,
  SubmissionDocumentSelection,
} from "@/shared/types/application";

export type {
  DocumentPreparationSettings,
  PreparationDocumentType,
  PreparationLanguage,
  PreparationPageSize,
  PreparationResumeMaxPages,
  SubmissionDocumentSelection,
} from "@/shared/types/application";

export const generationResumeTemplates = [
  {
    id: "moderncv_banking",
    name: "ModernCV · Banking",
    description: "A spacious layout with blue section headings and a centered header.",
  },
  {
    id: "ishchenko_classic",
    name: "Ishchenko · Classic",
    description: "Times New Roman, a centered header, and bold section titles with thin black rules.",
  },
] as const;

export function generationResumeTemplate(templateId: unknown) {
  const id = typeof templateId === "string" ? templateId.trim() : "";
  // Previously saved HTML template ids all used the Banking renderer.
  return generationResumeTemplates.find((template) => template.id === id)
    ?? generationResumeTemplates[0];
}

export const defaultDocumentPreparationSettings: DocumentPreparationSettings = {
  documentTypes: ["tailored_resume", "cover_letter"],
  language: "English",
  formatting: {
    pageSize: "A4",
    resumeTemplateId: generationResumeTemplates[0].id,
    resumeMaxPages: 2,
    coverLetterTemplateId: "",
  },
  submission: {
    tailored_resume: null,
    cover_letter: null,
  },
  latestGeneration: null,
  userPreferences: "",
};

const documentTypes: PreparationDocumentType[] = [
  "tailored_resume",
  "cover_letter",
];
const languages: PreparationLanguage[] = ["English", "German"];
const pageSizes: PreparationPageSize[] = ["A4", "Letter"];
const resumePageCounts: PreparationResumeMaxPages[] = [1, 2, 3];
const generationStates: GenerationDocumentState[] = [
  "queued",
  "running",
  "completed",
  "failed",
];

function normalizeSubmissionSelection(
  value: unknown,
): SubmissionDocumentSelection | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<SubmissionDocumentSelection>;
  const documentId = typeof candidate.documentId === "string"
    ? candidate.documentId.trim().slice(0, 240)
    : "";
  if (!documentId) return null;
  const version = candidate.version === null
    ? null
    : Number.isInteger(candidate.version) && Number(candidate.version) > 0
      ? Number(candidate.version)
      : null;
  return { documentId, version };
}

function normalizeGenerationError(value: unknown): GenerationError | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<GenerationError>;
  const code = typeof candidate.code === "string"
    ? candidate.code.trim().slice(0, 80)
    : "";
  const message = typeof candidate.message === "string"
    ? candidate.message.trim().slice(0, 1_000)
    : "";
  if (!code || !message || typeof candidate.retryable !== "boolean") {
    return null;
  }
  return { code, message, retryable: candidate.retryable };
}

function normalizeGeneratedFile(value: unknown): GeneratedFile | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<GeneratedFile>;
  const fileName = typeof candidate.fileName === "string"
    ? candidate.fileName.trim().slice(0, 240)
    : "";
  const contentType = typeof candidate.contentType === "string"
    ? candidate.contentType.trim().slice(0, 160)
    : "";
  const downloadUrl = typeof candidate.downloadUrl === "string"
    ? candidate.downloadUrl.trim().slice(0, 2_000)
    : "";
  const safeDownloadUrl = (
    downloadUrl.startsWith("/") && !downloadUrl.startsWith("//")
  ) || /^https?:\/\//i.test(downloadUrl);
  if (!fileName || !contentType || !safeDownloadUrl) return null;
  return { fileName, contentType, downloadUrl };
}

function normalizeGenerationDocument(
  value: unknown,
): GenerationDocumentResult | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<GenerationDocumentResult>;
  if (
    !documentTypes.includes(candidate.documentType as PreparationDocumentType)
    || !generationStates.includes(candidate.state as GenerationDocumentState)
  ) return null;
  const state = candidate.state as GenerationDocumentState;
  const files = Array.isArray(candidate.files)
    ? candidate.files
        .map(normalizeGeneratedFile)
        .filter((file): file is GeneratedFile => file !== null)
    : [];
  const error = normalizeGenerationError(candidate.error);
  if (state === "completed" && (!files.length || error)) return null;
  if (state === "failed" && !error) return null;
  if ((state === "queued" || state === "running") && (files.length || error)) {
    return null;
  }
  return {
    documentType: candidate.documentType as PreparationDocumentType,
    state,
    files,
    error,
  };
}

export function normalizeGenerationResult(
  value: unknown,
): PersistedGenerationResult | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<PersistedGenerationResult>;
  const executionId = typeof candidate.executionId === "string"
    ? candidate.executionId.trim().slice(0, 160)
    : "";
  if (
    !executionId
    || !generationStates.includes(candidate.state as GenerationDocumentState)
    || !Array.isArray(candidate.documentResults)
  ) return null;
  const documents = candidate.documentResults
    .map(normalizeGenerationDocument)
    .filter((document): document is GenerationDocumentResult => document !== null);
  if (
    !documents.length
    || documents.length > 2
    || documents.length !== candidate.documentResults.length
    || new Set(documents.map((document) => document.documentType)).size
      !== documents.length
  ) return null;
  const state = candidate.state as GenerationDocumentState;
  const error = normalizeGenerationError(candidate.error);
  if (state === "failed" && !error) return null;
  if ((state === "queued" || state === "running") && error) return null;
  if (
    (state === "completed" || state === "failed")
    && documents.some((document) =>
      document.state === "queued" || document.state === "running")
  ) return null;
  return { executionId, state, documentResults: documents, error };
}

export function normalizeDocumentPreparationSettings(
  value: unknown,
): DocumentPreparationSettings {
  if (!value || typeof value !== "object") {
    return structuredClone(defaultDocumentPreparationSettings);
  }

  const candidate = value as Partial<DocumentPreparationSettings>;
  const formatting: Partial<DocumentPreparationSettings["formatting"]> =
    candidate.formatting && typeof candidate.formatting === "object"
      ? candidate.formatting
      : {};
  const submission: Partial<DocumentPreparationSettings["submission"]> =
    candidate.submission && typeof candidate.submission === "object"
      ? candidate.submission
      : {};
  const normalizedDocumentTypes = Array.isArray(candidate.documentTypes)
    ? documentTypes.filter((type) => candidate.documentTypes?.includes(type))
    : defaultDocumentPreparationSettings.documentTypes;

  return {
    documentTypes: [...normalizedDocumentTypes],
    language: languages.includes(candidate.language as PreparationLanguage)
      ? (candidate.language as PreparationLanguage)
      : defaultDocumentPreparationSettings.language,
    formatting: {
      pageSize: pageSizes.includes(formatting.pageSize as PreparationPageSize)
        ? (formatting.pageSize as PreparationPageSize)
        : defaultDocumentPreparationSettings.formatting.pageSize,
      resumeTemplateId: generationResumeTemplate(formatting.resumeTemplateId).id,
      resumeMaxPages: resumePageCounts.includes(
        formatting.resumeMaxPages as PreparationResumeMaxPages,
      )
        ? (formatting.resumeMaxPages as PreparationResumeMaxPages)
        : defaultDocumentPreparationSettings.formatting.resumeMaxPages,
      coverLetterTemplateId:
        typeof formatting.coverLetterTemplateId === "string"
          ? formatting.coverLetterTemplateId.trim().slice(0, 160)
          : defaultDocumentPreparationSettings.formatting.coverLetterTemplateId,
    },
    submission: {
      tailored_resume: normalizeSubmissionSelection(
        submission.tailored_resume,
      ),
      cover_letter: normalizeSubmissionSelection(submission.cover_letter),
    },
    latestGeneration: normalizeGenerationResult(candidate.latestGeneration),
    userPreferences:
      typeof candidate.userPreferences === "string"
        ? candidate.userPreferences.slice(0, 10_000)
        : defaultDocumentPreparationSettings.userPreferences,
  };
}

export function generationRequestFromSettings(
  settings: DocumentPreparationSettings,
) {
  const formattingParameters: Record<
    string,
    Record<string, string | number>
  > = {};

  if (settings.documentTypes.includes("tailored_resume")) {
    formattingParameters.tailored_resume = {
      pageSize: settings.formatting.pageSize,
      templateId: generationResumeTemplate(settings.formatting.resumeTemplateId).id,
      maxPages: settings.formatting.resumeMaxPages,
    };
  }
  if (settings.documentTypes.includes("cover_letter")) {
    formattingParameters.cover_letter = {
      pageSize: settings.formatting.pageSize,
      ...(settings.formatting.coverLetterTemplateId
        ? { templateId: settings.formatting.coverLetterTemplateId }
        : {}),
    };
  }

  return {
    documentTypes: settings.documentTypes,
    language: settings.language,
    formattingParameters,
    userPreferences: settings.userPreferences.trim(),
  };
}
