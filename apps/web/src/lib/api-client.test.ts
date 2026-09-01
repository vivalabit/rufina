import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiResponseError,
  ApiUnavailableError,
  apiUnavailableMessage,
  fetchWithTimeout,
  requestJson,
} from "@/lib/api-client";

afterEach(() => {
  vi.useRealTimers();
});

describe("fetchWithTimeout", () => {
  it("turns a hung request into an API unavailable error", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })));

    const request = fetchWithTimeout("http://localhost/health", {}, 25);
    const rejection = expect(request).rejects.toBeInstanceOf(ApiUnavailableError);
    await vi.advanceTimersByTimeAsync(25);

    await rejection;
  });

  it("preserves caller cancellation", async () => {
    const parent = new AbortController();
    vi.stubGlobal("fetch", vi.fn((_: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })));

    const request = fetchWithTimeout("http://localhost/health", { signal: parent.signal }, 1_000);
    parent.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("apiUnavailableMessage", () => {
  it("maps network failures to a retryable user message", () => {
    expect(apiUnavailableMessage(new TypeError("fetch failed"), "fallback"))
      .toMatch(/API unavailable/);
  });
});

describe("requestJson", () => {
  it("returns typed data and response metadata", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(
      { name: "Alice" },
      { headers: { ETag: '"3"' } },
    )));

    await expect(requestJson<{ name: string }>("http://localhost/profile"))
      .resolves.toMatchObject({ data: { name: "Alice" }, etag: '"3"' });
  });

  it("preserves status and conflict revision on API errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(
      { detail: { message: "Resource revision is stale", current_revision: 4 } },
      { status: 412 },
    )));

    const request = requestJson("http://localhost/applications/app-1");
    await expect(request).rejects.toMatchObject({
      name: "ApiResponseError",
      status: 412,
      currentRevision: 4,
      message: "Resource revision is stale",
    } satisfies Partial<ApiResponseError>);
  });
});
