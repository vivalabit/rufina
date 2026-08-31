import { describe, expect, it } from "vitest";

import { formatFileSize } from "./files";

describe("formatFileSize", () => {
  it("formats bytes, kilobytes, and megabytes", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(1_536)).toBe("2 KB");
    expect(formatFileSize(1_572_864)).toBe("1.5 MB");
  });
});
