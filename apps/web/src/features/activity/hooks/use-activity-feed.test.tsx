import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { appLogsStorageKey } from "../model/constants";
import { useActivityFeed } from "./use-activity-feed";

beforeEach(() => {
  window.localStorage.clear();
});

describe("useActivityFeed", () => {
  it("hydrates, appends, persists, and clears local activity", async () => {
    window.localStorage.setItem(appLogsStorageKey, JSON.stringify([{
      id: "stored-log",
      timestamp: "2026-08-31T10:00:00.000Z",
      level: "info",
      area: "Jobs",
      message: "Stored",
    }]));

    const { result } = renderHook(() => useActivityFeed());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.entries).toHaveLength(1);

    act(() => {
      result.current.append({
        level: "success",
        area: "Jobs",
        message: "Added",
      });
    });
    await waitFor(() => expect(result.current.entries[0]?.message).toBe("Added"));
    expect(window.localStorage.getItem(appLogsStorageKey)).toContain("Added");

    act(() => result.current.clear());
    await waitFor(() => expect(result.current.entries).toEqual([]));
    expect(window.localStorage.getItem(appLogsStorageKey)).toBe("[]");
  });

  it("drops invalid stored activity and exposes a recoverable error", async () => {
    window.localStorage.setItem(appLogsStorageKey, "not-json");
    const { result } = renderHook(() => useActivityFeed());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.entries).toEqual([]);
    expect(result.current.error?.message).toMatch(/could not be loaded/);
  });
});
