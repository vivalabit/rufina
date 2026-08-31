import { describe, expect, it } from "vitest";

import {
  formatApplicationDate,
  formatApplicationEventDate,
  formatApplicationEventTime,
  getApplicationDocumentBadge,
  getApplicationEventTypeLabel,
  getApplicationTimelineEventLabel,
  getVisibleApplicationNotes,
} from "./formatting";

describe("application formatting", () => {
  it("keeps distinct invalid-date fallbacks", () => {
    expect(formatApplicationDate("invalid")).toBe("Not set");
    expect(formatApplicationEventDate("invalid")).toBe("Date TBD");
    expect(formatApplicationEventTime("invalid")).toBe("Time TBD");
  });

  it("uses distinct control and timeline labels", () => {
    expect(getApplicationEventTypeLabel("screening")).toBe("Screening");
    expect(getApplicationTimelineEventLabel("screening")).toBe("Phone screen");
  });

  it("hides only the exact trimmed legacy note", () => {
    expect(getVisibleApplicationNotes("  Moved from Jobs after applying.  ")).toBe("");
    expect(getVisibleApplicationNotes("  Candidate note  ")).toBe("Candidate note");
  });

  it("formats document badges from extension or MIME type", () => {
    const document = {
      id: "document-1",
      kind: "uploaded" as const,
      title: "Resume",
      fileName: "resume.pdf",
      fileSize: "",
      fileType: "application/pdf",
      uploadedAt: "",
      downloadUrl: "/resume.pdf",
    };

    expect(getApplicationDocumentBadge(document)).toBe("PDF");
    expect(
      getApplicationDocumentBadge({
        ...document,
        fileName: "resume",
        fileType: "application/msword",
      }),
    ).toBe("DOC");
  });
});
