import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "@/shared/api/query-client";

import { defaultCandidateProfile } from "../model/defaults";
import { useProfile } from "./use-profile";

afterEach(() => vi.unstubAllGlobals());
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={createQueryClient()}>{children}</QueryClientProvider>;
}

describe("useProfile", () => {
  it("loads the profile and protects saves with the latest ETag", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      if (url.pathname === "/profile/files") return Response.json([]);
      if (url.pathname === "/profile" && init?.method === "PUT") {
        return Response.json(
          { ...defaultCandidateProfile, name: "Alice Updated" },
          { headers: { ETag: '"2"' } },
        );
      }
      return Response.json(
        { ...defaultCandidateProfile, name: "Alice" },
        { headers: { ETag: '"1"' } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useProfile(), { wrapper });

    await waitFor(() => expect(result.current.profile.name).toBe("Alice"));
    await act(async () => {
      await result.current.save({
        ...result.current.profile,
        name: "Alice Updated",
      });
    });

    await waitFor(() => expect(result.current.profile.name).toBe("Alice Updated"));
    const putCall = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(putCall?.[1]?.headers).toMatchObject({ "If-Match": '"1"' });
  });

  it("aborts the initial request when its last consumer unmounts", async () => {
    let aborted = false;
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          aborted = true;
          reject(new DOMException("Aborted", "AbortError"));
        });
      })));

    const { unmount } = renderHook(() => useProfile(), { wrapper });
    unmount();
    await waitFor(() => expect(aborted).toBe(true));
  });
});
