import type { AiBackend } from "@/lib/ai-source";
import type { CandidateConfirmation } from "@/lib/candidate-confirmations";
import type { ResumeRenderSource } from "@/lib/resume-generation";
import type { ResumeTemplate } from "@/lib/resume-templates";
import {
  AI_GENERATION_REQUEST_TIMEOUT_MS,
  API_HEALTH_TIMEOUT_MS,
  apiClient,
  ApiResponseError,
} from "@/shared/api/client";

export type WorkspaceAiConfiguration = {
  providerName: string;
  backend: AiBackend;
};

export type WorkspaceMasterResume = {
  masterResumeId: string;
  version: number;
  createdAt: string;
  updatedAt: string;
};

export type WorkspaceDocumentTemplate = {
  id: string;
  type: "cover_letter" | "tailored_resume";
  name: string;
  fileName: string;
  builtIn: boolean;
  createdAt: string;
  updatedAt: string;
};

export type AssistantGenerationContext = {
  applicationId: string;
  templateId: string;
  documentType: "cover_letter" | "tailored_resume";
  targetLanguage: "English" | "German";
};

export type ResumeTailoringStage =
  | "imaginator"
  | "senior_recruiter_analysis"
  | "experience_rewrite"
  | "ats_final_review";

export class ResumeTemplateUnavailableError extends Error {
  constructor(options?: ErrorOptions) {
    super(
      "The selected resume template was deleted or is no longer available. Choose another template.",
      options,
    );
    this.name = "ResumeTemplateUnavailableError";
  }
}

function normalizeArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function resumeRenderPath(source: ResumeRenderSource, format: "pdf" | "docx") {
  const resource = source.kind === "imaginator"
    ? "imaginator"
    : "ats-final-review";
  return `/resume-tailoring/${resource}/${encodeURIComponent(source.id)}/${format}`;
}

export async function checkApiHealth(signal?: AbortSignal) {
  await apiClient.empty({
    path: "/health",
    cache: "no-store",
    signal,
    timeoutMs: API_HEALTH_TIMEOUT_MS,
    errorMessage: "API health check failed",
  });
}

export async function fetchGeneratedDocuments<T>(
  applicationId: string,
  signal?: AbortSignal,
) {
  return (await apiClient.json<T[]>({
    path: "/documents",
    query: { applicationId },
    signal,
    errorMessage: "Application documents are temporarily unavailable",
  }, normalizeArray<T>)).data;
}

export async function fetchWorkspaceDocumentTemplates(signal?: AbortSignal) {
  return (await apiClient.json<WorkspaceDocumentTemplate[]>({
    path: "/documents/templates/library",
    signal,
    errorMessage: "Document templates are temporarily unavailable",
  }, normalizeArray<WorkspaceDocumentTemplate>)).data;
}

export async function fetchWorkspaceResumeTemplates(signal?: AbortSignal) {
  return (await apiClient.json<ResumeTemplate[]>({
    path: "/resume-templates",
    cache: "no-store",
    signal,
    errorMessage: "Resume templates are temporarily unavailable",
  }, normalizeArray<ResumeTemplate>)).data;
}

export async function fetchWorkspaceAiConfiguration(signal?: AbortSignal) {
  return (await apiClient.json<WorkspaceAiConfiguration>({
    path: "/assistant/config",
    signal,
    errorMessage: "AI configuration is temporarily unavailable",
  })).data;
}

export async function fetchWorkspaceMasterResume(signal?: AbortSignal) {
  try {
    return (await apiClient.json<WorkspaceMasterResume>({
      path: "/profile/master-resume",
      cache: "no-store",
      signal,
      errorMessage: "Master Resume is temporarily unavailable",
    })).data;
  } catch (error) {
    if (error instanceof ApiResponseError && error.status === 404) return null;
    throw error;
  }
}

export async function fetchCandidateConfirmations(
  applicationId: string,
  signal?: AbortSignal,
) {
  try {
    return (await apiClient.json<CandidateConfirmation[]>({
      path: `/applications/${encodeURIComponent(applicationId)}/confirmations`,
      cache: "no-store",
      signal,
      errorMessage: "Candidate confirmations could not be loaded",
    }, normalizeArray<CandidateConfirmation>)).data;
  } catch (error) {
    if (error instanceof ApiResponseError && error.status === 404) return [];
    throw error;
  }
}

export async function saveCandidateConfirmations(
  applicationId: string,
  confirmations: Array<{
    questionId: string;
    response: CandidateConfirmation["response"];
    exampleText: string;
  }>,
  signal?: AbortSignal,
) {
  return (await apiClient.json<CandidateConfirmation[]>({
    path: `/applications/${encodeURIComponent(applicationId)}/confirmations`,
    method: "PUT",
    json: { confirmations },
    signal,
    errorMessage: "Candidate confirmations could not be saved",
  }, normalizeArray<CandidateConfirmation>)).data;
}

export async function askWorkspaceAssistant(
  applicationId: string,
  threadId: string,
  message: string,
  generationContext?: AssistantGenerationContext,
) {
  const payload = (await apiClient.json<{
    message?: unknown;
    metadata?: { generationArtifactId?: unknown };
  }>({
    path: "/assistant/chat",
    method: "POST",
    json: {
      threadId,
      message,
      contextKind: "application",
      contextId: applicationId,
      ...(generationContext ? { generationContext } : {}),
    },
    timeoutMs: AI_GENERATION_REQUEST_TIMEOUT_MS,
    errorMessage: "AI request failed",
  })).data;
  return {
    message: typeof payload?.message === "string" ? payload.message.trim() : "",
    generationArtifactId:
      typeof payload?.metadata?.generationArtifactId === "string"
        ? payload.metadata.generationArtifactId.trim()
        : "",
  };
}

const tailoringStageRequests: Record<ResumeTailoringStage, {
  path: string;
  errorMessage: string;
  timeoutMs: number;
}> = {
  imaginator: {
    path: "/resume-tailoring/imaginator",
    errorMessage: "Imaginator generation failed",
    timeoutMs: AI_GENERATION_REQUEST_TIMEOUT_MS * 2,
  },
  senior_recruiter_analysis: {
    path: "/resume-tailoring/senior-recruiter-analysis",
    errorMessage: "Senior recruiter analysis failed",
    timeoutMs: AI_GENERATION_REQUEST_TIMEOUT_MS,
  },
  experience_rewrite: {
    path: "/resume-tailoring/experience-rewrite",
    errorMessage: "Experience rewrite failed",
    timeoutMs: AI_GENERATION_REQUEST_TIMEOUT_MS,
  },
  ats_final_review: {
    path: "/resume-tailoring/ats-final-review",
    errorMessage: "ATS final review failed",
    timeoutMs: AI_GENERATION_REQUEST_TIMEOUT_MS,
  },
};

export async function runResumeTailoringStage<T extends { id: string }>(
  stage: ResumeTailoringStage,
  payload: unknown,
  signal?: AbortSignal,
) {
  const request = tailoringStageRequests[stage];
  return (await apiClient.json<T>({
    path: request.path,
    method: "POST",
    json: payload,
    signal,
    timeoutMs: request.timeoutMs,
    errorMessage: request.errorMessage,
  })).data;
}

export async function renderResumePdf(
  source: ResumeRenderSource,
  templateId: string,
  signal?: AbortSignal,
) {
  try {
    const result = await apiClient.blob({
      path: resumeRenderPath(source, "pdf"),
      query: { templateId },
      cache: "no-store",
      signal,
      timeoutMs: AI_GENERATION_REQUEST_TIMEOUT_MS,
      errorMessage: "PDF rendering failed",
    });
    return {
      documentId: result.meta.headers.get("X-Rufina-Document-Id"),
      data: result.data,
    };
  } catch (error) {
    if (error instanceof ApiResponseError && error.status === 404) {
      throw new ResumeTemplateUnavailableError({ cause: error });
    }
    throw error;
  }
}

export async function attachGeneratedDocument<T>(
  documentId: string,
  applicationId: string,
  signal?: AbortSignal,
) {
  return (await apiClient.json<T>({
    path: `/documents/${encodeURIComponent(documentId)}/attachments`,
    method: "POST",
    json: { applicationId },
    signal,
    errorMessage: "PDF could not be attached to the application",
  })).data;
}

export async function fetchGeneratedDocument<T>(
  documentId: string,
  signal?: AbortSignal,
) {
  return (await apiClient.json<T>({
    path: `/documents/${encodeURIComponent(documentId)}`,
    cache: "no-store",
    signal,
    errorMessage: "The saved document details are temporarily unavailable.",
  })).data;
}

export async function downloadGeneratedDocument(
  documentId: string,
  version?: number,
  signal?: AbortSignal,
) {
  return (await apiClient.blob({
    path: `/documents/${encodeURIComponent(documentId)}/download`,
    query: version === undefined ? undefined : { version },
    cache: "no-store",
    signal,
    errorMessage: "The saved document is temporarily unavailable.",
  })).data;
}

export async function downloadGeneratedDocumentPdf(
  documentId: string,
  version?: number,
  signal?: AbortSignal,
) {
  return (await apiClient.blob({
    path: `/documents/${encodeURIComponent(documentId)}/pdf`,
    query: version === undefined ? undefined : { version },
    cache: "no-store",
    signal,
    errorMessage: "The PDF preview is temporarily unavailable.",
  })).data;
}

export async function saveGeneratedDocument<T>(
  documentId: string | null,
  payload: unknown,
  signal?: AbortSignal,
) {
  return (await apiClient.json<T>({
    path: documentId
      ? `/documents/${encodeURIComponent(documentId)}`
      : "/documents",
    method: documentId ? "PATCH" : "POST",
    json: payload,
    signal,
    errorMessage: "Document save failed",
  })).data;
}

export async function restoreGeneratedDocument<T>(
  documentId: string,
  version: number,
  signal?: AbortSignal,
) {
  return (await apiClient.json<T>({
    path: `/documents/${encodeURIComponent(documentId)}/restore`,
    method: "POST",
    json: { version },
    signal,
    errorMessage: "Document version could not be restored",
  })).data;
}

export async function fetchGeneratedDocumentVersions<T>(
  documentId: string,
  offset: number,
  signal?: AbortSignal,
) {
  return (await apiClient.json<{ items: T[]; total: number }>({
    path: `/documents/${encodeURIComponent(documentId)}/versions`,
    query: { offset, limit: 20 },
    signal,
    errorMessage: "Version history could not be loaded",
  })).data;
}

export async function deleteGeneratedDocument(documentId: string, signal?: AbortSignal) {
  await apiClient.empty({
    path: `/documents/${encodeURIComponent(documentId)}`,
    method: "DELETE",
    signal,
    errorMessage: "Document could not be deleted",
  });
}

export function generatedDocumentDownloadUrl(documentId: string, version?: number) {
  return apiClient.url(
    `/documents/${encodeURIComponent(documentId)}/download`,
    version === undefined ? undefined : { version },
  ).toString();
}

export function generatedDocumentPdfUrl(documentId: string, version?: number) {
  return apiClient.url(
    `/documents/${encodeURIComponent(documentId)}/pdf`,
    version === undefined ? undefined : { version },
  ).toString();
}

export function generatedResumeRenderUrl(
  source: ResumeRenderSource,
  format: "pdf" | "docx",
  templateId: string,
) {
  return apiClient.url(resumeRenderPath(source, format), { templateId }).toString();
}

export function documentTemplateThumbnailUrl(templateId: string, version: string) {
  return apiClient.url(
    `/documents/templates/${encodeURIComponent(templateId)}/thumbnail`,
    { version, format: "9x16" },
  ).toString();
}

export function resumeTemplateThumbnailUrl(template: ResumeTemplate) {
  return apiClient.url(
    `/resume-templates/${encodeURIComponent(template.id)}/thumbnail`,
    {
      version: String(template.version ?? template.baseTemplateId),
      format: "9x16",
    },
  ).toString();
}
