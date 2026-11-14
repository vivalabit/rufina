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

export type CoverageStatus = "experience" | "skills" | "missing";

export type TailoringCoverageItem = {
  label: string;
  importance: "required" | "preferred";
  before: CoverageStatus;
  after: CoverageStatus;
};

export type TailoringKnockout = {
  kind: string;
  requirement: string;
  met: boolean | null;
  detail?: string;
};

/** What a run reports next to its documents: score, coverage, changes and gaps. */
export type TailoringReport = {
  language?: string;
  headline?: string;
  vacancy?: {
    title?: string;
    seniority?: string;
    language?: string;
    parsedBy?: string;
  };
  score?: { before?: number | null; after?: number | null };
  coverage?: TailoringCoverageItem[];
  gaps?: Array<{ label: string; importance: string }>;
  knockouts?: TailoringKnockout[];
  statements?: {
    inProfile?: number;
    selected?: number;
    reworded?: number;
    keptOriginal?: number;
    untranslated?: number;
    omitted?: number;
  };
  keptOriginal?: Array<{ id: string; reasons: string[] }>;
  untranslated?: Array<{ id: string; reasons: string[] }>;
  changes?: string[];
  summaryIssues?: string[];
  coverLetterIssues?: string[];
};

export type RenderInfo = {
  templateId?: string;
  templateVersion?: string;
  pages?: Partial<Record<"tailored_resume" | "cover_letter", number>>;
  droppedStatementIds?: string[];
  fitScale?: number;
  atsReadable?: boolean;
};

export type GeneratedDocument = {
  id: string;
  type: "tailored_resume" | "cover_letter";
  version: number;
  downloadUrl: string;
  pdfUrl: string;
};

export type GenerationRunResult = {
  tailoring?: TailoringReport;
  render?: RenderInfo;
  documents?: GeneratedDocument[];
  draft?: Record<string, unknown>;
  warnings?: string[];
  usage?: {
    requests?: number;
    inputTokens?: number;
    outputTokens?: number;
    seconds?: number;
  };
  /** Runs of the earlier pipeline list their changes here. */
  review?: { meaningfulChanges?: string[] };
};

export type GenerationRunTemplate = {
  id: string;
  name: string;
  description: string;
  columns: number;
  atsSafe: boolean;
  isDefault: boolean;
  selected: boolean;
  thumbnailUrl: string;
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
  pendingQuestion: Record<string, unknown> | null;
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
  masterResume: { language?: string; experiences?: unknown[] };
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

/** Render a finished run in another template. No model is called. */
export async function renderGenerationRun(
  applicationId: string,
  run: Pick<GenerationRun, "id" | "revision">,
  templateId: string,
  signal?: AbortSignal,
) {
  return (
    await apiClient.json<GenerationRun>({
      path: `${applicationPath(applicationId)}/${encodeURIComponent(run.id)}/render`,
      method: "POST",
      json: { templateId, revision: run.revision },
      signal,
      retry: false,
      errorMessage: "The template could not be applied",
    })
  ).data;
}

export async function fetchGenerationRunTemplates(
  applicationId: string,
  runId: string,
  signal?: AbortSignal,
) {
  return (
    await apiClient.json<GenerationRunTemplate[]>({
      path: `${applicationPath(applicationId)}/${encodeURIComponent(runId)}/templates`,
      cache: "no-store",
      signal,
      errorMessage: "Templates could not be loaded",
    })
  ).data;
}

/** First page of the run's own resume in a template, as a PNG. */
export async function fetchGenerationRunTemplateThumbnail(
  thumbnailUrl: string,
  signal?: AbortSignal,
) {
  return (
    await apiClient.blob({
      path: thumbnailUrl,
      signal,
      retry: false,
      errorMessage: "The template preview could not be loaded",
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
  return apiClient.url(
    `${applicationPath(applicationId)}/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`,
  ).toString();
}
