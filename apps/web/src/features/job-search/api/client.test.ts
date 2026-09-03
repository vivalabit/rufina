import { afterEach, describe, expect, it, vi } from "vitest";

import { API_REQUEST_TIMEOUT_MS } from "@/lib/api-client";

import { runJobSearch } from "./client";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("job-search API client", () => {
  it("keeps long-running parser requests alive past the default API timeout", async () => {
    vi.useFakeTimers();
    const run = {
      id: "run-1",
      status: "completed",
      sources: ["linkedin"],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((_: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((resolve, reject) => {
          const responseTimer = globalThis.setTimeout(
            () => resolve(Response.json(run)),
            API_REQUEST_TIMEOUT_MS + 1,
          );
          init?.signal?.addEventListener("abort", () => {
            globalThis.clearTimeout(responseTimer);
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
      ),
    );

    const request = runJobSearch({ sources: ["linkedin"] });
    await vi.advanceTimersByTimeAsync(API_REQUEST_TIMEOUT_MS + 1);

    await expect(request).resolves.toEqual(run);
  });
});
