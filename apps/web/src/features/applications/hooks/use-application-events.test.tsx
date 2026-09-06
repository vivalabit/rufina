import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "@/shared/api/query-client";

import { useApplicationEvents } from "./use-application-events";

afterEach(() => vi.unstubAllGlobals());
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={createQueryClient()}>{children}</QueryClientProvider>;
}

function eventPayload(title: string, revision: number) {
  const event = {
    id: "event-1",
    applicationId: "application-1",
    type: "interview",
    status: "scheduled",
    title,
    startsAt: "2026-09-02T10:00:00Z",
    durationMinutes: 45,
    timezone: "Europe/Zurich",
    location: "Video call",
    notes: "",
  };
  return {
    id: event.id,
    application_id: event.applicationId,
    data: event,
    revision,
  };
}

describe("useApplicationEvents", () => {
  it("loads current events and protects optimistic patches with If-Match", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      if (url.pathname === "/applications/events" && !init?.method) {
        return Response.json([eventPayload("Initial interview", 3)]);
      }
      if (url.pathname === "/applications/events/event-1" && init?.method === "PATCH") {
        return Response.json(eventPayload("Updated interview", 4));
      }
      if (url.pathname === "/applications/events/event-1" && init?.method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      throw new Error(`Unhandled ${init?.method ?? "GET"} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useApplicationEvents(), { wrapper });

    await waitFor(() => expect(result.current.events).toHaveLength(1));
    await act(async () => {
      await result.current.upsert({
        ...result.current.events[0],
        title: "Updated interview",
      });
    });

    await waitFor(() => expect(result.current.events[0]?.title).toBe("Updated interview"));
    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(patchCall?.[1]?.headers).toMatchObject({ "If-Match": '"3"' });

    await act(async () => {
      await result.current.remove("event-1");
    });
    const deleteCall = fetchMock.mock.calls.find(([, init]) => init?.method === "DELETE");
    expect(deleteCall?.[1]?.headers).toMatchObject({ "If-Match": '"4"' });
    await waitFor(() => expect(result.current.events).toHaveLength(0));
  });
});
