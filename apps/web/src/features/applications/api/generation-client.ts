import {
  AI_GENERATION_REQUEST_TIMEOUT_MS,
  apiClient,
} from "@/shared/api/client";
import type {
  GeneratedFile,
  GenerationDocumentResult,
  GenerationDocumentState,
  GenerationError,
  GenerationExecutionState,
  GenerationResult,
} from "@/shared/types/application";

import type { generationRequestFromSettings } from "../model/document-preparation";

export type {
  GeneratedFile,
  GenerationDocumentResult,
  GenerationDocumentState,
  GenerationError,
  GenerationExecutionState,
  GenerationResult,
};

export type GenerationAvailability = {
  available: boolean;
  code: "available" | "generator_unavailable";
  message: string;
};

export async function fetchApplicationGenerationAvailability(
  applicationId: string,
  signal?: AbortSignal,
) {
  return (
    await apiClient.json<GenerationAvailability>({
      path: `/applications/${encodeURIComponent(applicationId)}/generation/availability`,
      cache: "no-store",
      signal,
      errorMessage: "Generation availability could not be checked",
    })
  ).data;
}

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
