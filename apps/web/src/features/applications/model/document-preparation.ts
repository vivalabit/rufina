import type {
  DocumentPreparationSettings,
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

export const defaultDocumentPreparationSettings: DocumentPreparationSettings = {
  documentTypes: ["tailored_resume", "cover_letter"],
  language: "English",
  formatting: {
    pageSize: "A4",
    resumeTemplateId: "classic_single",
    resumeMaxPages: 2,
    coverLetterTemplateId: "",
  },
  submission: {
    tailored_resume: null,
    cover_letter: null,
  },
  userPreferences: "",
};

const documentTypes: PreparationDocumentType[] = [
  "tailored_resume",
  "cover_letter",
];
const languages: PreparationLanguage[] = ["English", "German"];
const pageSizes: PreparationPageSize[] = ["A4", "Letter"];
const resumePageCounts: PreparationResumeMaxPages[] = [1, 2, 3];

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
      resumeTemplateId:
        typeof formatting.resumeTemplateId === "string"
          ? formatting.resumeTemplateId.trim().slice(0, 160)
          : defaultDocumentPreparationSettings.formatting.resumeTemplateId,
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
      templateId: settings.formatting.resumeTemplateId,
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
