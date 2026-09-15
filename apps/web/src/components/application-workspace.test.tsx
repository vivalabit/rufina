import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApplicationWorkspace } from "@/components/application-workspace";
import type { GenerationRun } from "@/features/applications/api/generation-runs-client";
import { defaultDocumentPreparationSettings } from "@/features/applications/model/document-preparation";
import {
  createWorkspaceApplication,
  installApplicationWorkspaceApiMock,
  renderApplicationWorkspace,
} from "@/test/application-workspace-harness";

function generationRun(overrides: Partial<GenerationRun> = {}): GenerationRun {
  return {
    id: "run-1",
    applicationId: "application",
    status: "running",
    stage: "draft",
    revision: 3,
    backend: "openai_api",
    model: "gpt-5.4",
    reasoningEffort: "medium",
    inputFingerprint: "a".repeat(64),
    documentTypes: ["tailored_resume", "cover_letter"],
    pendingQuestion: null,
    result: {
      fit: {
        eligible: true,
        overallScore: 82,
        recommendation: "yes",
        summary: "Strong product design fit.",
        strengths: ["Design systems leadership"],
        gaps: ["No explicit fintech portfolio example"],
        keywords: [
          { term: "Design systems", support: "supported" },
          { term: "Fintech", support: "unsupported" },
        ],
      },
    },
    error: null,
    cancelRequested: false,
    events: [
      {
        sequence: 1,
        kind: "run.created",
        stage: "sources",
        data: {
          applicationRevision: 4,
          vacancyRevision: 2,
          masterProfileVersion: 7,
        },
        createdAt: "2026-09-13T10:00:00.000Z",
      },
      {
        sequence: 2,
        kind: "draft.started",
        stage: "draft",
        data: {},
        createdAt: "2026-09-13T10:01:00.000Z",
      },
    ],
    artifacts: [],
    checks: [],
    createdAt: "2026-09-13T10:00:00.000Z",
    updatedAt: "2026-09-13T10:01:00.000Z",
    completedAt: null,
    ...overrides,
  };
}

function completedRun(overrides: Partial<GenerationRun> = {}) {
  return generationRun({
    status: "completed",
    stage: "final_review",
    revision: 8,
    completedAt: "2026-09-13T10:05:00.000Z",
    result: {
      fit: generationRun().result.fit,
      review: {
        approved: true,
        summary: "Grounded and consistent.",
        meaningfulChanges: ["Led with design systems experience"],
        findings: [],
      },
      visualReview: {
        approved: true,
        summary: "Both rendered pages are balanced and readable.",
        findings: [],
      },
      documents: [
        {
          id: "document-cv",
          type: "tailored_resume",
          version: 2,
          downloadUrl: "/documents/document-cv/download",
          pdfUrl: "/documents/document-cv/pdf",
        },
        {
          id: "document-letter",
          type: "cover_letter",
          version: 2,
          downloadUrl: "/documents/document-letter/download",
          pdfUrl: "/documents/document-letter/pdf",
        },
      ],
    },
    artifacts: [
      {
        id: "artifact-cv",
        documentType: "tailored_resume",
        artifactType: "resume_pdf",
        version: 1,
        fileName: "acme-cv.pdf",
        contentType: "application/pdf",
        contentSha256: "b".repeat(64),
        metadata: {},
        documentId: "document-cv",
        documentVersion: 2,
        createdAt: "2026-09-13T10:05:00.000Z",
      },
      {
        id: "artifact-letter",
        documentType: "cover_letter",
        artifactType: "cover_letter_pdf",
        version: 1,
        fileName: "acme-letter.pdf",
        contentType: "application/pdf",
        contentSha256: "c".repeat(64),
        metadata: {},
        documentId: "document-letter",
        documentVersion: 2,
        createdAt: "2026-09-13T10:05:00.000Z",
      },
    ],
    checks: [
      {
        id: "check-text",
        artifactId: "artifact-cv",
        checkType: "text_layer",
        status: "passed",
        artifactSha256: "b".repeat(64),
        data: { message: "Readable" },
        createdAt: "2026-09-13T10:05:00.000Z",
      },
      {
        id: "check-pages",
        artifactId: "artifact-cv",
        checkType: "page_count",
        status: "passed",
        artifactSha256: "b".repeat(64),
        data: { pageCount: 2 },
        createdAt: "2026-09-13T10:05:00.000Z",
      },
    ],
    ...overrides,
  });
}

describe("ApplicationWorkspace", () => {
  it("renders the empty selection state", () => {
    installApplicationWorkspaceApiMock();
    const { props } = renderApplicationWorkspace(null);

    expect(screen.getByRole("heading", { name: "No application selected" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Applications" }));
    expect(props.onBack).toHaveBeenCalledOnce();
  });

  it("shows a responsive five-stage preparation workspace", async () => {
    installApplicationWorkspaceApiMock();
    renderApplicationWorkspace(createWorkspaceApplication());

    expect(screen.getByRole("heading", { name: "Senior Product Designer" })).toBeInTheDocument();
    expect(screen.getByText(/Acme Labs · Zurich, Switzerland/)).toBeInTheDocument();
    const workflow = screen.getByRole("list", { name: "Application document workflow" });
    expect(workflow).toHaveClass("sm:grid-cols-5");
    expect(screen.getByText("Draft & review")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Prepare your application pack" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start application" })).toBeEnabled();
    expect(screen.getAllByText("ModernCV · Banking")).toHaveLength(2);
    expect(screen.getAllByText("Classic letter")).toHaveLength(2);
  });

  it("starts CV and cover letter from saved user options", async () => {
    const started = generationRun({ status: "queued", stage: "sources", revision: 1 });
    const fetchMock = installApplicationWorkspaceApiMock({ startedGenerationRun: started });
    const { props } = renderApplicationWorkspace(createWorkspaceApplication());

    const preferences = await screen.findByRole("textbox", { name: "Your preferences" });
    fireEvent.change(preferences, { target: { value: "Emphasize design systems." } });
    fireEvent.click(screen.getByRole("button", { name: "Start application" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/applications/application/generation/runs"),
      expect.objectContaining({ method: "POST" }),
    ));
    const request = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      documentTypes: ["tailored_resume", "cover_letter"],
      language: "English",
      userPreferences: "Emphasize design systems.",
    });
    expect(props.onPreparationSettingsChange).toHaveBeenCalled();
    expect(await screen.findByText("Preparing sources")).toBeInTheDocument();
  });

  it("persists a selected CV template and sends it to generation", async () => {
    const started = generationRun({ status: "queued", stage: "sources", revision: 1 });
    const fetchMock = installApplicationWorkspaceApiMock({ startedGenerationRun: started });
    const { props } = renderApplicationWorkspace(createWorkspaceApplication());

    const template = await screen.findByRole("radio", { name: "Ishchenko · Classic" });
    fireEvent.click(template);

    expect(template).toBeChecked();
    expect(screen.getByRole("radio", { name: "ModernCV · Banking" })).not.toBeChecked();
    expect(props.onPreparationSettingsChange).toHaveBeenLastCalledWith(
      "application",
      expect.objectContaining({
        formatting: expect.objectContaining({ resumeTemplateId: "ishchenko_classic" }),
      }),
    );
    const brief = screen.getByRole("heading", { name: "Application brief" }).closest("aside")!;
    expect(within(brief).getByText("Ishchenko · Classic")).toBeInTheDocument();
    expect(within(brief).queryByText("ModernCV · Banking")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Start application" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/generation/runs"),
      expect.objectContaining({ method: "POST" }),
    ));
    const request = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      formattingParameters: {
        tailored_resume: { templateId: "ishchenko_classic", pageSize: "A4", maxPages: 2 },
      },
    });
  });

  it("restores the saved template when reopening preparation", async () => {
    installApplicationWorkspaceApiMock();
    renderApplicationWorkspace(createWorkspaceApplication({
      documentPreparation: {
        ...defaultDocumentPreparationSettings,
        formatting: { ...defaultDocumentPreparationSettings.formatting, resumeTemplateId: "ishchenko_classic" },
      },
    }));

    expect(await screen.findByRole("radio", { name: "Ishchenko · Classic" })).toBeChecked();
  });

  it("keeps the idempotency key within the API limit for long application ids", async () => {
    const applicationId = `application-${"x".repeat(148)}`;
    const started = generationRun({
      applicationId,
      status: "queued",
      stage: "sources",
      revision: 1,
    });
    const fetchMock = installApplicationWorkspaceApiMock({ startedGenerationRun: started });
    const application = createWorkspaceApplication({ id: applicationId });
    renderApplicationWorkspace(application);

    fireEvent.click(await screen.findByRole("button", { name: "Start application" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/generation/runs"),
      expect.objectContaining({ method: "POST" }),
    ));
    const request = fetchMock.mock.calls.find(([input, init]) => (
      init?.method === "POST" && String(input).includes("/generation/runs")
    ));
    const body = JSON.parse(String(request?.[1]?.body)) as { idempotencyKey: string };

    expect(body.idempotencyKey).toMatch(/^generation-/);
    expect(body.idempotencyKey.length).toBeLessThanOrEqual(160);
    expect(body.idempotencyKey).not.toContain(application.id);
  });

  it("restores the fit decision and continues the exact run", async () => {
    const awaiting = generationRun({
      status: "awaiting_approval",
      stage: "fit",
      pendingQuestion: {
        id: "continue_after_fit",
        prompt: "Continue with the CV and cover letter?",
        choices: ["continue", "stop"],
      },
      result: {
        fit: {
          ...generationRun().result.fit,
          clarificationQuestions: ["Can you confirm any regulated-finance work?"],
        },
      },
    });
    const queued = generationRun({ status: "queued", stage: "draft", revision: 4 });
    const fetchMock = installApplicationWorkspaceApiMock({
      currentGenerationRun: awaiting,
      generationRuns: [awaiting],
      requestHandler: (url, method) => {
        if (url.pathname.endsWith("/responses") && method === "POST") {
          return Response.json(queued, { status: 202 });
        }
      },
    });
    renderApplicationWorkspace(createWorkspaceApplication());

    expect(await screen.findByText("82")).toBeInTheDocument();
    expect(screen.getByText("Design systems leadership")).toBeInTheDocument();
    expect(screen.getAllByText("No explicit fintech portfolio example")).toHaveLength(2);
    expect(screen.getByText("Can you confirm any regulated-finance work?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/runs/run-1/responses"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          questionId: "continue_after_fit",
          response: "continue",
          revision: 3,
        }),
      }),
    ));
    expect(await screen.findByText("Writing drafts")).toBeInTheDocument();
  });

  it("restores live progress and exposes cancellation", async () => {
    const current = generationRun({ stage: "review" });
    installApplicationWorkspaceApiMock({
      currentGenerationRun: current,
      generationRuns: [current],
    });
    renderApplicationWorkspace(createWorkspaceApplication());

    expect(await screen.findByText("Writing drafts")).toBeInTheDocument();
    expect(screen.getByText(/leave this page/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeEnabled();
  });

  it("shows a recoverable failure without publishing partial files", async () => {
    const failed = generationRun({
      status: "failed",
      stage: "pdf_checks",
      error: {
        code: "pdf_verification_failed",
        message: "PDF verification did not pass after three attempts",
        retryable: true,
      },
    });
    installApplicationWorkspaceApiMock({
      currentGenerationRun: failed,
      generationRuns: [failed],
    });
    renderApplicationWorkspace(createWorkspaceApplication());

    expect(await screen.findByText("PDF verification did not pass after three attempts")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start a new run" })).toBeInTheDocument();
    expect(screen.queryByText("Ready for your review")).not.toBeInTheDocument();
  });

  it("reviews both PDFs, changes, checks, and starts an audited revision", async () => {
    const current = completedRun();
    const next = generationRun({ id: "run-2", status: "queued", stage: "sources", revision: 1 });
    const fetchMock = installApplicationWorkspaceApiMock({
      currentGenerationRun: current,
      generationRuns: [current],
      startedGenerationRun: next,
      requestHandler: (url, method) => {
        if (url.pathname.endsWith("/pdf") && method === "GET") {
          return new Response(new Blob(["%PDF"], { type: "application/pdf" }));
        }
      },
    });
    const onStatusChange = vi.fn();
    renderApplicationWorkspace(createWorkspaceApplication(), { onStatusChange });

    expect(await screen.findByText("Ready for your review")).toBeInTheDocument();
    expect(screen.getByText("Checks complete")).toBeInTheDocument();
    expect(screen.getByText("PDF text is readable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Cover letter" }));
    expect(await screen.findByLabelText("Cover letter PDF preview panel")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Changes" }));
    expect(screen.getAllByText("Led with design systems experience").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Mark submitted" }));
    expect(onStatusChange).toHaveBeenCalledWith("application", "applied");

    fireEvent.change(screen.getByRole("textbox", { name: "Revision request" }), {
      target: { value: "Make the opening more direct." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create revision" }));
    await waitFor(() => {
      const request = fetchMock.mock.calls.find(([, init]) =>
        init?.method === "POST" && String(init.body).includes("Make the opening more direct."),
      );
      expect(request).toBeDefined();
    });
  });

  it("creates a revision for a template change and keeps the current PDF label accurate", async () => {
    const current = completedRun();
    const next = generationRun({ id: "run-2", status: "queued", stage: "sources", revision: 1 });
    const fetchMock = installApplicationWorkspaceApiMock({
      currentGenerationRun: current,
      generationRuns: [current],
      startedGenerationRun: next,
      requestHandler: (url, method) => {
        if (url.pathname.endsWith("/pdf") && method === "GET") {
          return new Response(new Blob(["%PDF"], { type: "application/pdf" }));
        }
      },
    });
    renderApplicationWorkspace(createWorkspaceApplication({
      documentPreparation: { ...defaultDocumentPreparationSettings, userPreferences: "Keep the tone direct." },
    }));

    expect(await screen.findByRole("button", { name: "Create revision" })).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "Ishchenko · Classic" }));
    const brief = screen.getByRole("heading", { name: "Application brief" }).closest("aside")!;
    expect(within(brief).getByText("ModernCV · Banking")).toBeInTheDocument();
    expect(within(brief).queryByText("Ishchenko · Classic")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Revision request" })).toHaveValue("");
    expect(screen.getByRole("button", { name: "Create revision" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Create revision" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/generation/runs"),
      expect.objectContaining({ method: "POST" }),
    ));
    const request = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      userPreferences: "Keep the tone direct.",
      formattingParameters: { tailored_resume: { templateId: "ishchenko_classic" } },
    });
  });

  it.each(["moderncv_banking", "ishchenko_classic"])(
    "opens regeneration from the header and creates a new version with %s",
    async (templateId) => {
      const current = completedRun();
      const next = generationRun({ id: "run-2", status: "queued", stage: "sources", revision: 1 });
      const fetchMock = installApplicationWorkspaceApiMock({
        currentGenerationRun: current,
        generationRuns: [current],
        startedGenerationRun: next,
      });
      const onStatusChange = vi.fn();
      renderApplicationWorkspace(createWorkspaceApplication({
        documentPreparation: {
          ...defaultDocumentPreparationSettings,
          userPreferences: "Keep the tone direct.",
        },
      }), { onStatusChange });

      const regenerate = await screen.findByRole("button", { name: "Regenerate CV" });
      expect(regenerate.closest("header")).not.toBeNull();
      fireEvent.click(regenerate);

      expect(screen.getByRole("heading", { name: "Create a new version" })).toBeInTheDocument();
      expect(screen.queryByLabelText("CV PDF preview panel")).not.toBeInTheDocument();
      expect(screen.getAllByRole("radio")).toHaveLength(2);
      expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
      if (templateId === "ishchenko_classic") {
        fireEvent.click(screen.getByRole("radio", { name: "Ishchenko · Classic" }));
      }
      const generate = screen.getByRole("button", { name: "Generate new version" });
      expect(generate).toBeEnabled();
      fireEvent.click(generate);

      await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/generation/runs"),
        expect.objectContaining({ method: "POST" }),
      ));
      const request = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
      expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
        userPreferences: "Keep the tone direct.",
        formattingParameters: { tailored_resume: { templateId } },
      });
      await waitFor(() => expect(screen.queryByRole("button", { name: "Generate new version" })).not.toBeInTheDocument());
      expect(onStatusChange).not.toHaveBeenCalled();
    },
  );

  it("returns from regeneration options to the existing PDF without starting a run", async () => {
    const current = completedRun();
    const fetchMock = installApplicationWorkspaceApiMock({
      currentGenerationRun: current,
      generationRuns: [current],
    });
    renderApplicationWorkspace(createWorkspaceApplication());

    fireEvent.click(await screen.findByRole("button", { name: "Regenerate CV" }));
    fireEvent.click(screen.getByRole("button", { name: "Back to documents" }));

    expect(screen.getByRole("tablist", { name: "Generated documents" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Create a new version" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
  });

  it("offers regeneration for existing documents without a generation run", async () => {
    installApplicationWorkspaceApiMock();
    renderApplicationWorkspace(createWorkspaceApplication({
      documents: [{
        id: "legacy-cv", kind: "generated", title: "CV", fileName: "cv.pdf",
        fileSize: "10 KB", fileType: "PDF", uploadedAt: "2026-08-01",
        downloadUrl: "/documents/legacy-cv/download",
      }],
    }));

    expect(await screen.findByRole("button", { name: "Generate new version" })).toBeEnabled();
    expect(screen.getByRole("heading", { name: "Create a new version" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regenerate CV" })).toBeEnabled();
  });

  it("shows the template recorded on a run rather than later preparation settings", async () => {
    const current = generationRun();
    current.events[0].data.resumeTemplateId = "ishchenko_classic";
    installApplicationWorkspaceApiMock({ currentGenerationRun: current, generationRuns: [current] });
    renderApplicationWorkspace(createWorkspaceApplication());

    await screen.findByText("Writing drafts");
    const brief = screen.getByRole("heading", { name: "Application brief" }).closest("aside")!;
    expect(within(brief).getByText("Ishchenko · Classic")).toBeInTheDocument();
    expect(within(brief).queryByText("ModernCV · Banking")).not.toBeInTheDocument();
  });

  it("keeps the reviewed historical PDF selected when the parent persists a revision template", async () => {
    const current = completedRun();
    current.events[0].data.resumeTemplateId = "ishchenko_classic";
    const older = completedRun({ id: "older-run", createdAt: "2026-09-12T10:00:00.000Z" });
    installApplicationWorkspaceApiMock({
      currentGenerationRun: current,
      generationRuns: [current, older],
      requestHandler: (url, method) => {
        if (url.pathname.endsWith("/pdf") && method === "GET") {
          return new Response(new Blob(["%PDF"], { type: "application/pdf" }));
        }
      },
    });
    const application = createWorkspaceApplication();
    const { props, rerender } = renderApplicationWorkspace(application);

    const versions = await screen.findByRole("combobox", { name: "Document version" });
    fireEvent.change(versions, { target: { value: older.id } });
    fireEvent.click(screen.getByRole("radio", { name: "Ishchenko · Classic" }));
    const savedSettings = vi.mocked(props.onPreparationSettingsChange).mock.calls.at(-1)![1];
    rerender(<ApplicationWorkspace {...props} application={{ ...application, documentPreparation: savedSettings }} />);

    expect(screen.getByRole("combobox", { name: "Document version" })).toHaveValue(older.id);
    expect(screen.getByRole("radio", { name: "Ishchenko · Classic" })).toBeChecked();
    const brief = screen.getByRole("heading", { name: "Application brief" }).closest("aside")!;
    expect(within(brief).getByText("ModernCV · Banking")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create revision" })).toBeEnabled();
  });
});
