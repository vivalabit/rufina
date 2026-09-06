import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "@/shared/api/query-client";

import { demoJobs } from "../model/demo-jobs";
import { useJobs } from "./use-jobs";

afterEach(() => vi.unstubAllGlobals());
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

  it("uses authoritative states and revisions for every job", async () => {
    const [archivedJob, job] = demoJobs;
    const archivedState = {
      jobId: archivedJob.id,
      saved: false,
      archived: true,
      dismissed: false,
      savedAt: null,
      archivedAt: "2026-09-01T09:00:00Z",
      dismissedAt: null,
      updatedAt: "2026-09-01T09:00:00Z",
      revision: 2,
    };
    const state = {
      jobId: job.id,
      saved: false,
      archived: false,
      dismissed: false,
      savedAt: null,
      archivedAt: null,
      dismissedAt: null,
      updatedAt: "2026-09-01T10:00:00Z",
      revision: 4,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      if (url.pathname === "/jobs" && !init?.method) {
        return Response.json([
          { id: archivedJob.id, data: archivedJob },
          { id: job.id, data: job },
        ]);
      }
      if (url.pathname === "/jobs/state" && !init?.method) {
        return Response.json([archivedState, state]);
      }
      if (url.pathname === `/jobs/${job.id}/state` && init?.method === "PATCH") {
        expect(new Headers(init.headers).get("If-Match")).toBe('"4"');
        return Response.json({
          ...state,
          archived: true,
          archivedAt: "2026-09-01T11:00:00Z",
          revision: 5,
        });
      }
      throw new Error(`Unhandled ${init?.method ?? "GET"} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useJobs(), { wrapper });

    await waitFor(() => expect(result.current.jobs).toHaveLength(2));
    await act(async () => {
      await result.current.patchState(job.id, { archived: true });
    });

    await waitFor(() => expect(result.current.archivedJobIds).toEqual(
      expect.arrayContaining([archivedJob.id, job.id]),
    ));
    expect(result.current.jobs.find((item) => item.id === job.id)?.archived).toBe(true);
    expect(fetchMock.mock.calls.some(([input, init]) => (
      new URL(String(input)).pathname === `/jobs/${job.id}/state`
      && init?.method === "PATCH"
    ))).toBe(true);
  });

  it("restores an archived vacancy from server state after remount", async () => {
    const job = demoJobs[0];
    let serverState = {
      jobId: job.id,
      saved: false,
      archived: false,
      dismissed: false,
      savedAt: null,
      archivedAt: null as string | null,
      dismissedAt: null,
      updatedAt: "2026-09-01T10:00:00Z",
      revision: 1,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      if (url.pathname === "/jobs" && !init?.method) {
        return Response.json([{ id: job.id, data: { ...job, archived: false } }]);
      }
      if (url.pathname === "/jobs/state" && !init?.method) {
        return Response.json([serverState]);
      }
      if (url.pathname === `/jobs/${job.id}/state` && init?.method === "PATCH") {
        serverState = {
          ...serverState,
          archived: true,
          archivedAt: "2026-09-01T11:00:00Z",
          updatedAt: "2026-09-01T11:00:00Z",
          revision: 2,
        };
        return Response.json(serverState);
      }
      throw new Error(`Unhandled ${init?.method ?? "GET"} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const mounted = renderHook(() => useJobs(), { wrapper });

    await waitFor(() => expect(mounted.result.current.jobs).toHaveLength(1));
    await act(async () => {
      await mounted.result.current.patchState(job.id, { archived: true });
    });
    await waitFor(() => expect(mounted.result.current.jobs[0]?.archived).toBe(true));

    mounted.unmount();
    const reloaded = renderHook(() => useJobs(), { wrapper });

    await waitFor(() => expect(reloaded.result.current.jobs[0]?.archived).toBe(true));
    expect(reloaded.result.current.archivedJobIds).toContain(job.id);
  });
});
