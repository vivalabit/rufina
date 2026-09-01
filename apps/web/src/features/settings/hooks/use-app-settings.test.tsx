import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "@/shared/api/query-client";

import { defaultAppSettings } from "../model/defaults";
import { useAppSettings } from "./use-app-settings";

afterEach(() => vi.unstubAllGlobals());

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={createQueryClient()}>{children}</QueryClientProvider>;
}

describe("useAppSettings", () => {
  it("loads settings and replaces the cache with the save response", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      return Response.json({
        ...defaultAppSettings,
        has_brightdata_api_key: method === "PUT",
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useAppSettings(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.settings.has_brightdata_api_key).toBe(false);

    await act(async () => {
      await result.current.connection.save({ brightdata_api_key: "secret" });
    });
    await waitFor(() => expect(result.current.connection.status).toBe("ready"));
    expect(result.current.settings.has_brightdata_api_key).toBe(true);
    expect(fetchMock).toHaveBeenLastCalledWith(
      expect.stringContaining("/settings"),
      expect.objectContaining({ method: "PUT" }),
    );
  });
});
