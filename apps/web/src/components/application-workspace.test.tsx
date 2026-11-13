import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

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
    backend: "anthropic_api",
    model: "claude-sonnet-5-5",
    reasoningEffort: "low",
    inputFingerprint: "a".repeat(64),
    documentTypes: ["tailored_resume", "cover_letter"],
    pendingQuestion: null,
    result: {},
    error: null,
    cancelRequested: false,
    events: [
      {
        sequence: 1,
        kind: "run.created",
        stage: "sources",
        data: { documentTemplateId: "swiss_classic", resumeTemplateId: "swiss_classic" },
        createdAt: "2026-11-12T10:00:00.000Z",
      },
    ],
    artifacts: [],
    checks: [],
    createdAt: "2026-11-12T10:00:00.000Z",
    updatedAt: "2026-11-12T10:00:20.000Z",
    completedAt: null,
    ...overrides,
  };
}

function artifact(
  id: string,
  documentType: "tailored_resume" | "cover_letter",
  artifactType: string,
  fileName: string,
  templateId = "swiss_classic",
  version = 1,
): GenerationRun["artifacts"][number] {
  return {
    id,
    documentType,
    artifactType,
    version,
    fileName,
    contentType: fileName.endsWith(".pdf")
      ? "application/pdf"
      : "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    contentSha256: "b".repeat(64),
    metadata: { templateId },
    documentId: documentType === "tailored_resume" ? "document-cv" : "document-letter",
    documentVersion: 2,
    createdAt: "2026-11-12T10:00:30.000Z",
  };
}

function completedRun(overrides: Partial<GenerationRun> = {}) {
  return generationRun({
    status: "completed",
    stage: "final_review",
    revision: 8,
    completedAt: "2026-11-12T10:00:31.000Z",
    result: {
      tailoring: {
        language: "en",
        headline: "Product Designer | Figma, User research",
        vacancy: { title: "Senior Product Designer", parsedBy: "claude-haiku-5-5" },
        score: { before: 58, after: 84 },
        coverage: [
          { label: "Figma", importance: "required", before: "skills", after: "experience" },
          { label: "User research", importance: "required", before: "experience", after: "experience" },
          { label: "Design systems", importance: "preferred", before: "missing", after: "skills" },
          { label: "Fintech", importance: "preferred", before: "missing", after: "missing" },
        ],
        gaps: [{ label: "Fintech", importance: "preferred" }],
        knockouts: [
          { kind: "language", requirement: "German C1", met: false, detail: "Profile: B2" },
          { kind: "work_permit", requirement: "Swiss work permit", met: null, detail: "" },
        ],
        statements: { inProfile: 12, selected: 12, reworded: 9, keptOriginal: 1, omitted: 0 },
        keptOriginal: [{ id: "statement-4", reasons: ["new numbers: 40"] }],
        changes: [
          "Headline set to “Product Designer | Figma, User research”.",
          "Reworded 9 of 12 statements for this vacancy; every number and technology was checked against your profile.",
        ],
      },
      render: {
        templateId: "swiss_classic",
        templateVersion: "1.1.0",
        pages: { tailored_resume: 1, cover_letter: 1 },
        droppedStatementIds: [],
        fitScale: 1,
        atsReadable: true,
      },
      warnings: [
        "1 statement(s) keep the profile wording because the rewritten text did not pass the fact check.",
      ],
      usage: { requests: 2, inputTokens: 5200, outputTokens: 1800, seconds: 27.4 },
      documents: [
        { id: "document-cv", type: "tailored_resume", version: 2, downloadUrl: "/documents/document-cv/download", pdfUrl: "/documents/document-cv/pdf" },
        { id: "document-letter", type: "cover_letter", version: 2, downloadUrl: "/documents/document-letter/download", pdfUrl: "/documents/document-letter/pdf" },
      ],
    },
    artifacts: [
      artifact("artifact-cv", "tailored_resume", "resume_pdf", "Ada_Lovelace_CV_Acme_Labs.pdf"),
      artifact("artifact-cv-docx", "tailored_resume", "resume_docx", "Ada_Lovelace_CV_Acme_Labs.docx"),
      artifact("artifact-letter", "cover_letter", "cover_letter_pdf", "Ada_Lovelace_Cover_Letter_Acme_Labs.pdf"),
      artifact("artifact-letter-docx", "cover_letter", "cover_letter_docx", "Ada_Lovelace_Cover_Letter_Acme_Labs.docx"),
    ],
    checks: [
      {
        id: "check-facts",
        artifactId: null,
        checkType: "fact_check",
        status: "warning",
        artifactSha256: null,
        data: { message: "Some statements keep the profile wording after the fact check." },
        createdAt: "2026-11-12T10:00:25.000Z",
      },
      {
        id: "check-pages",
        artifactId: null,
        checkType: "page_limit",
        status: "passed",
        artifactSha256: null,
        data: { document: "tailored_resume", templateId: "swiss_classic", message: "CV fits on 1 of 1 allowed page(s)." },
        createdAt: "2026-11-12T10:00:30.000Z",
      },
      {
        id: "check-ats",
        artifactId: null,
        checkType: "ats_text",
        status: "passed",
        artifactSha256: null,
        data: { document: "tailored_resume", templateId: "swiss_classic", message: "CV: applicant tracking systems can read the complete text." },
        createdAt: "2026-11-12T10:00:30.000Z",
      },
    ],
    ...overrides,
  });
}

function postedBody(fetchMock: ReturnType<typeof installApplicationWorkspaceApiMock>, suffix: string) {
  const call = fetchMock.mock.calls.find(
    ([input, init]) =>
      init?.method === "POST"
      && new URL(String(input), "http://localhost").pathname.endsWith(suffix),
  );
  return call ? JSON.parse(String(call[1]?.body)) : null;
}

describe("ApplicationWorkspace", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders the empty selection state", () => {
    installApplicationWorkspaceApiMock();
    const { props } = renderApplicationWorkspace(null);

    expect(screen.getByRole("heading", { name: "No application selected" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Applications" }));
    expect(props.onBack).toHaveBeenCalledOnce();
  });

  it("offers one action before the first run and no template choice yet", async () => {
    installApplicationWorkspaceApiMock();
    renderApplicationWorkspace(createWorkspaceApplication());

    expect(screen.getByRole("heading", { name: "Senior Product Designer" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Tailor your resume to this vacancy" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tailor resume" })).toBeEnabled();
    expect(screen.getByRole("combobox", { name: "CV page limit" })).toHaveValue("1");
    expect(screen.getByRole("combobox", { name: "Document language" })).toHaveValue("Auto");
    expect(screen.getByText("Swiss Classic")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Template" })).not.toBeInTheDocument();
  });

  it("starts tailoring with the saved options in one click", async () => {
    const started = generationRun({ status: "queued", stage: "sources", revision: 1 });
    const fetchMock = installApplicationWorkspaceApiMock({ startedGenerationRun: started });
    const { props } = renderApplicationWorkspace(createWorkspaceApplication());

    fireEvent.change(await screen.findByRole("textbox", { name: "Your wishes" }), {
      target: { value: "Emphasize design systems." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tailor resume" }));

    await waitFor(() => expect(postedBody(fetchMock, "/generation/runs")).not.toBeNull());
    const request = postedBody(fetchMock, "/generation/runs");
    expect(request).toMatchObject({
      documentTypes: ["tailored_resume", "cover_letter"],
      language: "Auto",
      userPreferences: "Emphasize design systems.",
      formattingParameters: {
        tailored_resume: { templateId: "swiss_classic", maxPages: 1 },
        cover_letter: { templateId: "swiss_classic" },
      },
    });
    expect(request.idempotencyKey.length).toBeLessThanOrEqual(160);
    expect(props.onPreparationSettingsChange).toHaveBeenCalled();
    expect(await screen.findByText("Reading the vacancy")).toBeInTheDocument();
  });

  it("writes in the vacancy language unless the person chooses one here", async () => {
    const fetchMock = installApplicationWorkspaceApiMock({
      startedGenerationRun: generationRun({ status: "queued", stage: "sources", revision: 1 }),
    });
    renderApplicationWorkspace(createWorkspaceApplication({
      // A language saved by an earlier version must not override the vacancy.
      documentPreparation: { ...defaultDocumentPreparationSettings, language: "German", languageChoice: undefined },
    }));

    const language = await screen.findByRole("combobox", { name: "Document language" });
    expect(language).toHaveValue("Auto");
    fireEvent.change(language, { target: { value: "English" } });
    fireEvent.click(screen.getByRole("button", { name: "Tailor resume" }));

    await waitFor(() => expect(postedBody(fetchMock, "/generation/runs")).not.toBeNull());
    expect(postedBody(fetchMock, "/generation/runs").language).toBe("English");
  });

  it("starts by itself when opened from a vacancy", async () => {
    const started = generationRun({ status: "queued", stage: "sources", revision: 1 });
    const fetchMock = installApplicationWorkspaceApiMock({ startedGenerationRun: started });
    const { props } = renderApplicationWorkspace(createWorkspaceApplication(), {
      autoStart: true,
      onAutoStartHandled: () => undefined,
    });

    await waitFor(() => expect(postedBody(fetchMock, "/generation/runs")).not.toBeNull());
    expect(await screen.findByRole("heading", { name: "Tailoring your documents" })).toBeInTheDocument();
    expect(props.autoStart).toBe(true);
  });

  it("does not start by itself when documents already exist", async () => {
    const current = completedRun();
    const fetchMock = installApplicationWorkspaceApiMock({
      currentGenerationRun: current,
      generationRuns: [current],
    });
    renderApplicationWorkspace(createWorkspaceApplication(), { autoStart: true });

    expect(await screen.findByRole("complementary", { name: "Tailoring summary" })).toBeInTheDocument();
    expect(postedBody(fetchMock, "/generation/runs")).toBeNull();
  });

  it("needs work experience in the profile before tailoring", async () => {
    const fetchMock = installApplicationWorkspaceApiMock({
      currentMasterResume: {
        masterResumeId: "default",
        version: 1,
        masterResume: { language: "en", experiences: [] },
        createdAt: "2026-07-25T10:00:00.000Z",
        updatedAt: "2026-07-25T10:00:00.000Z",
      },
    });
    renderApplicationWorkspace(createWorkspaceApplication(), { autoStart: true });

    expect(await screen.findByRole("alert")).toHaveTextContent("Add your experience to the profile first");
    expect(screen.getByRole("button", { name: "Tailor resume" })).toBeDisabled();
    expect(postedBody(fetchMock, "/generation/runs")).toBeNull();
  });

  it("needs a profile before tailoring", async () => {
    installApplicationWorkspaceApiMock({ currentMasterResume: null });
    renderApplicationWorkspace(createWorkspaceApplication(), { autoStart: true });

    expect(await screen.findByRole("alert")).toHaveTextContent("Add your experience to the profile first");
    expect(screen.getByRole("button", { name: "Tailor resume" })).toBeDisabled();
  });

  it("restores live progress with the current step and allows stopping", async () => {
    const current = generationRun({ stage: "review" });
    const fetchMock = installApplicationWorkspaceApiMock({
      currentGenerationRun: current,
      generationRuns: [current],
      requestHandler: (url, method) =>
        url.pathname.endsWith("/cancel") && method === "POST"
          ? Response.json({ ...current, cancelRequested: true, revision: 4 })
          : undefined,
    });
    renderApplicationWorkspace(createWorkspaceApplication());

    const progress = await screen.findByRole("list", { name: "Tailoring progress" });
    expect(within(progress).getAllByRole("listitem")).toHaveLength(5);
    expect(within(progress).getByText("Checking facts")).toBeInTheDocument();
    expect(screen.getByText(/leave this page/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    await waitFor(() => expect(postedBody(fetchMock, "/cancel")).toEqual({ revision: 3 }));
    expect(await screen.findByRole("button", { name: "Stopping…" })).toBeDisabled();
  });

  it("shows a recoverable failure with the technical details folded away", async () => {
    const failed = generationRun({
      status: "failed",
      stage: "draft",
      error: { code: "provider_error", message: "The AI backend request failed: timeout", retryable: true },
    });
    installApplicationWorkspaceApiMock({ currentGenerationRun: failed, generationRuns: [failed] });
    renderApplicationWorkspace(createWorkspaceApplication());

    expect(await screen.findByText(/The AI service did not answer/)).toBeVisible();
    const details = screen.getByText("The AI backend request failed: timeout");
    expect(details).not.toBeVisible();
    fireEvent.click(screen.getByText("Technical details"));
    expect(details).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("keeps the last documents reachable after a failed new run", async () => {
    const previous = completedRun({ id: "run-previous" });
    const failed = generationRun({
      id: "run-failed",
      status: "failed",
      error: { code: "wording_failed", message: "No usable wording", retryable: true },
    });
    installApplicationWorkspaceApiMock({ currentGenerationRun: failed, generationRuns: [failed, previous] });
    renderApplicationWorkspace(createWorkspaceApplication());

    fireEvent.click(await screen.findByRole("button", { name: "View last version" }));

    expect(await screen.findByRole("complementary", { name: "Tailoring summary" })).toBeInTheDocument();
    expect(screen.getByText(/You are viewing a previous version/)).toBeInTheDocument();
  });

  it("shows the result with score, coverage, changes, gaps and checks", async () => {
    const current = completedRun();
    installApplicationWorkspaceApiMock({ currentGenerationRun: current, generationRuns: [current] });
    renderApplicationWorkspace(createWorkspaceApplication());

    const summary = await screen.findByRole("complementary", { name: "Tailoring summary" });
    expect(within(summary).getByLabelText("Before tailoring: 58")).toBeInTheDocument();
    expect(within(summary).getByLabelText("After tailoring: 84")).toBeInTheDocument();
    expect(within(summary).getByText(/not the grade of an applicant tracking system/)).toBeInTheDocument();
    expect(within(summary).getByText("Figma")).toHaveAttribute("title", "Shown in your experience");
    expect(within(summary).getByText("Design systems")).toHaveAttribute("title", "Listed in your skills only");
    expect(within(summary).getByText("German C1")).toBeInTheDocument();
    expect(within(summary).getByText("Profile: B2")).toBeInTheDocument();
    expect(within(summary).getByText("Check this yourself")).toBeInTheDocument();
    expect(within(summary).getByText(/Reworded 9 of 12 statements/)).toBeInTheDocument();
    expect(within(summary).getByRole("heading", { name: "Not in your profile" })).toBeInTheDocument();
    expect(within(summary).getByText(/add it to your profile and tailor again/)).toBeInTheDocument();
    expect(within(summary).getByText("CV fits on 1 of 1 allowed page(s).")).toBeInTheDocument();
    expect(within(summary).getByText(/claude-sonnet-5-5 · 27 s · 7,000 tokens/)).toBeInTheDocument();

    expect(screen.getByRole("tab", { name: "CV" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("link", { name: "Download CV as PDF" })).toHaveAttribute(
      "href",
      expect.stringContaining("/documents/document-cv/download"),
    );
    expect(screen.getByRole("link", { name: "Download CV as Word" })).toHaveAttribute(
      "href",
      expect.stringContaining("/generation/runs/run-1/artifacts/artifact-cv-docx"),
    );
    fireEvent.click(screen.getByRole("tab", { name: "Cover letter" }));
    expect(screen.getByRole("link", { name: "Download Cover letter as Word" })).toHaveAttribute(
      "href",
      expect.stringContaining("/artifacts/artifact-letter-docx"),
    );
  });

  it("shows a single score when tailoring did not change the match", async () => {
    const base = completedRun();
    const current = completedRun({
      result: { ...base.result, tailoring: { ...base.result.tailoring, score: { before: 84, after: 84 } } },
    });
    installApplicationWorkspaceApiMock({ currentGenerationRun: current, generationRuns: [current] });
    renderApplicationWorkspace(createWorkspaceApplication());

    const summary = await screen.findByRole("complementary", { name: "Tailoring summary" });
    expect(within(summary).getByLabelText("After tailoring: 84")).toBeInTheDocument();
    expect(within(summary).queryByLabelText(/Before tailoring/)).not.toBeInTheDocument();
  });

  it("switches the template in one click without a new run", async () => {
    const current = completedRun();
    const rendered = completedRun({
      revision: 9,
      result: {
        ...current.result,
        render: { ...current.result.render, templateId: "modern_single" },
        documents: current.result.documents?.map((item) => ({ ...item, version: 3 })),
      },
      artifacts: [
        ...current.artifacts,
        artifact("artifact-cv-2", "tailored_resume", "resume_pdf", "Ada_Lovelace_CV_Acme_Labs.pdf", "modern_single", 2),
      ],
    });
    const fetchMock = installApplicationWorkspaceApiMock({
      currentGenerationRun: current,
      generationRuns: [current],
      renderedGenerationRun: rendered,
    });
    const { props } = renderApplicationWorkspace(createWorkspaceApplication());

    const picker = await screen.findByRole("group", { name: "Template" });
    expect(await within(picker).findAllByRole("button")).toHaveLength(5);
    expect(within(picker).getByRole("button", { name: "Swiss Classic template" })).toHaveAttribute("aria-pressed", "true");
    expect(within(picker).getByText("Design · ATS risk")).toBeInTheDocument();
    fireEvent.click(within(picker).getByRole("button", { name: "Modern template" }));

    await waitFor(() => expect(postedBody(fetchMock, "/render")).toEqual({
      templateId: "modern_single",
      revision: 8,
    }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Modern template" })).toHaveAttribute("aria-pressed", "true"),
    );
    // No new run was started, and the choice is kept for this and the next application.
    expect(postedBody(fetchMock, "/generation/runs")).toBeNull();
    expect(props.onPreparationSettingsChange).toHaveBeenLastCalledWith(
      "application",
      expect.objectContaining({
        formatting: expect.objectContaining({ resumeTemplateId: "modern_single", coverLetterTemplateId: "modern_single" }),
      }),
    );
    expect(window.localStorage.getItem("rufina.document-template")).toBe("modern_single");
  });

  it("uses the template picked last for a new application", async () => {
    window.localStorage.setItem("rufina.document-template", "modern_single");
    const fetchMock = installApplicationWorkspaceApiMock({
      startedGenerationRun: generationRun({ status: "queued", stage: "sources", revision: 1 }),
    });
    renderApplicationWorkspace(createWorkspaceApplication());

    fireEvent.click(await screen.findByRole("button", { name: "Tailor resume" }));

    await waitFor(() => expect(postedBody(fetchMock, "/generation/runs")).not.toBeNull());
    expect(postedBody(fetchMock, "/generation/runs").formattingParameters.tailored_resume.templateId).toBe("modern_single");
  });

  it("tailors again with a change request as a new version", async () => {
    const current = completedRun();
    const fetchMock = installApplicationWorkspaceApiMock({
      currentGenerationRun: current,
      generationRuns: [current],
      startedGenerationRun: generationRun({ id: "run-2", status: "queued", stage: "sources", revision: 1 }),
    });
    renderApplicationWorkspace(createWorkspaceApplication());

    fireEvent.change(await screen.findByRole("textbox", { name: "Change request" }), {
      target: { value: "Shorter summary." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tailor again" }));

    await waitFor(() => expect(postedBody(fetchMock, "/generation/runs")).not.toBeNull());
    expect(postedBody(fetchMock, "/generation/runs").userPreferences).toBe("Shorter summary.");
    expect(await screen.findByRole("heading", { name: "Tailoring your documents" })).toBeInTheDocument();
  });

  it("opens the options from a result and returns without starting a run", async () => {
    const current = completedRun();
    const fetchMock = installApplicationWorkspaceApiMock({ currentGenerationRun: current, generationRuns: [current] });
    renderApplicationWorkspace(createWorkspaceApplication());

    fireEvent.click(await screen.findByRole("button", { name: "Options" }));
    expect(screen.getByRole("heading", { name: "Tailor again" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to documents" }));

    expect(await screen.findByRole("complementary", { name: "Tailoring summary" })).toBeInTheDocument();
    expect(postedBody(fetchMock, "/generation/runs")).toBeNull();
  });

  it("explains a cover letter that did not pass the fact check", async () => {
    const base = completedRun();
    const current = completedRun({
      result: {
        ...base.result,
        documents: base.result.documents?.filter((item) => item.type === "tailored_resume"),
      },
    });
    installApplicationWorkspaceApiMock({ currentGenerationRun: current, generationRuns: [current] });
    renderApplicationWorkspace(createWorkspaceApplication());

    expect(await screen.findByRole("tab", { name: "Cover letter" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "CV" })).toHaveAttribute("aria-selected", "true");
  });

  it("still shows documents of a run made by the earlier pipeline", async () => {
    const base = completedRun();
    const legacy = completedRun({
      result: {
        documents: base.result.documents,
        review: { meaningfulChanges: ["Led with design systems experience"] },
      },
      events: [
        {
          sequence: 1,
          kind: "run.created",
          stage: "sources",
          data: { documentTemplateId: "roman", resumeTemplateId: "roman" },
          createdAt: "2026-09-13T10:00:00.000Z",
        },
      ],
      artifacts: [artifact("artifact-cv", "tailored_resume", "resume_pdf", "acme-cv.pdf", "roman")],
      checks: [],
    });
    installApplicationWorkspaceApiMock({ currentGenerationRun: legacy, generationRuns: [legacy] });
    renderApplicationWorkspace(createWorkspaceApplication());

    const summary = await screen.findByRole("complementary", { name: "Tailoring summary" });
    expect(within(summary).getByText("Led with design systems experience")).toBeInTheDocument();
    expect(within(summary).queryByText("Vacancy match")).not.toBeInTheDocument();
    // The Times-style template of the earlier generator is today's Swiss Classic.
    expect(await screen.findByRole("button", { name: "Swiss Classic template" })).toHaveAttribute("aria-pressed", "true");
  });

  it("marks the application submitted from a finished result", async () => {
    const current = completedRun();
    installApplicationWorkspaceApiMock({ currentGenerationRun: current, generationRuns: [current] });
    const onStatusChange = () => undefined;
    const { props } = renderApplicationWorkspace(createWorkspaceApplication(), { onStatusChange });

    expect(await screen.findByRole("button", { name: "Mark submitted" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Download PDF" })).toBeEnabled();
    expect(props.onStatusChange).toBe(onStatusChange);
  });
});
