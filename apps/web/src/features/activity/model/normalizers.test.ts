import { describe, expect, it } from "vitest";

import { normalizeStoredLogs } from "./normalizers";

describe("normalizeStoredLogs", () => {
  it("normalizes partial stored entries using injected runtime values", () => {
    const logs = normalizeStoredLogs([{ level: "error", details: "Request failed" }], {
      createId: (prefix) => `${prefix}-generated`,
      now: () => "2026-08-31T12:00:00.000Z",
    });

    expect(logs).toEqual([{
      id: "log-generated",
      timestamp: "2026-08-31T12:00:00.000Z",
      level: "error",
      area: "Application",
      message: "Log entry",
      details: "Request failed",
    }]);
  });

  it("rejects non-array stored values", () => {
    expect(normalizeStoredLogs({}, {
      createId: () => "unused",
      now: () => "unused",
    })).toEqual([]);
  });
});
