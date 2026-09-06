import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "@/shared/api/query-client";

import { useJobSearch } from "./use-job-search";

afterEach(() => vi.unstubAllGlobals());
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={createQueryClient()}>{children}</QueryClientProvider>;
}

describe("useJobSearch", () => {
  it("loads configs and keeps completed runs as current server state", async () => {
    const run = {
      id: "run-1",
      runType: "manual",
      sources: ["linkedin"],
      status: "completed",
      jobsFound: 2,
      jobsAlreadyKnown: 0,
      jobsDiscoveredNew: 2,
      jobsDiscoveredUpdated: 0,
      jobsAlreadyObserved: 0,
      jobsScreened: 2,
      jobsPassed: 1,
      jobsRejected: 1,
      jobsUncertain: 0,
      jobsAdded: 1,
      jobsAnalyzed: 1,
      screeningErrors: 0,
      jobsScreeningAiCalls: 1,
      sourceErrors: {},
      startedAt: "2026-09-01T10:00:00Z",
      completedAt: "2026-09-01T10:01:00Z",
      warning: null,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      if (url.pathname === "/job-search/configs" && !init?.method) {
        return Response.json([{
          id: "config-1",
          name: "Engineering",
          filters: { sources: ["linkedin"], keywords: "engineer" },
          createdAt: "2026-09-01T09:00:00Z",
          updatedAt: "2026-09-01T09:00:00Z",
        }]);
      }
      if (url.pathname === "/job-search/source-configs" && !init?.method) return Response.json([]);
      if (url.pathname === "/job-search/run" && init?.method === "POST") return Response.json(run);
      throw new Error(`Unhandled ${init?.method ?? "GET"} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useJobSearch(), { wrapper });

    await waitFor(() => expect(result.current.configs).toHaveLength(1));
    await act(async () => {
      await result.current.run({ configId: "config-1", sources: ["linkedin"] });
    });
    await waitFor(() => expect(result.current.runs[0]?.id).toBe("run-1"));
  });
});
