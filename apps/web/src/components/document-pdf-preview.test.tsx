import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentPdfPreview } from "@/components/document-pdf-preview";

describe("DocumentPdfPreview", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: vi.fn(() => "blob:cover-letter-preview"),
        revokeObjectURL: vi.fn(),
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the selected version and displays PDF and DOCX downloads", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => (
      new Response(new Blob(["%PDF-1.7"]), {
        headers: { "Content-Type": "application/pdf" },
      })
    ));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <DocumentPdfPreview
        apiBaseUrl="http://localhost:8000"
        label="Cover letter"
        document={{
          id: "cover-letter-1",
          title: "Cover letter · Acme",
          currentVersion: 3,
          versions: [
            {
              version: 3,
              artifact: { fileName: "Acme-cover-letter.docx" },
            },
          ],
        }}
      />,
    );

    expect(
      await screen.findByTitle("Cover letter PDF preview"),
    ).toHaveAttribute("src", "blob:cover-letter-preview");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/documents/cover-letter-1/pdf?version=3",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(screen.getByRole("link", { name: "Download PDF" })).toHaveAttribute(
      "href",
      "http://localhost:8000/documents/cover-letter-1/pdf",
    );
    expect(screen.getByRole("link", { name: "Download PDF" })).toHaveAttribute(
      "download",
      "Acme-cover-letter.pdf",
    );
    expect(screen.getByRole("link", { name: "Download DOCX" })).toHaveAttribute(
      "href",
      "http://localhost:8000/documents/cover-letter-1/download",
    );
  });
});
