import type { AiBackend } from "@/lib/ai-source";
import type { CandidateConfirmation } from "@/lib/candidate-confirmations";
import type { ResumeGenerationMode, ResumeRenderSource } from "@/lib/resume-generation";
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

export type WorkspaceApplicationPreferences = {
  application_id: string;
  resume_template_id: string | null;
  resume_generation_mode: ResumeGenerationMode | null;
  updated_at: string;
  revision: number;
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

export async function fetchWorkspaceApplicationPreferences(
  applicationId: string,
  signal?: AbortSignal,
) {
  try {
    return (await apiClient.json<WorkspaceApplicationPreferences>({
      path: `/applications/${encodeURIComponent(applicationId)}/preferences`,
      cache: "no-store",
      signal,
      errorMessage: "Application preferences could not be loaded",
    })).data;
  } catch (error) {
    if (error instanceof ApiResponseError && error.status === 404) return null;
    throw error;
  }
}

export async function saveWorkspaceApplicationPreferences(
  applicationId: string,
  preferences: {
    resume_template_id?: string | null;
    resume_generation_mode?: ResumeGenerationMode | null;
  },
  revision: number | null,
  signal?: AbortSignal,
) {
  return (await apiClient.json<WorkspaceApplicationPreferences>({
    path: `/applications/${encodeURIComponent(applicationId)}/preferences`,
    method: "PUT",
    ifMatch: revision,
    json: preferences,
    signal,
    errorMessage: "Application preferences could not be saved",
  })).data;
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
