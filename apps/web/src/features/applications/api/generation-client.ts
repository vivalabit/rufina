import {
  AI_GENERATION_REQUEST_TIMEOUT_MS,
  apiClient,
} from "@/shared/api/client";

import type { generationRequestFromSettings } from "../model/document-preparation";

export type GenerationDocumentState =
  "queued" | "running" | "completed" | "failed";
export type GenerationExecutionState = GenerationDocumentState;

export type GenerationError = {
  code: string;
  message: string;
  retryable: boolean;
};

export type GeneratedFile = {
  fileName: string;
  contentType: string;
  downloadUrl: string;
};

export type GenerationDocumentResult = {
  documentType: "tailored_resume" | "cover_letter";
  state: GenerationDocumentState;
  files: GeneratedFile[];
  error: GenerationError | null;
};

export type GenerationResult = {
  executionId: string;
  state: GenerationExecutionState;
  documents: GenerationDocumentResult[];
  error: GenerationError | null;
};

export async function startApplicationGeneration(
  applicationId: string,
  request: ReturnType<typeof generationRequestFromSettings>,
  signal?: AbortSignal,
) {
  return (
    await apiClient.json<GenerationResult>({
      path: `/applications/${encodeURIComponent(applicationId)}/generation`,
      method: "POST",
      json: request,
      signal,
      timeoutMs: AI_GENERATION_REQUEST_TIMEOUT_MS,
      errorMessage: "Document generation could not be started",
    })
  ).data;
}
