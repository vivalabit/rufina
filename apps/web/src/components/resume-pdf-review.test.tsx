import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ResumePdfReview,
  ResumeTemplatePicker,
  type BundledResumeTemplate,
  type ResumePdfDocument,
} from "@/components/resume-pdf-review";

const templates: BundledResumeTemplate[] = [
  {
    id: "classic_single",
    name: "Classic Single",
    description: "Traditional single-column resume.",
    layout: "single_column",
    columns: 1,
  },
  {
    id: "modern_single",
    name: "Modern Single",
    description: "Modern single-column resume.",
    layout: "single_column",
    columns: 1,
  },
  {
    id: "modern_two_column",
    name: "Modern Two Column",
    description: "Modern two-column resume.",
    layout: "two_column",
    columns: 2,
  },
];

function pdfDocument(
  id = "pdf-document-classic",
  templateId = "classic_single",
): ResumePdfDocument {
  return {
    id,
    type: "tailored_resume",
    title: "Ada Lovelace resume",
    currentVersion: 1,
    versions: [
      {
        id: `${id}-version`,
        version: 1,
        content: "{}",
        createdAt: "2026-07-25T10:00:00.000Z",
        hasRenderedArtifact: true,
        artifact: {
          fileName: "Ada-Lovelace-resume.pdf",
          contentType: "application/pdf",
          templateId,
          templateVersion: "1.0.0",
          sourceAtsFinalReviewId: "ats-review-1",
          stageResults: {
            experienceRewrite: {
              experiences: [
                {
                  company: "Analytical Engines",
                  bullets: [{ id: "bullet-1", text: "Wrote technical notes." }],
                },
              ],
            },
            atsFinalReview: {
              atsScan: {
                skippedSections: [
                  {
                    section: "summary",
                    reason: "The opening was too generic.",
                    action: "Lead with role-specific evidence.",
                  },
                ],
              },
              finalResume: {
                experiences: [
                  {
                    company: "Analytical Engines",
                    bullets: [
                      {
                        id: "bullet-1",
                        text: "Published the first algorithm for the Analytical Engine.",
                      },
                    ],
                  },
                ],
              },
            },
          },
        },
        factualValidation: { status: "passed" },
        visualValidation: { status: "passed" },
        diff: [],
      },
    ],
  };
}

describe("ResumeTemplatePicker", () => {
  it("offers only bundled templates and exposes the allowed theme", () => {
    const onChange = vi.fn();
    render(
      <ResumeTemplatePicker
        templates={templates}
        selectedId="modern_two_column"
        onChange={onChange}
      />,
    );

    const selector = screen.getByRole("combobox", { name: "Resume template" });
    expect(within(selector).getAllByRole("option")).toHaveLength(3);
    expect(screen.getByText("Navy")).toBeInTheDocument();
    expect(screen.getByText("A4")).toBeInTheDocument();
    expect(screen.getByText("Two column")).toBeInTheDocument();
    expect(screen.getByText(/Custom HTML, CSS, and DOCX templates are not accepted/)).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Use Modern Single resume template",
      }),
    );
    expect(onChange).toHaveBeenCalledWith("modern_single");
  });
});

describe("ResumePdfReview", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: vi.fn(() => "blob:resume-preview"),
        revokeObjectURL: vi.fn(),
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the saved PDF and shows ATS scan and stage diff", async () => {
    const detail = pdfDocument();
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = new URL(String(input));
      if (url.pathname === "/documents/pdf-document-classic") {
        return Response.json(detail);
      }
      if (url.pathname === "/documents/pdf-document-classic/download") {
        return new Response(new Blob(["%PDF-1.7"]), {
          headers: { "Content-Type": "application/pdf" },
        });
      }
      throw new Error(`Unhandled request: ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ResumePdfReview
        apiBaseUrl="http://localhost:8000"
        document={detail}
        templates={templates}
        selectedTemplateId="classic_single"
        onDocumentReady={vi.fn()}
      />,
    );

    expect(
      await screen.findByTitle("Resume PDF preview"),
    ).toHaveAttribute("src", "blob:resume-preview");
    expect(screen.getByText("The opening was too generic.")).toBeInTheDocument();
    expect(screen.getByText("Lead with role-specific evidence.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download PDF" })).toHaveAttribute(
      "href",
      "http://localhost:8000/documents/pdf-document-classic/download",
    );

    fireEvent.click(screen.getByRole("tab", { name: "Diff · 1" }));
    expect(screen.getByText("Wrote technical notes.")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Published the first algorithm for the Analytical Engine.",
      ),
    ).toBeInTheDocument();
  });

  it("renders another bundled template and switches to its saved artifact", async () => {
    const classic = pdfDocument();
    const modern = pdfDocument("pdf-document-modern", "modern_single");
    const onDocumentReady = vi.fn();
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = new URL(String(input));
      if (url.pathname === "/documents/pdf-document-classic") {
        return Response.json(classic);
      }
      if (url.pathname === "/documents/pdf-document-classic/download") {
        return new Response(new Blob(["%PDF-classic"]));
      }
      if (url.pathname === "/resume-tailoring/ats-final-review/ats-review-1/pdf") {
        return new Response(new Blob(["%PDF-modern"]), {
          headers: { "X-Rufina-Document-Id": "pdf-document-modern" },
        });
      }
      if (url.pathname === "/documents/pdf-document-modern") {
        return Response.json(modern);
      }
      throw new Error(`Unhandled request: ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ResumePdfReview
        apiBaseUrl="http://localhost:8000"
        document={classic}
        templates={templates}
        selectedTemplateId="modern_single"
        onDocumentReady={onDocumentReady}
      />,
    );

    const renderButton = await screen.findByRole("button", {
      name: "Render Modern Single",
    });
    fireEvent.click(renderButton);

    await waitFor(() => expect(onDocumentReady).toHaveBeenCalledWith(modern));
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes(
          "/resume-tailoring/ats-final-review/ats-review-1/pdf?templateId=modern_single",
        ),
      ),
    ).toBe(true);
    expect(screen.getByText("modern_single · v1.0.0")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download PDF" })).toHaveAttribute(
      "href",
      "http://localhost:8000/documents/pdf-document-modern/download",
    );
  });
});
