import { describe, expect, it } from "vitest";

import { decodeDataUrl, isInlineDataUrl } from "./data-url";

describe("data URL helpers", () => {
  it("recognizes inline data URLs after whitespace", () => {
    expect(isInlineDataUrl("  DATA:text/plain,hello")).toBe(true);
    expect(isInlineDataUrl("https://example.com/file.txt")).toBe(false);
  });

  it("decodes base64 payload metadata", () => {
    const file = decodeDataUrl("data:text/plain;base64,aGVsbG8=");

    expect(file.type).toBe("text/plain");
    expect(file.size).toBe(5);
  });
});
