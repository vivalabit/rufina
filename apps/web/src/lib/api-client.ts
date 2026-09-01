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

export class ApiResponseError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiResponseError";
    this.status = status;
    this.body = body;
  }

  get currentRevision(): number | null {
    if (!this.body || typeof this.body !== "object") return null;
    const detail = "detail" in this.body ? this.body.detail : this.body;
    if (!detail || typeof detail !== "object") return null;
    const value =
      "currentRevision" in detail
        ? detail.currentRevision
        : "current_revision" in detail
          ? detail.current_revision
          : null;
    return typeof value === "number" ? value : null;
  }
}

export type ApiJsonResult<T> = {
  data: T;
  etag: string | null;
  response: Response;
};

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

function apiErrorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  if ("message" in body && typeof body.message === "string") return body.message;
  if (!("detail" in body)) return fallback;
  const detail = body.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") {
    return detail.message;
  }
  return fallback;
}

export async function requestJson<T>(
  input: RequestInfo | URL,
  init: RequestInit = {},
  options: { errorMessage?: string; timeoutMs?: number } = {},
): Promise<ApiJsonResult<T>> {
  const response = await fetchWithTimeout(
    input,
    init,
    options.timeoutMs ?? API_REQUEST_TIMEOUT_MS,
  );
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = text;
    }
  }
  if (!response.ok) {
    throw new ApiResponseError(
      apiErrorMessage(body, options.errorMessage ?? "API request failed"),
      response.status,
      body,
    );
  }
  return {
    data: body as T,
    etag: response.headers.get("ETag"),
    response,
  };
}
