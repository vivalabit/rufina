import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createWorkspaceApplication,
  installApplicationWorkspaceApiMock,
  renderApplicationWorkspace,
} from "@/test/application-workspace-harness";
import { defaultDocumentPreparationSettings } from "@/features/applications/model/document-preparation";

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
          submission: {
            tailored_resume: null,
            cover_letter: null,
          },
          latestGeneration: null,
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
          submission: {
            tailored_resume: null,
            cover_letter: null,
          },
          latestGeneration: null,
          userPreferences: "Keep it concise.",
        },
      }),
    );

    await waitFor(() => expect(
      screen.getByRole("button", { name: "Generate documents" }),
    ).toBeEnabled());
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

  it("keeps existing document actions available when generation is unavailable", async () => {
    installApplicationWorkspaceApiMock({
      generationAvailability: {
        available: false,
        code: "generator_unavailable",
        message: "Document generation is not configured yet.",
      },
    });
    renderApplicationWorkspace(createWorkspaceApplication({
      documents: [{
        id: "source-existing-cv",
        sourceId: "existing-cv",
        kind: "uploaded",
        title: "Existing CV",
        fileName: "existing-cv.pdf",
        fileSize: "128 KB",
        fileType: "application/pdf",
        uploadedAt: "2026-09-12T10:00:00.000Z",
        downloadUrl: "/documents/existing-cv/download",
      }],
    }));

    await screen.findByText("Creation awaits the generator");
    expect(screen.getByRole("button", { name: "Generate documents" }))
      .toBeDisabled();
    expect(screen.getAllByText("Unavailable")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Open Existing CV" }))
      .toHaveAttribute("href", "/documents/existing-cv/download?preview=true");
    expect(screen.getByRole("link", { name: "Download Existing CV" }))
      .toHaveAttribute("href", "/documents/existing-cv/download");
    expect(screen.getByRole("button", { name: "Use Existing CV as CV" }))
      .toBeEnabled();
  });

  it("shows per-document progress and prevents a double start", async () => {
    let finishGeneration: ((response: Response) => void) | undefined;
    const pendingGeneration = new Promise<Response>((resolve) => {
      finishGeneration = resolve;
    });
    const fetchMock = installApplicationWorkspaceApiMock({
      requestHandler: (url, method) => {
        if (url.pathname === "/applications/application/generation" && method === "POST") {
          return pendingGeneration;
        }
        return undefined;
      },
    });
    const { props } = renderApplicationWorkspace(
      createWorkspaceApplication({
        documentPreparation: defaultDocumentPreparationSettings,
        documents: [{
          id: "source-existing-letter",
          sourceId: "existing-letter",
          kind: "uploaded",
          title: "Existing letter",
          fileName: "existing-letter.pdf",
          fileSize: "64 KB",
          fileType: "application/pdf",
          uploadedAt: "2026-09-12T10:00:00.000Z",
          downloadUrl: "/documents/existing-letter/download",
        }],
      }),
    );
    const generateButton = screen.getByRole("button", {
      name: "Generate documents",
    });
    await waitFor(() => expect(generateButton).toBeEnabled());

    fireEvent.click(generateButton);
    fireEvent.click(generateButton);

    const resumeState = await screen.findByRole("group", {
      name: "Tailored CV generation status",
    });
    const letterState = screen.getByRole("group", {
      name: "Cover letter generation status",
    });
    expect(within(resumeState).getByText("In progress")).toBeInTheDocument();
    expect(within(letterState).getByText("Queued")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download Existing letter" }))
      .toBeInTheDocument();
    await waitFor(() => expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(1));

    finishGeneration?.(Response.json({
      executionId: "generation-partial",
      state: "completed",
      documents: [
        {
          documentType: "tailored_resume",
          state: "completed",
          files: [{
            fileName: "tailored-cv.pdf",
            contentType: "application/pdf",
            downloadUrl: "/generated/tailored-cv.pdf",
          }],
          error: null,
        },
        {
          documentType: "cover_letter",
          state: "failed",
          files: [],
          error: {
            code: "render_failed",
            message: "The cover letter could not be rendered.",
            retryable: true,
          },
        },
      ],
      error: null,
    }));

    expect(await screen.findByText("Generation finished")).toBeInTheDocument();
    expect(within(resumeState).getByText("Ready")).toBeInTheDocument();
    expect(within(letterState).getByText("Failed")).toBeInTheDocument();
    expect(within(letterState).getByRole("alert"))
      .toHaveTextContent("The cover letter could not be rendered.");
    await waitFor(() => expect(props.onPreparationSettingsChange)
      .toHaveBeenLastCalledWith(
        "application",
        expect.objectContaining({
          latestGeneration: expect.objectContaining({
            executionId: "generation-partial",
            state: "completed",
          }),
        }),
      ));
  });

  it("restores a running generation after reload without allowing a duplicate", async () => {
    const runningGeneration = {
      executionId: "generation-running",
      state: "running" as const,
      documentResults: [
        {
          documentType: "tailored_resume" as const,
          state: "running" as const,
          files: [],
          error: null,
        },
        {
          documentType: "cover_letter" as const,
          state: "queued" as const,
          files: [],
          error: null,
        },
      ],
      error: null,
    };
    const fetchMock = installApplicationWorkspaceApiMock();
    renderApplicationWorkspace(createWorkspaceApplication({
      documentPreparation: {
        ...defaultDocumentPreparationSettings,
        latestGeneration: runningGeneration,
      },
    }));

    expect(screen.getByText("Generation in progress")).toBeInTheDocument();
    const generateButton = screen.getByRole("button", {
      name: "Preparing documents…",
    });
    expect(generateButton).toBeDisabled();
    fireEvent.click(generateButton);
    await waitFor(() => expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
    ).toBe(false));
  });

  it("lists existing application documents with their actions", async () => {
    renderApplicationWorkspace(
      createWorkspaceApplication({
        documents: [
          {
            id: "document-1",
            kind: "uploaded",
            title: "Tailored CV",
            fileName: "alex-morgan-cv.pdf",
            fileSize: "128 KB",
            fileType: "application/pdf",
            uploadedAt: "2026-07-25T10:00:00.000Z",
            downloadUrl: "/documents/document-1/download",
          },
          {
            id: "document-2",
            kind: "uploaded",
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

    expect(within(documents).getAllByText("Tailored CV")).not.toHaveLength(0);
    expect(within(documents).getAllByText("Cover letter")).not.toHaveLength(0);
    expect(
      within(documents).getByRole("link", { name: "Download Tailored CV" }),
    ).toHaveAttribute("href", "/documents/document-1/download");
    expect(
      within(documents).getByRole("link", { name: "Open Tailored CV" }),
    ).toHaveAttribute("href", "/documents/document-1/download?preview=true");
    expect(
      within(documents).getByRole("link", { name: "Download Cover letter" }),
    ).toHaveAttribute("href", "/documents/document-2/download");
    await waitFor(() => expect(
      screen.getByRole("button", { name: "Generate documents" }),
    ).toBeEnabled());
  });

  it("uploads an own file and selects it for submission", async () => {
    const uploaded = {
      id: "source-uploaded-cv",
      sourceId: "uploaded-cv",
      kind: "uploaded" as const,
      title: "Own CV",
      fileName: "own-cv.pdf",
      fileSize: "1 KB",
      fileType: "application/pdf",
      uploadedAt: "2026-09-13T11:00:00.000Z",
      downloadUrl: "/documents/workspace-sources/uploaded-cv/download",
    };
    const { props } = renderApplicationWorkspace(
      createWorkspaceApplication(),
      {
        onUploadDocument: vi.fn().mockResolvedValue(uploaded),
      },
    );
    const file = new File(["%PDF-1.7 own cv"], "own-cv.pdf", {
      type: "application/pdf",
    });

    fireEvent.change(screen.getByLabelText("Upload own document"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(props.onUploadDocument).toHaveBeenCalledWith(
      "application",
      file,
      { fileName: "own-cv.pdf", title: "own cv" },
    ));
    expect(props.onDocumentAttached).toHaveBeenCalledWith(
      "application",
      uploaded,
    );
    await waitFor(() => expect(props.onPreparationSettingsChange).toHaveBeenCalledWith(
      "application",
      expect.objectContaining({
        submission: expect.objectContaining({
          tailored_resume: {
            documentId: "source-uploaded-cv",
            version: null,
          },
        }),
      }),
    ));
  });

  it("replaces a selected uploaded file without changing its selection", async () => {
    const existing = {
      id: "source-existing-cv",
      sourceId: "existing-cv",
      kind: "uploaded" as const,
      title: "Existing CV",
      fileName: "existing-cv.pdf",
      fileSize: "1 KB",
      fileType: "application/pdf",
      uploadedAt: "2026-09-12T11:00:00.000Z",
      downloadUrl: "/documents/workspace-sources/existing-cv/download",
    };
    const replacement = {
      ...existing,
      title: "Updated CV",
      fileName: "updated-cv.pdf",
      uploadedAt: "2026-09-13T11:00:00.000Z",
    };
    const { props } = renderApplicationWorkspace(
      createWorkspaceApplication({
        documents: [existing],
        documentPreparation: {
          documentTypes: ["tailored_resume", "cover_letter"],
          language: "English",
          formatting: {
            pageSize: "A4",
            resumeTemplateId: "classic_single",
            resumeMaxPages: 2,
            coverLetterTemplateId: "",
          },
          submission: {
            tailored_resume: {
              documentId: "source-existing-cv",
              version: null,
            },
            cover_letter: null,
          },
          latestGeneration: null,
          userPreferences: "",
        },
      }),
      {
        onReplaceDocument: vi.fn().mockResolvedValue(replacement),
      },
    );
    const file = new File(["%PDF-1.7 updated cv"], "updated-cv.pdf", {
      type: "application/pdf",
    });

    fireEvent.change(screen.getByLabelText("Replace selected CV"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(props.onReplaceDocument).toHaveBeenCalledWith(
      "application",
      existing,
      file,
      { fileName: "updated-cv.pdf", title: "updated cv" },
    ));
    expect(props.onDocumentAttached).toHaveBeenCalledWith(
      "application",
      replacement,
    );
    await waitFor(() => expect(props.onPreparationSettingsChange).toHaveBeenCalledWith(
      "application",
      expect.objectContaining({
        submission: expect.objectContaining({
          tailored_resume: {
            documentId: "source-existing-cv",
            version: null,
          },
        }),
      }),
    ));
  });

  it("persists the exact stored version selected for submission", async () => {
    installApplicationWorkspaceApiMock({ documents: [storedDocument()] });
    const { props } = renderApplicationWorkspace(createWorkspaceApplication());

    fireEvent.click(await screen.findByRole("button", {
      name: "Use current Saved cover letter version 2 for submission",
    }));

    await waitFor(() => expect(props.onPreparationSettingsChange).toHaveBeenCalledWith(
      "application",
      expect.objectContaining({
        submission: expect.objectContaining({
          cover_letter: {
            documentId: "stored-document-1",
            version: 2,
          },
        }),
      }),
    ));
    expect(screen.getByRole("button", {
      name: "Use current Saved cover letter version 2 for submission",
    })).toHaveAttribute("aria-pressed", "true");
  });

  it("exposes future generator actions without pretending they are available", () => {
    renderApplicationWorkspace(createWorkspaceApplication());

    expect(screen.getByRole("button", { name: "Edit with AI" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Regenerate selected" }),
    ).toBeDisabled();
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
