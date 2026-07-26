import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AI_GENERATION_REQUEST_TIMEOUT_MS } from "@/lib/api-client";
import {
  createLegacyWorkspaceApplication,
  createV3WorkspaceApplication,
  createWorkspaceApplicationWithoutGuide,
  createWorkspaceProfile,
  installApplicationWorkspaceApiMock,
  renderApplicationWorkspace,
} from "@/test/application-workspace-harness";

const consent = {
  consentVersion: "2026-07-18.v2",
  consentedAt: "2026-07-25T10:00:00.000Z",
  hasCurrentConsent: true,
};

function generatedPdfDocument(templateId = "classic_single") {
  return {
    id: `pdf-document-${templateId}`,
    type: "tailored_resume",
    title: "Alex Morgan resume",
    jobId: "job-product-designer",
    applicationIds: ["application-v3"],
    currentVersion: 1,
    createdAt: "2026-07-25T10:00:00.000Z",
    updatedAt: "2026-07-25T10:00:00.000Z",
    generationFingerprint: "pdf-fingerprint",
    currentGenerationFingerprint: "pdf-fingerprint",
    generationModel: "gpt-5",
    generationBackend: "openclaw_codex",
    inputVersions: {},
    versionsTotal: 1,
    versionsHasMore: false,
    versions: [
      {
        id: `pdf-version-${templateId}`,
        version: 1,
        content: "{}",
        createdAt: "2026-07-25T10:00:00.000Z",
        hasRenderedDocx: false,
        hasRenderedArtifact: true,
        artifact: {
          fileName: "Alex-Morgan-resume.pdf",
          contentType: "application/pdf",
          templateId,
          templateVersion: "1.0.0",
          sourceAtsFinalReviewId: "ats-review-1",
          finalResumeJson: {},
          stageResults: {
            experienceRewrite: { experiences: [] },
            atsFinalReview: {
              atsScan: { skippedSections: [] },
              finalResume: { experiences: [] },
            },
          },
          provenance: {},
        },
        factualValidation: { status: "passed" },
        visualValidation: { status: "passed" },
        diff: [],
      },
    ],
  };
}

describe("ApplicationWorkspace", () => {
  it("shows an empty state when no application is selected", () => {
    renderApplicationWorkspace(null);

    expect(
      screen.getByRole("heading", { name: "No application selected" }),
    ).toBeInTheDocument();
  });

  it("renders legacy and current application-analysis states", async () => {
    installApplicationWorkspaceApiMock();
    const legacy = renderApplicationWorkspace(createLegacyWorkspaceApplication());

    expect(
      screen.getByText(/legacy ai-match-v1 percentage/),
    ).toBeInTheDocument();
    legacy.unmount();

    installApplicationWorkspaceApiMock();
    renderApplicationWorkspace(createV3WorkspaceApplication());

    expect(
      screen.getByText(
        "Turn complex B2B workflows into clear, validated product experiences.",
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Confirmed Master Resume"),
    ).toBeInTheDocument();
  });

  it("requires a confirmed Master Resume and never offers a Source CV picker", async () => {
    installApplicationWorkspaceApiMock({ currentMasterResume: null });
    renderApplicationWorkspace(createV3WorkspaceApplication());

    expect(
      await screen.findByRole("button", { name: "Confirm Master Resume" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/Confirm your Master Resume in My Profile/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Source CV")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Attach CV \/ Resume/ }),
    ).not.toBeInTheDocument();
  });

  it("offers only bundled PDF templates and persists the application choice", async () => {
    window.localStorage.removeItem(
      "tasko.resume-template.v1.application-v3",
    );
    installApplicationWorkspaceApiMock();
    renderApplicationWorkspace(createV3WorkspaceApplication());

    const selector = await screen.findByRole("combobox", {
      name: "Resume template",
    });
    expect(
      within(selector)
        .getAllByRole("option")
        .map((option) => option.getAttribute("value")),
    ).toEqual([
      "classic_single",
      "modern_single",
      "modern_two_column",
    ]);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Use Modern Two Column resume template",
      }),
    );
    expect(selector).toHaveValue("modern_two_column");
    expect(
      window.localStorage.getItem(
        "tasko.resume-template.v1.application-v3",
      ),
    ).toBe("modern_two_column");
    window.localStorage.removeItem(
      "tasko.resume-template.v1.application-v3",
    );
  });

  it("runs exactly three sequential server stages before rendering finalResume as PDF", async () => {
    const requestOrder: string[] = [];
    const saved = generatedPdfDocument();
    const timeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const fetchMock = installApplicationWorkspaceApiMock({
      aiPrivacySettings: consent,
      requestHandler: async (url, method, init) => {
        if (
          url.pathname
          === "/resume-tailoring/senior-recruiter-analysis"
          && method === "POST"
        ) {
          requestOrder.push("recruiter");
          expect(JSON.parse(String(init?.body))).toEqual({
            masterResumeId: "master-resume-1",
            targetJobId: "job-product-designer",
          });
          return Response.json({ id: "recruiter-analysis-1" });
        }
        if (
          url.pathname === "/resume-tailoring/experience-rewrite"
          && method === "POST"
        ) {
          requestOrder.push("rewrite");
          expect(JSON.parse(String(init?.body))).toEqual({
            seniorRecruiterAnalysisId: "recruiter-analysis-1",
          });
          return Response.json({ id: "experience-rewrite-1" });
        }
        if (
          url.pathname === "/resume-tailoring/ats-final-review"
          && method === "POST"
        ) {
          requestOrder.push("ats");
          expect(JSON.parse(String(init?.body))).toEqual({
            experienceRewriteId: "experience-rewrite-1",
          });
          return Response.json({ id: "ats-review-1" });
        }
        if (
          url.pathname
          === "/resume-tailoring/ats-final-review/ats-review-1/pdf"
          && method === "GET"
        ) {
          requestOrder.push(`pdf:${url.searchParams.get("templateId")}`);
          return new Response(new Blob(["%PDF-1.7"]), {
            headers: {
              "Content-Type": "application/pdf",
              "X-Rufina-Document-Id": saved.id,
            },
          });
        }
        if (
          url.pathname === `/documents/${saved.id}/attachments`
          && method === "POST"
        ) {
          requestOrder.push("attach");
          expect(JSON.parse(String(init?.body))).toEqual({
            applicationId: "application-v3",
          });
          return Response.json(saved);
        }
        if (url.pathname === `/documents/${saved.id}` && method === "GET") {
          return Response.json(saved);
        }
        if (
          url.pathname === `/documents/${saved.id}/download`
          && method === "GET"
        ) {
          return new Response(new Blob(["%PDF-1.7"]));
        }
        return undefined;
      },
    });
    const { props } = renderApplicationWorkspace(
      createV3WorkspaceApplication(),
    );

    const generate = await screen.findByRole("button", {
      name: "Generate Tailored CV",
    });
    await waitFor(() => expect(generate).toBeEnabled());
    fireEvent.click(generate);

    await waitFor(
      () => expect(props.onDocumentAttached).toHaveBeenCalledTimes(1),
      { timeout: 4_000 },
    );
    expect(requestOrder.slice(0, 5)).toEqual([
      "recruiter",
      "rewrite",
      "ats",
      "pdf:classic_single",
      "attach",
    ]);
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("/assistant/chat"),
      ),
    ).toBe(false);
    expect(
      fetchMock.mock.calls.some(([input, init]) =>
        String(input).includes("/documents/templates/preflight")
        && init?.method === "POST"
        && String(init.body).includes("tailored_resume"),
      ),
    ).toBe(false);
    expect(timeoutSpy).toHaveBeenCalledWith(
      expect.any(Function),
      AI_GENERATION_REQUEST_TIMEOUT_MS,
    );
    expect(props.onDocumentAttached).toHaveBeenCalledWith(
      "application-v3",
      expect.objectContaining({
        artifactId: saved.id,
        fileType: "application/pdf",
      }),
    );
    expect(
      await screen.findByText("PDF rendered, validated, and saved"),
    ).toBeInTheDocument();
  });

  it("keeps historical DOCX resumes available for download", async () => {
    const legacyDocument = {
      ...generatedPdfDocument("classic_single"),
      id: "legacy-docx",
      title: "Historical tailored CV",
      versions: [
        {
          id: "legacy-version",
          version: 1,
          content: "{}",
          createdAt: "2026-07-01T10:00:00.000Z",
          hasRenderedDocx: true,
          hasRenderedArtifact: true,
          artifact: {
            fileName: "historical-cv.docx",
            contentType:
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            templateId: "legacy-template",
            templateVersion: null,
          },
          factualValidation: { status: "passed" },
          visualValidation: { status: "passed" },
          diff: [],
        },
      ],
    };
    installApplicationWorkspaceApiMock({ documents: [legacyDocument] });
    renderApplicationWorkspace(createV3WorkspaceApplication());

    const downloads = await screen.findAllByRole("link", { name: "DOCX" });
    expect(downloads[0]).toHaveAttribute(
      "href",
      "http://localhost:8000/documents/legacy-docx/download",
    );
    expect(
      screen.queryByRole("button", { name: "Delete Tailored CV" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Restore/ }),
    ).not.toBeInTheDocument();
  });

  it("keeps cover-letter DOCX upload and preflight independent", async () => {
    const source = {
      id: "cover-source",
      category: "Cover Letter",
      title: "Main cover",
      language: "English",
      file_name: "cover.docx",
      file_size: "16 KB",
      file_type:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      uploaded_at: "2026-07-25T10:00:00.000Z",
      data_url:
        "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cover",
    };
    const fetchMock = installApplicationWorkspaceApiMock();
    renderApplicationWorkspace(createV3WorkspaceApplication(), {
      profile: createWorkspaceProfile({
        documents: JSON.stringify([source]),
      }),
    });

    expect(
      await screen.findByRole("combobox", { name: "Source cover letter" }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([input, init]) =>
          String(input).includes("/documents/templates/preflight")
          && init?.method === "POST"
          && String(init.body).includes("cover_letter"),
        ),
      ).toBe(true);
    });
  });

  it("does not loop when the application guide is missing", async () => {
    const fetchMock = installApplicationWorkspaceApiMock();
    renderApplicationWorkspace(createWorkspaceApplicationWithoutGuide());

    expect(
      screen.getByText(/does not have a complete application guide v3/),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Refresh analysis first" }),
      ).toBeDisabled();
    });
    expect(fetchMock.mock.calls.length).toBeLessThan(12);
  });
});
