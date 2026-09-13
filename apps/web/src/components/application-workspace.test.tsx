import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  createWorkspaceApplication,
  installApplicationWorkspaceApiMock,
  renderApplicationWorkspace,
} from "@/test/application-workspace-harness";

function storedDocument(overrides: Record<string, unknown> = {}) {
  return {
    id: "stored-document-1",
    type: "cover_letter",
    title: "Saved cover letter",
    jobId: "job-product-designer",
    applicationIds: ["application"],
    currentVersion: 2,
    createdAt: "2026-07-24T10:00:00.000Z",
    updatedAt: "2026-07-25T10:00:00.000Z",
    generationFingerprint: "old-match-fingerprint",
    currentGenerationFingerprint: null,
    generationModel: "gpt-5",
    inputVersions: {},
    versionsTotal: 2,
    versionsHasMore: false,
    versions: [
      {
        id: "stored-version-2",
        version: 2,
        content: "Saved content",
        createdAt: "2026-07-25T10:00:00.000Z",
        hasRenderedArtifact: true,
        artifact: {
          fileName: "saved-cover-letter.docx",
          contentType:
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
        factualValidation: {},
        visualValidation: {},
        diff: [],
      },
    ],
    ...overrides,
  };
}

describe("ApplicationWorkspace", () => {
  beforeEach(() => {
    installApplicationWorkspaceApiMock();
  });

  it("shows an empty state when no application is selected", () => {
    const { props } = renderApplicationWorkspace(null);

    expect(
      screen.getByRole("heading", { name: "No application selected" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Applications" }));
    expect(props.onBack).toHaveBeenCalledOnce();
  });

  it("renders a compact vacancy card with the application status", () => {
    renderApplicationWorkspace(
      createWorkspaceApplication({ status: "interview" }),
    );

    expect(
      screen.getByRole("heading", { name: "Senior Product Designer" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Acme Labs")).toBeInTheDocument();
    expect(screen.getByText("Zurich, Switzerland")).toBeInTheDocument();
    expect(screen.getByText("Full-time")).toBeInTheDocument();
    expect(screen.getByText("Interview")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Lead product discovery and delivery for a growing B2B platform.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Document pack" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Existing documents" }),
    ).toBeInTheDocument();
  });

  it("restores document preparation settings and saves changes", async () => {
    const { props } = renderApplicationWorkspace(
      createWorkspaceApplication({
        documentPreparation: {
          documentTypes: ["cover_letter"],
          language: "German",
          formatting: {
            pageSize: "Letter",
            resumeTemplateId: "modern_single",
            resumeMaxPages: 1,
            coverLetterTemplateId: "4a9260bb-dc6a-5b9d-8a3a-1caa1e1433e8",
          },
          userPreferences: "Use a direct tone.",
        },
      }),
    );

    expect(screen.getByRole("checkbox", { name: "Tailored CV" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Cover letter" })).toBeChecked();
    expect(screen.getByRole("combobox", { name: "Document language" })).toHaveValue("German");
    expect(screen.getByRole("combobox", { name: "Page size" })).toHaveValue("Letter");
    expect(screen.getByRole("textbox", { name: "Additional document instructions" })).toHaveValue(
      "Use a direct tone.",
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Document language" }), {
      target: { value: "English" },
    });

    await waitFor(() => expect(props.onPreparationSettingsChange).toHaveBeenCalledWith(
      "application",
      expect.objectContaining({
        documentTypes: ["cover_letter"],
        language: "English",
        formatting: expect.objectContaining({ pageSize: "Letter" }),
      }),
    ));
    expect(await screen.findByText("Settings saved")).toBeInTheDocument();
  });

  it("sends the selected pack through the generation contract", async () => {
    let generationRequest: unknown = null;
    installApplicationWorkspaceApiMock({
      requestHandler: (url, method, init) => {
        if (
          url.pathname === "/applications/application/generation"
          && method === "POST"
        ) {
          generationRequest = JSON.parse(String(init?.body));
          return Response.json({
            executionId: "generation-1",
            state: "completed",
            documents: [
              {
                documentType: "tailored_resume",
                state: "completed",
                files: [
                  {
                    fileName: "tailored-cv.pdf",
                    contentType: "application/pdf",
                    downloadUrl: "/generated/tailored-cv.pdf",
                  },
                ],
                error: null,
              },
            ],
            error: null,
          });
        }
        return undefined;
      },
    });
    renderApplicationWorkspace(
      createWorkspaceApplication({
        documentPreparation: {
          documentTypes: ["tailored_resume"],
          language: "German",
          formatting: {
            pageSize: "A4",
            resumeTemplateId: "modern_single",
            resumeMaxPages: 1,
            coverLetterTemplateId: "",
          },
          userPreferences: "Keep it concise.",
        },
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Generate documents" }));

    expect(await screen.findByText("Generation finished")).toBeInTheDocument();
    expect(generationRequest).toEqual({
      documentTypes: ["tailored_resume"],
      language: "German",
      formattingParameters: {
        tailored_resume: {
          pageSize: "A4",
          templateId: "modern_single",
          maxPages: 1,
        },
      },
      userPreferences: "Keep it concise.",
    });
    expect(screen.getByRole("link", { name: "Download tailored-cv.pdf" })).toHaveAttribute(
      "href",
      "/generated/tailored-cv.pdf",
    );
  });

  it("normalizes jobs.ch vacancy links", () => {
    renderApplicationWorkspace(
      createWorkspaceApplication({
        job: {
          applyUrl:
            "https://www.jobs.ch/en/vacancies/detail/de866122-37da-4c9d-ad34-c2fa0bc45d5f/apply/",
        },
      }),
    );

    expect(screen.getByRole("link", { name: "View vacancy" })).toHaveAttribute(
      "href",
      "https://www.jobs.ch/en/vacancies/detail/de866122-37da-4c9d-ad34-c2fa0bc45d5f/",
    );
  });

  it("lists existing application documents with their actions", () => {
    renderApplicationWorkspace(
      createWorkspaceApplication({
        documents: [
          {
            id: "document-1",
            title: "Tailored CV",
            fileName: "alex-morgan-cv.pdf",
            fileSize: "128 KB",
            fileType: "application/pdf",
            uploadedAt: "2026-07-25T10:00:00.000Z",
            downloadUrl: "/documents/document-1/download",
          },
          {
            id: "document-2",
            title: "Cover letter",
            fileName: "alex-morgan-letter.docx",
            fileSize: "64 KB",
            fileType:
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            uploadedAt: "2026-07-26T10:00:00.000Z",
            downloadUrl: "/documents/document-2/download",
          },
        ],
      }),
    );

    const documents = screen.getByRole("region", {
      name: "Existing documents",
    });

    expect(within(documents).getByText("Tailored CV")).toBeInTheDocument();
    expect(within(documents).getByText("Cover letter")).toBeInTheDocument();
    expect(
      within(documents).getByRole("link", { name: "Download Tailored CV" }),
    ).toHaveAttribute("href", "/documents/document-1/download");
    expect(
      within(documents).getByRole("link", { name: "Download Cover letter" }),
    ).toHaveAttribute("href", "/documents/document-2/download");
    expect(
      screen.getByRole("button", { name: "Generate documents" }),
    ).toBeEnabled();
  });

  it("does not render any legacy preparation content", () => {
    renderApplicationWorkspace(createWorkspaceApplication());

    expect(screen.queryByText("Your application angle")).not.toBeInTheDocument();
    expect(screen.queryByText("Required confirmations")).not.toBeInTheDocument();
    expect(screen.queryByText("CV direction")).not.toBeInTheDocument();
    expect(screen.queryByText("Cover letter direction")).not.toBeInTheDocument();
    expect(screen.queryByText("CV generation mode")).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "Turn complex B2B workflows into clear, validated product experiences.",
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "Do not imply unverified people-management experience",
      ),
    ).not.toBeInTheDocument();
  });

  it("loads saved files without requesting match or confirmation data", async () => {
    const document = storedDocument();
    const fetchMock = installApplicationWorkspaceApiMock({
      documents: [document],
      requestHandler: (url, method) => {
        if (
          url.pathname === "/documents/stored-document-1/pdf"
          && method === "GET"
        ) {
          return new Response(new Blob(["%PDF-1.7"], {
            type: "application/pdf",
          }));
        }
        return undefined;
      },
    });
    renderApplicationWorkspace(createWorkspaceApplication());

    expect(await screen.findByText("Saved cover letter")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open Saved cover letter" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Download Saved cover letter" }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining("/documents/stored-document-1/download"),
    );

    fireEvent.click(screen.getByText("Version history · 2"));
    expect(
      screen.getByRole("button", {
        name: "Open Saved cover letter version 2",
      }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Open Saved cover letter" }),
    );
    expect(
      await screen.findByRole("region", {
        name: "Cover letter PDF preview panel",
      }),
    ).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/documents/stored-document-1/pdf?version=2"),
      expect.objectContaining({ cache: "no-store" }),
    ));

    const requestedPaths = fetchMock.mock.calls.map(([input]) => String(input));
    expect(requestedPaths.some((path) => path.includes("/confirmations"))).toBe(false);
    expect(requestedPaths.some((path) => path.includes("/ai-match"))).toBe(false);
    expect(requestedPaths.some((path) => path.includes("/profile/master-resume"))).toBe(false);
  });

  it("loads older document versions independently", async () => {
    const document = storedDocument({ versionsHasMore: true });
    installApplicationWorkspaceApiMock({
      documents: [document],
      requestHandler: (url, method) => {
        if (
          url.pathname === "/documents/stored-document-1/versions"
          && method === "GET"
        ) {
          return Response.json({
            items: [
              {
                id: "stored-version-1",
                version: 1,
                content: "Older content",
                createdAt: "2026-07-24T10:00:00.000Z",
                hasRenderedArtifact: true,
                artifact: {
                  fileName: "saved-cover-letter-v1.docx",
                  contentType:
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                },
                factualValidation: {},
                visualValidation: {},
                diff: [],
              },
            ],
            total: 2,
          });
        }
        return undefined;
      },
    });
    renderApplicationWorkspace(createWorkspaceApplication());

    fireEvent.click(await screen.findByText("Version history · 2"));
    fireEvent.click(screen.getByRole("button", { name: "Load older versions" }));

    expect(
      await screen.findByRole("button", {
        name: "Open Saved cover letter version 1",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "Download Saved cover letter version 1",
      }),
    ).toHaveAttribute("href", expect.stringContaining("version=1"));
  });

  it("attaches a saved vacancy document without preparation analysis", async () => {
    const document = storedDocument({ applicationIds: [] });
    const fetchMock = installApplicationWorkspaceApiMock({
      requestHandler: (url, method) => {
        if (url.pathname === "/documents" && method === "GET") {
          return Response.json(
            url.searchParams.has("applicationId") ? [] : [document],
          );
        }
        if (
          url.pathname === "/documents/stored-document-1/attachments"
          && method === "POST"
        ) {
          return Response.json({
            ...document,
            applicationIds: ["application"],
          });
        }
        return undefined;
      },
    });
    const { props } = renderApplicationWorkspace(
      createWorkspaceApplication(),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Attach" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/documents/stored-document-1/attachments"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ applicationId: "application" }),
      }),
    ));
    expect(props.onDocumentAttached).toHaveBeenCalledWith(
      "application",
      expect.objectContaining({
        artifactId: "stored-document-1",
        fileName: "saved-cover-letter.docx",
      }),
    );
    expect(screen.queryByText("Required confirmations")).not.toBeInTheDocument();
  });
});
