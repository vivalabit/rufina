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

/** Gallery templates, in the order the server lists them. The first is the default. */
export const generationResumeTemplates = [
  {
    id: "swiss_classic",
    name: "Swiss Classic",
    description: "Classic serif on one column. Reads well for people and for applicant tracking systems.",
  },
  {
    id: "classic_single",
    name: "Classic",
    description: "Traditional single-column layout.",
  },
  {
    id: "modern_single",
    name: "Modern",
    description: "Contemporary single-column layout with a restrained accent.",
  },
  {
    id: "swiss_local_german",
    name: "Swiss Local German",
    description: "Compact German-language Swiss CV with a one-line header.",
  },
  {
    id: "modern_two_column",
    name: "Modern two-column",
    description: "Design layout with a skills rail. Some applicant tracking systems misread two columns.",
  },
] as const;

/** Identifiers saved by the earlier LaTeX generator. */
const renamedTemplateIds: Record<string, string> = {
  roman: "swiss_classic",
  ishchenko_classic: "swiss_classic",
  moderncv_banking: "modern_single",
};

export function generationResumeTemplate(templateId: unknown) {
  const requestedId = typeof templateId === "string" ? templateId.trim() : "";
  const id = renamedTemplateIds[requestedId] ?? requestedId;
  return generationResumeTemplates.find((template) => template.id === id)
    ?? generationResumeTemplates[0];
}

const lastTemplateStorageKey = "rufina.document-template";

/** The template the person picked last, used for the next application. */
export function rememberedDocumentTemplateId() {
  try {
    return generationResumeTemplate(
      globalThis.localStorage?.getItem(lastTemplateStorageKey),
    ).id;
  } catch {
    return generationResumeTemplates[0].id;
  }
}

export function rememberDocumentTemplateId(templateId: string) {
  try {
    globalThis.localStorage?.setItem(lastTemplateStorageKey, templateId);
  } catch {
    // Storage can be unavailable; the choice still applies to this application.
  }
}

export const defaultDocumentPreparationSettings: DocumentPreparationSettings = {
  documentTypes: ["tailored_resume", "cover_letter"],
  language: "Auto",
  languageChoice: "Auto",
  formatting: {
    pageSize: "A4",
    resumeTemplateId: generationResumeTemplates[0].id,
    resumeMaxPages: 1,
    coverLetterTemplateId: generationResumeTemplates[0].id,
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
const languages: PreparationLanguage[] = ["Auto", "English", "German"];
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
    languageChoice: languages.includes(candidate.languageChoice as PreparationLanguage)
      ? (candidate.languageChoice as PreparationLanguage)
      : "Auto",
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
      // Keep the persisted legacy field in sync with the single design selection.
      coverLetterTemplateId: generationResumeTemplate(formatting.resumeTemplateId).id,
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
      templateId: generationResumeTemplate(settings.formatting.resumeTemplateId).id,
    };
  }

  return {
    documentTypes: settings.documentTypes,
    // "Auto" writes in the language of the vacancy. The older `language` field
    // is ignored so that a choice saved long ago cannot override the vacancy.
    language: settings.languageChoice ?? "Auto",
    formattingParameters,
    userPreferences: settings.userPreferences.trim(),
  };
}
