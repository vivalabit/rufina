import { describe, expect, it } from "vitest";

import { normalizeExternalUrl } from "./urls";

describe("normalizeExternalUrl", () => {
  it("normalizes web and email values while rejecting unsupported schemes", () => {
    expect(normalizeExternalUrl(" example.com/path ")).toBe("https://example.com/path");
    expect(normalizeExternalUrl("person@example.com")).toBe("mailto:person@example.com");
    expect(normalizeExternalUrl("javascript:alert(1)")).toBe("");
  });
});
