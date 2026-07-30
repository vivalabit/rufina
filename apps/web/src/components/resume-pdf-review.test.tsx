import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ResumePdfReview,
  ResumeTemplatePicker,
  type ResumeTemplate,
  type ResumePdfDocument,
} from "@/components/resume-pdf-review";

const classicDesign = {
  accentColor: "#2B2B2B",
  fontFamily: "Georgia",
  fontScale: 1,
  density: "standard" as const,
  pageMargins: { top: 15, right: 15, bottom: 15, left: 15 },
  headingStyle: "underlined",
  skillsStyle: "inline",
  sidebarWidth: 0,
  sidebarSections: [],
};

const templates: ResumeTemplate[] = [
  {
    id: "classic_single",
    kind: "bundled",
    name: "Classic Single",
    description: "Traditional single-column resume.",
    layout: "single_column",
    columns: 1,
    baseTemplateId: "classic_single",
    designJson: classicDesign,
  },
  {
    id: "modern_single",
    kind: "bundled",
    name: "Modern Single",
    description: "Modern single-column resume.",
    layout: "single_column",
    columns: 1,
    baseTemplateId: "modern_single",
    designJson: {
      ...classicDesign,
      accentColor: "#176B87",
      fontFamily: "Inter",
      headingStyle: "accent-rule",
      skillsStyle: "pills",
    },
  },
  {
    id: "modern_two_column",
    kind: "bundled",
    name: "Modern Two Column",
    description: "Modern two-column resume.",
    layout: "two_column",
    columns: 2,
    baseTemplateId: "modern_two_column",
    designJson: {
      ...classicDesign,
      accentColor: "#243B53",
      fontFamily: "Inter",
      density: "compact",
      headingStyle: "accent-rule",
      skillsStyle: "pills",
      sidebarWidth: 32,
      sidebarSections: ["skills", "education"],
    },
  },
];

const customTemplate: ResumeTemplate = {
  ...templates[2],
  id: "4ce57ea1-74a2-44cb-90c2-bfe24c549233",
  kind: "custom",
  name: "My Swiss CV",
  description: "Personal design based on Modern Two Column.",
  version: 2,
  designJson: {
    ...templates[2].designJson,
    accentColor: "#8A1538",
  },
};

function pdfDocument(
  id = "pdf-document-classic",
  templateId = "classic_single",
  templateVersion = "1.0.0",
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
          templateVersion,
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

function imaginatorPdfDocument(): ResumePdfDocument {
  const document = pdfDocument("pdf-document-imaginator");
  const version = document.versions[0];
  return {
    ...document,
    versions: [
      {
        ...version,
        artifact: {
          ...version.artifact!,
          sourceAtsFinalReviewId: null,
          sourceImaginatorResumeId: "imaginator-1",
          stageResults: {
            generationMode: "imaginator",
            claimLedger: [
              {
                path: "summary",
                text: "Built globally distributed AI platforms.",
                origin: "synthetic",
                evidenceIds: ["imagination:1"],
              },
              {
                path: "education[0]",
                text: "University of London",
                origin: "locked_source",
                evidenceIds: [],
              },
            ],
            protectedFactsAudit: {
              passed: true,
              auditedClaimCount: 18,
              promptVersion: "imaginator-protected-facts-audit-v1",
              model: "gpt-5.6-terra",
            },
          },
          provenance: {
            generationMode: "imaginator",
            syntheticClaimCount: 1,
            lockedClaimCount: 1,
            resumeMasterVersionId: "master-version-7",
            imaginatorConstraintsVersion: "imaginator-locks-v1",
          },
        },
      },
    ],
  };
}

describe("ResumeTemplatePicker", () => {
  it("groups personal and built-in templates and previews custom tokens", () => {
    const onChange = vi.fn();
    render(
      <ResumeTemplatePicker
        apiBaseUrl="http://localhost:8000"
        templates={[customTemplate, ...templates]}
        selectedId="modern_two_column"
        onChange={onChange}
      />,
    );

    const selector = screen.getByRole("combobox", { name: "Resume template" });
    expect(within(selector).getAllByRole("option")).toHaveLength(4);
    expect(
      within(selector).getByRole("group", { name: "My templates" }),
    ).toBeInTheDocument();
    expect(
      within(selector).getByRole("group", { name: "Built-in" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Use My Swiss CV resume template",
      }),
    ).toBeInTheDocument();
    for (const template of [customTemplate, ...templates]) {
      expect(
        screen.getByTestId(`resume-template-thumbnail-${template.id}`),
      ).toHaveClass("aspect-[9/16]");
      expect(
        screen.getByTestId(`resume-template-thumbnail-${template.id}`)
          .parentElement,
      ).toHaveClass("max-w-[9rem]");
      expect(
        screen.getByRole("img", {
          name: `${template.name} resume template preview`,
        }),
      ).toHaveAttribute(
        "src",
        `http://localhost:8000/resume-templates/${template.id}/thumbnail?version=${template.version ?? template.baseTemplateId}&format=9x16`,
      );
    }
    expect(screen.queryByText("Allowed theme")).not.toBeInTheDocument();
    expect(screen.queryByText("A4")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/User HTML, CSS, and DOCX templates are never accepted/),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Use My Swiss CV resume template",
      }),
    );
    expect(onChange).toHaveBeenCalledWith(customTemplate.id);
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
        return new Response("%PDF-1.7", {
          headers: { "Content-Type": "application/pdf" },
        });
      }
      throw new Error(`Unhandled request: ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ResumePdfReview
        apiBaseUrl="http://localhost:8000"
        applicationId="application-1"
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
    expect(screen.getByRole("link", { name: "Download DOCX" })).toHaveAttribute(
      "href",
      "http://localhost:8000/resume-tailoring/ats-final-review/ats-review-1/docx?templateId=classic_single",
    );
    expect(screen.getByRole("link", { name: "Download DOCX" })).toHaveAttribute(
      "download",
      "Ada-Lovelace-resume.docx",
    );

    fireEvent.click(screen.getByRole("tab", { name: "Diff · 1" }));
    expect(screen.getByText("Wrote technical notes.")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Published the first algorithm for the Analytical Engine.",
      ),
    ).toBeInTheDocument();
  });

  it("labels Imaginator claims and exposes locked-fact provenance", async () => {
    const detail = imaginatorPdfDocument();
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const url = new URL(String(input));
        if (url.pathname === "/documents/pdf-document-imaginator") {
          return Response.json(detail);
        }
        if (url.pathname === "/documents/pdf-document-imaginator/download") {
          return new Response("%PDF-1.7");
        }
        throw new Error(`Unhandled request: ${url.pathname}`);
      }),
    );

    render(
      <ResumePdfReview
        apiBaseUrl="http://localhost:8000"
        applicationId="application-1"
        document={detail}
        templates={templates}
        selectedTemplateId="classic_single"
        onDocumentReady={vi.fn()}
      />,
    );

    expect(
      await screen.findByTitle("Resume PDF preview"),
    ).toHaveAttribute("src", "blob:resume-preview");
    expect(
      screen.getByText("Imaginator draft · contains AI-invented claims"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Invented claims · 1" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Built globally distributed AI platforms."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "ATS scan" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download DOCX" })).toHaveAttribute(
      "href",
      "http://localhost:8000/resume-tailoring/imaginator/imaginator-1/docx?templateId=classic_single",
    );

    fireEvent.click(screen.getByRole("tab", { name: "Provenance" }));
    expect(screen.getByText("Locked source facts")).toBeInTheDocument();
    expect(screen.getByText("Passed · 18 claims")).toBeInTheDocument();
    expect(screen.getByText("master-version-7")).toBeInTheDocument();
    expect(screen.getByText("imaginator-locks-v1")).toBeInTheDocument();
  });

  it("renders a custom UUID from the saved FinalResume and switches artifacts", async () => {
    const classic = pdfDocument();
    const modern = pdfDocument("pdf-document-modern", customTemplate.id, "2");
    const onDocumentReady = vi.fn();
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = new URL(String(input));
      if (url.pathname === "/documents/pdf-document-classic") {
        return Response.json(classic);
      }
      if (url.pathname === "/documents/pdf-document-classic/download") {
        return new Response("%PDF-classic");
      }
      if (url.pathname === "/resume-tailoring/ats-final-review/ats-review-1/pdf") {
        return new Response("%PDF-modern", {
          headers: { "X-Rufina-Document-Id": "pdf-document-modern" },
        });
      }
      if (url.pathname === "/documents/pdf-document-modern/attachments") {
        return Response.json(modern);
      }
      throw new Error(`Unhandled request: ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ResumePdfReview
        apiBaseUrl="http://localhost:8000"
        applicationId="application-1"
        document={classic}
        templates={[customTemplate, ...templates]}
        selectedTemplateId={customTemplate.id}
        onDocumentReady={onDocumentReady}
      />,
    );

    const renderButton = await screen.findByRole("button", {
      name: "Render My Swiss CV",
    });
    fireEvent.click(renderButton);

    await waitFor(() => expect(onDocumentReady).toHaveBeenCalledWith(modern));
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes(
          `/resume-tailoring/ats-final-review/ats-review-1/pdf?templateId=${customTemplate.id}`,
        ),
      ),
    ).toBe(true);
    expect(screen.getByText("My Swiss CV · v2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download PDF" })).toHaveAttribute(
      "href",
      "http://localhost:8000/documents/pdf-document-modern/download",
    );
  });

  it("reports a deleted custom template and asks the picker to fall back", async () => {
    const classic = pdfDocument();
    const onTemplateUnavailable = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const url = new URL(String(input));
        if (url.pathname === "/documents/pdf-document-classic") {
          return Response.json(classic);
        }
        if (url.pathname === "/documents/pdf-document-classic/download") {
          return new Response("%PDF-classic");
        }
        if (
          url.pathname ===
          "/resume-tailoring/ats-final-review/ats-review-1/pdf"
        ) {
          return Response.json(
            { detail: "Resume template not found" },
            { status: 404 },
          );
        }
        throw new Error(`Unhandled request: ${url.pathname}`);
      }),
    );

    render(
      <ResumePdfReview
        apiBaseUrl="http://localhost:8000"
        applicationId="application-1"
        document={classic}
        templates={[customTemplate, ...templates]}
        selectedTemplateId={customTemplate.id}
        onDocumentReady={vi.fn()}
        onTemplateUnavailable={onTemplateUnavailable}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Render My Swiss CV" }),
    );
    expect(
      await screen.findByText(
        "This resume template was deleted or is no longer available. Choose another template.",
      ),
    ).toBeInTheDocument();
    expect(onTemplateUnavailable).toHaveBeenCalledWith(customTemplate.id);
  });
});
