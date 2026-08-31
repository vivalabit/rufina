import { describe, expect, it } from "vitest";

import { formatApiErrorDetail, readApiErrorMessage } from "./error";

describe("formatApiErrorDetail", () => {
  it("formats nested validation details without the body prefix", () => {
    expect(formatApiErrorDetail([
      { loc: ["body", "profile", "name"], msg: "Field required" },
      "Retry later",
    ])).toBe("profile.name: Field required; Retry later");
  });

  it("returns an empty string for unsupported values", () => {
    expect(formatApiErrorDetail({ code: "invalid" })).toBe("");
  });
});

describe("readApiErrorMessage", () => {
  it("uses a non-JSON response fallback", async () => {
    const response = {
      json: async () => {
        throw new Error("not json");
      },
    } as unknown as Response;

    await expect(readApiErrorMessage(response, "Request failed")).resolves.toBe("Request failed");
  });
});
