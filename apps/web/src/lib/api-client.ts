export const API_REQUEST_TIMEOUT_MS = 10_000;
export const API_HEALTH_TIMEOUT_MS = 3_000;
// AI endpoints can legitimately run for the backend's configured maximum of
// 600 seconds. Keep the browser deadline slightly longer so the backend owns
// timeout and retry decisions instead of reporting a healthy API as offline.
export const AI_GENERATION_REQUEST_TIMEOUT_MS = 610_000;

export class ApiUnavailableError extends Error {
  constructor(message = "API unavailable. Check that the backend is running and retry.") {
    super(message);
    this.name = "ApiUnavailableError";
  }
}

export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs = API_REQUEST_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const parentSignal = init.signal;
  let timedOut = false;
  const abortFromParent = () => controller.abort(parentSignal?.reason);

  if (parentSignal?.aborted) {
    abortFromParent();
  } else {
    parentSignal?.addEventListener("abort", abortFromParent, { once: true });
  }

  const timeoutId = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (timedOut) {
      throw new ApiUnavailableError("API unavailable. The request timed out; retry when the backend is ready.");
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeoutId);
    parentSignal?.removeEventListener("abort", abortFromParent);
  }
}

export function apiUnavailableMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiUnavailableError || error instanceof TypeError) {
    return error instanceof ApiUnavailableError
      ? error.message
      : "API unavailable. Check that the backend is running and retry.";
  }
  return error instanceof Error ? error.message : fallback;
}
