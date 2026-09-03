import { apiBaseUrl, apiOwnerId } from "./config";
import { formatApiErrorDetail } from "./error";
import {
  revisionFromEtag,
  revisionToken,
  type RevisionToken,
} from "./revision";

export const API_REQUEST_TIMEOUT_MS = 10_000;
export const API_HEALTH_TIMEOUT_MS = 3_000;
export const AI_GENERATION_REQUEST_TIMEOUT_MS = 610_000;
export const API_GET_MAX_ATTEMPTS = 2;

const retryableGetStatuses = new Set([408, 425, 429, 500, 502, 503, 504]);
const ownerHeader = "X-Rufina-Owner-Id";

export type ApiQueryValue = string | number | boolean | null | undefined;
export type ApiQuery = Record<string, ApiQueryValue | readonly ApiQueryValue[]>;

export type ApiResponseMeta = {
  status: number;
  headers: Headers;
  etag: RevisionToken | null;
};

export type ApiResult<T> = {
  data: T;
  meta: ApiResponseMeta;
};

export class ApiUnavailableError extends Error {
  readonly reason: "network" | "timeout";

  constructor(
    message = "API unavailable. Check that the backend is running and retry.",
    reason: "network" | "timeout" = "network",
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "ApiUnavailableError";
    this.reason = reason;
  }
}

export class ApiDecodeError extends Error {
  readonly status: number;
  readonly body: string;

  constructor(message: string, status: number, body: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "ApiDecodeError";
    this.status = status;
    this.body = body;
  }
}

export class ApiResponseError extends Error {
  readonly status: number;
  readonly body: unknown;
  readonly headers: Headers;

  constructor(
    message: string,
    status: number,
    body: unknown,
    headers: Headers = new Headers(),
  ) {
    super(message);
    this.name = "ApiResponseError";
    this.status = status;
    this.body = body;
    this.headers = headers;
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

export type ApiRequest = Omit<RequestInit, "body" | "method" | "signal"> & {
  path: string;
  method?: string;
  query?: ApiQuery | URLSearchParams;
  json?: unknown;
  body?: BodyInit | null;
  signal?: AbortSignal;
  timeoutMs?: number | null;
  errorMessage?: string;
  ifMatch?: RevisionToken | string | number | null;
  retry?: boolean;
};

export type ApiClientOptions = {
  baseUrl: string;
  getOwnerId: () => string | null;
  fetch?: typeof globalThis.fetch;
  sleep?: (milliseconds: number, signal?: AbortSignal) => Promise<void>;
};

function appendQuery(url: URL, query: ApiQuery | URLSearchParams | undefined) {
  if (!query) return;
  if (query instanceof URLSearchParams) {
    query.forEach((value, key) => url.searchParams.append(key, value));
    return;
  }
  Object.entries(query).forEach(([key, rawValue]) => {
    const values = Array.isArray(rawValue) ? rawValue : [rawValue];
    values.forEach((value) => {
      if (value !== null && value !== undefined) {
        url.searchParams.append(key, String(value));
      }
    });
  });
}

function errorMessage(body: unknown, fallback: string) {
  if (body && typeof body === "object") {
    if ("detail" in body) {
      const detail = formatApiErrorDetail(body.detail);
      if (detail) return detail;
    }
    if ("message" in body) {
      const message = formatApiErrorDetail(body.message);
      if (message) return message;
    }
  }
  if (typeof body === "string" && body.trim()) return body.trim();
  return fallback;
}

function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1_000;
  const date = Date.parse(value);
  if (!Number.isFinite(date)) return null;
  return Math.max(0, date - Date.now());
}

function defaultSleep(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
      return;
    }
    const timeoutId = globalThis.setTimeout(resolve, milliseconds);
    signal?.addEventListener("abort", () => {
      globalThis.clearTimeout(timeoutId);
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

function shouldRetryGet(error: unknown) {
  if (error instanceof ApiUnavailableError) return true;
  return error instanceof ApiResponseError && retryableGetStatuses.has(error.status);
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

export function createApiClient(options: ApiClientOptions) {
  const normalizedBaseUrl = options.baseUrl.replace(/\/+$/, "");
  const fetchImplementation = options.fetch ?? globalThis.fetch.bind(globalThis);
  const sleep = options.sleep ?? defaultSleep;

  function url(path: string, query?: ApiQuery | URLSearchParams) {
    const resolved = /^https?:\/\//i.test(path)
      ? new URL(path)
      : new URL(`${normalizedBaseUrl}${path.startsWith("/") ? path : `/${path}`}`);
    appendQuery(resolved, query);
    return resolved;
  }

  async function fetchAttempt(
    request: ApiRequest,
    requestUrl: URL,
    requestOwnerId: string | null,
  ): Promise<Response> {
    const controller = new AbortController();
    const parentSignal = request.signal;
    let timedOut = false;
    const abortFromParent = () => controller.abort(parentSignal?.reason);

    if (parentSignal?.aborted) abortFromParent();
    else parentSignal?.addEventListener("abort", abortFromParent, { once: true });

    const timeoutMs = request.timeoutMs === undefined
      ? API_REQUEST_TIMEOUT_MS
      : request.timeoutMs;
    const timeoutId = timeoutMs === null
      ? null
      : globalThis.setTimeout(() => {
          timedOut = true;
          controller.abort();
        }, timeoutMs);

    const headers = new Headers(request.headers);
    if (requestOwnerId && requestUrl.href.startsWith(`${normalizedBaseUrl}/`)) {
      headers.set(ownerHeader, requestOwnerId);
    }
    if (request.ifMatch !== undefined && request.ifMatch !== null) {
      headers.set("If-Match", revisionToken(request.ifMatch));
    }
    let body = request.body;
    if (request.json !== undefined) {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(request.json);
    }

    try {
      return await fetchImplementation(requestUrl, {
        ...request,
        method: request.method ?? "GET",
        headers,
        body,
        signal: controller.signal,
        path: undefined,
        query: undefined,
        json: undefined,
        timeoutMs: undefined,
        errorMessage: undefined,
        ifMatch: undefined,
        retry: undefined,
      } as RequestInit);
    } catch (error) {
      if (parentSignal?.aborted) throw error;
      if (timedOut) {
        throw new ApiUnavailableError(
          "API unavailable. The request timed out; retry when the backend is ready.",
          "timeout",
          { cause: error },
        );
      }
      if (error instanceof TypeError) {
        throw new ApiUnavailableError(undefined, "network", { cause: error });
      }
      throw error;
    } finally {
      if (timeoutId !== null) globalThis.clearTimeout(timeoutId);
      parentSignal?.removeEventListener("abort", abortFromParent);
    }
  }

  async function response(request: ApiRequest): Promise<Response> {
    const method = (request.method ?? "GET").toUpperCase();
    const requestUrl = url(request.path, request.query);
    const requestOwnerId = options.getOwnerId()?.trim() || null;
    const maxAttempts = method === "GET" && request.retry !== false
      ? API_GET_MAX_ATTEMPTS
      : 1;

    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      try {
        const result = await fetchAttempt(request, requestUrl, requestOwnerId);
        if (!result.ok) {
          const body = await parseResponseBody(result);
          throw new ApiResponseError(
            errorMessage(body, request.errorMessage ?? `API request failed (${result.status})`),
            result.status,
            body,
            result.headers,
          );
        }
        return result;
      } catch (error) {
        if (attempt === maxAttempts || !shouldRetryGet(error)) throw error;
        const retryAfter = error instanceof ApiResponseError
          ? parseRetryAfter(error.headers.get("Retry-After"))
          : null;
        await sleep(retryAfter ?? 250 * 2 ** (attempt - 1), request.signal);
      }
    }
    throw new Error("API request exhausted attempts");
  }

  function meta(result: Response): ApiResponseMeta {
    return {
      status: result.status,
      headers: result.headers,
      etag: revisionFromEtag(result.headers.get("ETag")),
    };
  }

  async function json<T>(
    request: ApiRequest,
    normalize?: (value: unknown) => T,
  ): Promise<ApiResult<T>> {
    const result = await response(request);
    const text = await result.text();
    let value: unknown = null;
    if (text) {
      try {
        value = JSON.parse(text) as unknown;
      } catch (error) {
        throw new ApiDecodeError(
          request.errorMessage ?? "API returned invalid JSON",
          result.status,
          text,
          { cause: error },
        );
      }
    }
    return { data: normalize ? normalize(value) : value as T, meta: meta(result) };
  }

  async function empty(request: ApiRequest): Promise<ApiResponseMeta> {
    const result = await response(request);
    await result.arrayBuffer();
    return meta(result);
  }

  async function blob(request: ApiRequest): Promise<ApiResult<Blob>> {
    const result = await response(request);
    return { data: await result.blob(), meta: meta(result) };
  }

  async function arrayBuffer(request: ApiRequest): Promise<ApiResult<ArrayBuffer>> {
    const result = await response(request);
    return { data: await result.arrayBuffer(), meta: meta(result) };
  }

  async function stream(request: ApiRequest): Promise<ApiResult<ReadableStream<Uint8Array>>> {
    const result = await response(request);
    if (!result.body) {
      throw new ApiDecodeError("API returned an empty stream", result.status, "");
    }
    return { data: result.body, meta: meta(result) };
  }

  return { url, json, empty, blob, arrayBuffer, stream };
}

export const apiClient = createApiClient({
  baseUrl: apiBaseUrl,
  getOwnerId: () => apiOwnerId,
});

export function apiUnavailableMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiUnavailableError) return error.message;
  return error instanceof Error ? error.message : fallback;
}
