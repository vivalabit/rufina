import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "@/shared/api/query-client";

import { demoJobs } from "../model/demo-jobs";
import { useJobs } from "./use-jobs";

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => window.localStorage.clear());

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={createQueryClient()}>{children}</QueryClientProvider>;
}

describe("useJobs", () => {
  it("loads jobs and protects optimistic state changes with If-Match", async () => {
    const job = demoJobs[0];
    const state = {
      jobId: job.id,
      saved: false,
      archived: false,
      dismissed: false,
      savedAt: null,
      archivedAt: null,
      dismissedAt: null,
      updatedAt: "2026-09-01T10:00:00Z",
      revision: 2,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      if (url.pathname === "/jobs" && !init?.method) return Response.json([{ id: job.id, data: job }]);
      if (url.pathname === "/jobs/state" && !init?.method) return Response.json([state]);
      if (url.pathname === `/jobs/${job.id}/state` && init?.method === "PATCH") {
        return Response.json({ ...state, saved: true, revision: 3 });
      }
      throw new Error(`Unhandled ${init?.method ?? "GET"} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useJobs(), { wrapper });

    await waitFor(() => expect(result.current.jobs).toHaveLength(1));
    await act(async () => {
      await result.current.patchState(job.id, { saved: true });
    });
    await waitFor(() => expect(result.current.savedJobIds).toContain(job.id));

    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(patchCall?.[1]?.headers).toMatchObject({ "If-Match": '"2"' });
  });
});
