import { apiClient, ApiResponseError } from "@/shared/api/client";

import type { generationRequestFromSettings } from "../model/document-preparation";

export type GenerationRunStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

export type GenerationRunStage =
  | "sources"
  | "fit"
  | "draft"
  | "review"
  | "pdf_checks"
  | "final_review";

export type GenerationRunEvent = {
  sequence: number;
  kind: string;
  stage: GenerationRunStage;
  data: Record<string, unknown>;
  createdAt: string;
};

export type GenerationRunArtifact = {
  id: string;
  documentType: "tailored_resume" | "cover_letter" | null;
  artifactType: string;
  version: number;
  fileName: string;
  contentType: string;
  contentSha256: string;
  metadata: Record<string, unknown>;
  documentId: string | null;
  documentVersion: number | null;
  createdAt: string;
};

export type GenerationRunCheck = {
  id: string;
  artifactId: string | null;
  checkType: string;
  status: "passed" | "failed" | "warning";
  artifactSha256: string | null;
  data: Record<string, unknown>;
  createdAt: string;
};

export type FitKeyword = {
  term: string;
  importance?: string;
  support?: string;
};

export type FitEvaluation = {
  eligible?: boolean;
  overallScore?: number;
  recommendation?: string;
  summary?: string;
  strengths?: string[];
  gaps?: string[];
  keywords?: FitKeyword[];
  clarificationQuestions?: string[];
};

export type ReviewerFeedback = {
  approved?: boolean;
  summary?: string;
  findings?: Array<{
    severity?: string;
    message?: string;
    documentType?: string;
  }>;
  meaningfulChanges?: string[];
  companySources?: Array<{ title?: string; url?: string }>;
};

export type VisualReview = {
  approved?: boolean;
  summary?: string;
  findings?: Array<{ severity?: string; message?: string }>;
};

export type GeneratedDocument = {
  id: string;
  type: "tailored_resume" | "cover_letter";
  version: number;
  downloadUrl: string;
  pdfUrl: string;
};

export type GenerationRunResult = {
  fit?: FitEvaluation;
  review?: ReviewerFeedback;
  visualReview?: VisualReview;
  documents?: GeneratedDocument[];
  draft?: Record<string, unknown>;
};

export type GenerationRun = {
  id: string;
  applicationId: string;
  status: GenerationRunStatus;
  stage: GenerationRunStage;
  revision: number;
  backend: string;
  model: string;
  reasoningEffort: string;
  inputFingerprint: string;
  documentTypes: Array<"tailored_resume" | "cover_letter">;
  pendingQuestion: {
    id?: string;
    prompt?: string;
    choices?: string[];
  } | null;
  result: GenerationRunResult;
  error: { code?: string; message?: string; retryable?: boolean } | null;
  cancelRequested: boolean;
  events: GenerationRunEvent[];
  artifacts: GenerationRunArtifact[];
  checks: GenerationRunCheck[];
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
};

export type StartGenerationRunRequest = ReturnType<
  typeof generationRequestFromSettings
> & { idempotencyKey: string };

export type MasterResumeSummary = {
  masterResumeId: string;
  version: number;
  masterResume: { language?: string };
  createdAt: string;
  updatedAt: string;
};

function applicationPath(applicationId: string) {
  return `/applications/${encodeURIComponent(applicationId)}/generation/runs`;
}

export async function fetchCurrentMasterResumeSummary(signal?: AbortSignal) {
  try {
    return (
      await apiClient.json<MasterResumeSummary>({
        path: "/profile/master-resume",
        cache: "no-store",
        signal,
        retry: false,
        errorMessage: "The candidate profile could not be loaded",
      })
    ).data;
  } catch (error) {
    if (error instanceof ApiResponseError && error.status === 404) return null;
    throw error;
  }
}

export async function fetchCurrentGenerationRun(
  applicationId: string,
  signal?: AbortSignal,
): Promise<GenerationRun | null> {
  try {
    return (
      await apiClient.json<GenerationRun>({
        path: `${applicationPath(applicationId)}/current`,
        cache: "no-store",
        signal,
        retry: false,
        errorMessage: "The current document run could not be loaded",
      })
    ).data;
  } catch (error) {
    if (error instanceof ApiResponseError && error.status === 404) return null;
    throw error;
  }
}

export async function fetchGenerationRuns(
  applicationId: string,
  signal?: AbortSignal,
) {
  return (
    await apiClient.json<GenerationRun[]>({
      path: applicationPath(applicationId),
      cache: "no-store",
      signal,
      errorMessage: "Document versions could not be loaded",
    })
  ).data;
}

export async function fetchGenerationRun(
  applicationId: string,
  runId: string,
  signal?: AbortSignal,
) {
  return (
    await apiClient.json<GenerationRun>({
      path: `${applicationPath(applicationId)}/${encodeURIComponent(runId)}`,
      cache: "no-store",
      signal,
      retry: false,
      errorMessage: "The document run could not be refreshed",
    })
  ).data;
}

export async function startGenerationRun(
  applicationId: string,
  request: StartGenerationRunRequest,
  signal?: AbortSignal,
) {
  return (
    await apiClient.json<GenerationRun>({
      path: applicationPath(applicationId),
      method: "POST",
      json: request,
      signal,
      errorMessage: "The document run could not be started",
    })
  ).data;
}

export async function answerGenerationRun(
  applicationId: string,
  run: Pick<GenerationRun, "id" | "revision">,
  response: "continue" | "stop",
  signal?: AbortSignal,
) {
  return (
    await apiClient.json<GenerationRun>({
      path: `${applicationPath(applicationId)}/${encodeURIComponent(run.id)}/responses`,
      method: "POST",
      json: {
        questionId: "continue_after_fit",
        response,
        revision: run.revision,
      },
      signal,
      errorMessage: "The fit decision could not be saved",
    })
  ).data;
}

export async function cancelGenerationRun(
  applicationId: string,
  run: Pick<GenerationRun, "id" | "revision">,
  signal?: AbortSignal,
) {
  return (
    await apiClient.json<GenerationRun>({
      path: `${applicationPath(applicationId)}/${encodeURIComponent(run.id)}/cancel`,
      method: "POST",
      json: { revision: run.revision },
      signal,
      errorMessage: "The document run could not be cancelled",
    })
  ).data;
}

export function generationArtifactUrl(
  applicationId: string,
  runId: string,
  artifactId: string,
) {
  return `${applicationPath(applicationId)}/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`;
}
