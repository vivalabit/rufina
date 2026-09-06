import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "@/shared/api/query-client";

import { useApplications } from "./use-applications";

afterEach(() => vi.unstubAllGlobals());
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={createQueryClient()}>{children}</QueryClientProvider>;
}

function applicationPayload(notes: string, revision: number) {
  return {
    id: "application-1",
    data: {
      id: "application-1",
      status: "applied",
      appliedAt: "2026-08-31T10:00:00Z",
      nextStep: "",
      notes,
      job: {
        id: "job-1",
        title: "Engineer",
        company: "Example AG",
        location: "Zurich",
        type: "Full-time",
        salary: "Not specified",
        posted: "Today",
        experience: "Mid-level",
        department: "Engineering",
        match: 80,
        logo: "manual",
        overview: "Build reliable systems.",
        responsibilities: ["Build systems"],
        requirements: ["Engineering experience"],
        skills: ["TypeScript"],
      },
    },
    created_at: "2026-08-31T10:00:00Z",
    updated_at: "2026-08-31T10:00:00Z",
    revision,
  };
}

describe("useApplications", () => {
  it("loads documents and protects optimistic patches with If-Match", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      if (url.pathname === "/applications" && !init?.method) {
        return Response.json([applicationPayload("Initial", 1)]);
      }
      if (url.pathname.startsWith("/documents")) return Response.json([]);
      if (url.pathname === "/applications/application-1" && init?.method === "PATCH") {
        return Response.json(applicationPayload("Updated", 2));
      }
      if (url.pathname === "/applications/application-1" && init?.method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      throw new Error(`Unhandled ${init?.method ?? "GET"} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useApplications(), { wrapper });

    await waitFor(() => expect(result.current.applications).toHaveLength(1));
    await act(async () => {
      await result.current.upsert({
        ...result.current.applications[0],
        notes: "Updated",
      });
    });
    await waitFor(() => expect(result.current.applications[0]?.notes).toBe("Updated"));

    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(patchCall?.[1]?.headers).toMatchObject({ "If-Match": '"1"' });

    await act(async () => {
      await result.current.remove("application-1");
    });
    const deleteCall = fetchMock.mock.calls.find(([, init]) => init?.method === "DELETE");
    expect(deleteCall?.[1]?.headers).toMatchObject({ "If-Match": '"2"' });
    await waitFor(() => expect(result.current.applications).toHaveLength(0));
  });
});
