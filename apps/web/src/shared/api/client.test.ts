import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiDecodeError,
  ApiResponseError,
  ApiUnavailableError,
  createApiClient,
} from "./client";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function client(fetch: typeof globalThis.fetch, owner = "owner-a") {
  return createApiClient({
    baseUrl: "http://localhost:8000",
    getOwnerId: () => owner,
    fetch,
    sleep: async () => undefined,
  });
}

describe("shared API client", () => {
  it("builds API URLs and adds the owner identity", async () => {
    const fetch = vi.fn(async () => Response.json({ ok: true }));
    const api = client(fetch);

    await api.json({ path: "/jobs", query: { saved: true, tag: ["a", "b"] } });

    expect(fetch).toHaveBeenCalledOnce();
    const [url, init] = (fetch.mock.calls as unknown as Array<[
      RequestInfo | URL,
      RequestInit | undefined,
    ]>)[0];
    expect(String(url)).toBe("http://localhost:8000/jobs?saved=true&tag=a&tag=b");
    expect(new Headers(init?.headers).get("X-Rufina-Owner-Id")).toBe("owner-a");
  });

  it("does not leak owner identity to external URLs", async () => {
    const fetch = vi.fn(async () => Response.json({ ok: true }));
    const api = client(fetch);

    await api.json({ path: "https://files.example.test/file.json" });

    const [, init] = (fetch.mock.calls as unknown as Array<[
      RequestInfo | URL,
      RequestInit | undefined,
    ]>)[0];
    expect(new Headers(init?.headers).has("X-Rufina-Owner-Id"))
      .toBe(false);
  });

  it("keeps data URLs outside the API origin", async () => {
    const fetch = vi.fn(async () => new Response("resume"));
    const api = client(fetch);

    await api.blob({ path: "data:text/plain,resume" });

    const [url, init] = (fetch.mock.calls as unknown as Array<[
      RequestInfo | URL,
      RequestInit | undefined,
    ]>)[0];
    expect(String(url)).toBe("data:text/plain,resume");
    expect(new Headers(init?.headers).has("X-Rufina-Owner-Id")).toBe(false);
  });

  it("parses JSON once and exposes an opaque ETag", async () => {
    const api = client(vi.fn(async () => Response.json(
      { name: "Alice" },
      { headers: { ETag: '"3"' } },
    )));

    await expect(api.json<{ name: string }>({ path: "/profile" }))
      .resolves.toMatchObject({ data: { name: "Alice" }, meta: { etag: '"3"' } });
  });

  it("handles empty successful JSON responses", async () => {
    const api = client(vi.fn(async () => new Response(null, { status: 204 })));
    await expect(api.json({ path: "/resource", method: "DELETE" }))
      .resolves.toMatchObject({ data: null });
  });

  it("rejects malformed successful JSON without retrying", async () => {
    const fetch = vi.fn(async () => new Response("not-json"));
    const api = client(fetch);

    await expect(api.json({ path: "/jobs" })).rejects.toBeInstanceOf(ApiDecodeError);
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("normalizes FastAPI errors and conflict revision", async () => {
    const api = client(vi.fn(async () => Response.json(
      { detail: { message: "Resource revision is stale", current_revision: 4 } },
      { status: 412 },
    )));

    await expect(api.json({ path: "/applications/app-1" })).rejects.toMatchObject({
      name: "ApiResponseError",
      status: 412,
      currentRevision: 4,
      message: "Resource revision is stale",
    } satisfies Partial<ApiResponseError>);
  });

  it("retries a transient GET but never retries a POST", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockResolvedValueOnce(Response.json({ ok: true }));
    const api = client(fetch);
    await expect(api.json({ path: "/jobs" })).resolves.toMatchObject({ data: { ok: true } });
    expect(fetch).toHaveBeenCalledTimes(2);

    fetch.mockClear();
    fetch.mockResolvedValue(new Response(null, { status: 503 }));
    await expect(api.json({ path: "/jobs", method: "POST", json: {} }))
      .rejects.toBeInstanceOf(ApiResponseError);
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("forwards If-Match without double quoting", async () => {
    const fetch = vi.fn(async () => Response.json({ ok: true }));
    const api = client(fetch);
    await api.json({ path: "/profile", method: "PUT", ifMatch: '"7"', json: {} });
    const [, init] = (fetch.mock.calls as unknown as Array<[
      RequestInfo | URL,
      RequestInit | undefined,
    ]>)[0];
    expect(new Headers(init?.headers).get("If-Match")).toBe('"7"');
  });

  it("preserves caller cancellation", async () => {
    const parent = new AbortController();
    const api = client(vi.fn((_: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      }),
    ));
    const request = api.json({ path: "/jobs", signal: parent.signal });
    parent.abort();
    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });

  it("turns timeouts into unavailable errors", async () => {
    vi.useFakeTimers();
    const api = createApiClient({
      baseUrl: "http://localhost:8000",
      getOwnerId: () => "owner-a",
      sleep: async () => undefined,
      fetch: vi.fn((_: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
      ),
    });
    const request = api.json({ path: "/jobs", method: "POST", timeoutMs: 25 });
    const rejection = expect(request).rejects.toBeInstanceOf(ApiUnavailableError);
    await vi.advanceTimersByTimeAsync(25);
    await rejection;
  });
});
