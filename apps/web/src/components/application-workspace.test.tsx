import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  createLegacyWorkspaceApplication,
  createV3WorkspaceApplication,
  createWorkspaceProfile,
  createWorkspaceApplicationWithoutGuide,
  installApplicationWorkspaceApiMock,
  renderApplicationWorkspace,
} from "@/test/application-workspace-harness";

const defaultResumeReplacement = {
  blockId: "block-0001",
  spanId: "block-0001-span-0001",
  original: "Summary",
  replacement: "Tailored summary",
  reason: "Matches the role",
  evidenceIds: ["source:block-0001-span-0001"],
};

function resumePipelineResponse(
  prompt: string,
  replacement = defaultResumeReplacement,
) {
  if (prompt.includes("PASS 1 OF 3")) {
    return JSON.stringify({
      missingKeywords: Array.from({ length: 5 }, (_, index) => ({
        keyword: `keyword-${index + 1}`,
        whyItMatters: "Role requirement",
        evidenceStatus: "verified",
        evidenceIds: ["source:block-0001-span-0001"],
      })),
      redFlags: Array.from({ length: 3 }, (_, index) => ({
        flag: `red-flag-${index + 1}`,
        whyItIsVisible: "Visible in a quick scan",
        fix: "Use concise evidence",
      })),
    });
  }
  if (prompt.includes("PASS 2 OF 3")) {
    return JSON.stringify({ replacements: [replacement] });
  }
  return JSON.stringify({
    atsScan: { skippedSections: [] },
    replacements: [replacement],
  });
}

describe("ApplicationWorkspace", () => {
  it("shows an empty state when the route has no application ID", () => {
    renderApplicationWorkspace(null);

    expect(
      screen.getByRole("heading", { name: "No application selected" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Back to applications" }),
    ).toBeInTheDocument();
  });

  it("renders a legacy application and asks for a refreshed analysis", async () => {
    installApplicationWorkspaceApiMock();

    renderApplicationWorkspace(createLegacyWorkspaceApplication());

    expect(
      screen.getByRole("heading", { name: "Senior Product Designer" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Update analysis" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/legacy ai-match-v1 percentage/),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getAllByRole("button", { name: "Select source first" }),
      ).toHaveLength(2);
    });
  });

  it("renders the current v3 application guide", async () => {
    installApplicationWorkspaceApiMock();

    renderApplicationWorkspace(createV3WorkspaceApplication());

    expect(
      screen.getByRole("heading", { name: "Senior Product Designer" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Turn complex B2B workflows into clear, validated product experiences.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Position Alex as a research-led designer/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tablist", { name: "Application analysis" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Refresh analysis" }),
    ).toBeInTheDocument();
    expect(screen.getByText("match-revision-v3")).toBeInTheDocument();
    expect(
      screen.getByText(
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      ),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getAllByRole("button", { name: "Select source first" }),
      ).toHaveLength(2);
    });
  });

  it("saves recipient, employee contact, and additional cover-letter context", async () => {
    const savedPayloads: Array<{ confirmations: Array<{ questionId: string; response: string; exampleText: string }> }> = [];
    installApplicationWorkspaceApiMock({
      requestHandler: async (url, method, init) => {
        if (/^\/applications\/[^/]+\/confirmations$/.test(url.pathname) && method === "PUT") {
          const payload = JSON.parse(String(init?.body)) as { confirmations: Array<{ questionId: string; response: string; exampleText: string }> };
          savedPayloads.push(payload);
          return Response.json(payload.confirmations.map((confirmation) => ({
            ...confirmation,
            requirement: confirmation.questionId,
            blocking: false,
            updatedAt: "2026-07-20T10:00:00.000Z",
          })));
        }
        return undefined;
      },
    });
    renderApplicationWorkspace(createV3WorkspaceApplication());

    fireEvent.click(await screen.findByRole("button", { name: "Yes, use their name" }));
    fireEvent.change(screen.getByLabelText("Recruiter or hiring contact full name"), {
      target: { value: "Anna Müller" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Yes, I know someone" }));
    fireEvent.change(screen.getByLabelText("Known employee full name"), {
      target: { value: "Marco Rossi" },
    });
    fireEvent.change(screen.getByLabelText("Additional cover letter context"), {
      target: { value: "Emphasize the product mission and avoid relocation details." },
    });

    await waitFor(() => expect(savedPayloads.length).toBeGreaterThan(0), { timeout: 2_000 });
    const savedById = Object.fromEntries(
      savedPayloads.at(-1)!.confirmations.map((confirmation) => [confirmation.questionId, confirmation]),
    );
    expect(savedById["cover-letter-recipient-name"]).toMatchObject({
      response: "yes",
      exampleText: "Anna Müller",
    });
    expect(savedById["cover-letter-company-contact"].exampleText).toBe("Marco Rossi");
    expect(savedById["cover-letter-additional-context"].exampleText).toContain("product mission");
  });

  it("builds quick advice only from visible verified evidence sources", async () => {
    const fetchMock = installApplicationWorkspaceApiMock();
    renderApplicationWorkspace(createV3WorkspaceApplication());

    fireEvent.click(screen.getByRole("button", { name: "What should I emphasize?" }));

    expect(await screen.findByText(/Emphasize these source-backed facts/)).toBeInTheDocument();
    expect(screen.getByText(/Experience · achievement/)).toBeInTheDocument();
    expect(screen.getByText(/Six years designing B2B software products/)).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("/assistant/chat")),
    ).toBe(false);
  });

  it("stops hung loaders, reports API unavailable, and retries", async () => {
    vi.useFakeTimers();
    let apiUnavailable = true;
    installApplicationWorkspaceApiMock({
      requestHandler: (_url, _method, init) => {
        if (!apiUnavailable) return undefined;
        return new Promise<Response>((_, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        });
      },
    });

    renderApplicationWorkspace(createV3WorkspaceApplication());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });

    expect(screen.getAllByText("API unavailable").length).toBeGreaterThan(0);
    expect(screen.queryByText("Loading answers")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Retry loading history" })).toHaveLength(2);

    apiUnavailable = false;
    fireEvent.click(screen.getAllByRole("button", { name: "Retry" })[0]);
    await act(async () => {
      await Promise.resolve();
    });
    vi.useRealTimers();

    expect(await screen.findByText("API online")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Select source first" })).toHaveLength(2);
    });
  });

  it("sends only candidate answers when saving confirmations", async () => {
    const application = createV3WorkspaceApplication();
    application.job.aiMatch?.applicationGuide?.clarificationQuestions?.push({
      id: "production-research",
      requirement: "Production research",
      question: "Have you run research for a production product?",
      why: "The role requires evidence from shipped products.",
      claimIfConfirmed: "Led production product research.",
      blocking: true,
    });
    const fetchMock = installApplicationWorkspaceApiMock({
      confirmationPutResponse: [
        {
          questionId: "production-research",
          requirement: "Production research",
          response: "yes",
          exampleText: "Led customer interviews before two production launches.",
          blocking: true,
          updatedAt: "2026-07-18T10:00:00.000Z",
        },
      ],
    });

    renderApplicationWorkspace(application);

    expect(
      await screen.findByText("Have you run research for a production product?"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "yes" }));
    fireEvent.change(
      screen.getByPlaceholderText("Add a true, concrete example"),
      {
        target: {
          value: "Led customer interviews before two production launches.",
        },
      },
    );

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([, init]) => init?.method === "PUT"),
      ).toBe(true);
    });
    const putCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "PUT",
    );
    expect(putCall).toBeDefined();
    expect(JSON.parse(String(putCall?.[1]?.body))).toEqual({
      confirmations: [
        {
          questionId: "production-research",
          response: "yes",
          exampleText: "Led customer interviews before two production launches.",
        },
      ],
    });
  });

  it("blocks generation until edited confirmations are saved", async () => {
    const application = createV3WorkspaceApplication();
    application.job.aiMatch?.applicationGuide?.clarificationQuestions?.push({
      id: "production-research",
      requirement: "Production research",
      question: "Have you run research for a production product?",
      why: "The role requires production evidence.",
      claimIfConfirmed: "Led production product research.",
      blocking: true,
    });
    const uploadedAt = "2026-07-18T10:00:00.000Z";
    const sources = [
      {
        id: "resume-source",
        category: "CV / Resume",
        title: "Main CV",
        language: "English",
        file_name: "resume.docx",
        file_size: "24 KB",
        file_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        uploaded_at: uploadedAt,
        data_url: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,resume",
      },
      {
        id: "cover-source",
        category: "Cover Letter",
        title: "Main cover",
        language: "English",
        file_name: "cover.docx",
        file_size: "16 KB",
        file_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        uploaded_at: uploadedAt,
        data_url: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cover",
      },
    ];
    const templates = [
      { id: "resume-template", type: "tailored_resume", name: `Main CV · ${uploadedAt}`, fileName: "resume.docx", createdAt: uploadedAt, updatedAt: uploadedAt },
      { id: "cover-template", type: "cover_letter", name: `Main cover · ${uploadedAt}`, fileName: "cover.docx", createdAt: uploadedAt, updatedAt: uploadedAt },
    ];
    const savedConfirmation = {
      questionId: "production-research",
      requirement: "Production research",
      response: "yes",
      exampleText: "Led interviews before a production launch.",
      blocking: true,
      updatedAt: uploadedAt,
    };
    const fetchMock = installApplicationWorkspaceApiMock({
      confirmations: [savedConfirmation],
      confirmationPutResponse: [{
        ...savedConfirmation,
        exampleText: "Led interviews before two production launches.",
      }],
      templates,
      aiPrivacySettings: {
        consentVersion: "2026-07-18.v2",
        consentedAt: uploadedAt,
        hasCurrentConsent: true,
      },
    });
    renderApplicationWorkspace(application, {
      profile: createWorkspaceProfile({ documents: JSON.stringify(sources) }),
    });

    const generatePack = await screen.findByRole("button", { name: "Generate both documents" });
    await waitFor(() => expect(generatePack).toBeEnabled());
    fireEvent.change(screen.getByPlaceholderText("Add a true, concrete example"), {
      target: { value: "Led interviews before two production launches." },
    });

    expect(generatePack).toBeDisabled();
    fireEvent.click(generatePack);
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("/assistant/chat")),
    ).toBe(false);
    await waitFor(() => expect(generatePack).toBeEnabled(), { timeout: 2_000 });
  });

  it("persists an incomplete required confirmation as a draft", async () => {
    const application = createV3WorkspaceApplication();
    application.job.aiMatch?.applicationGuide?.clarificationQuestions?.push({
      id: "production-research",
      requirement: "Production research",
      question: "Have you run research for a production product?",
      why: "The role requires evidence from shipped products.",
      claimIfConfirmed: "Led production product research.",
      blocking: true,
    });
    const fetchMock = installApplicationWorkspaceApiMock({
      confirmationPutResponse: [
        {
          questionId: "production-research",
          requirement: "Production research",
          response: "yes",
          exampleText: "",
          blocking: true,
          updatedAt: "2026-07-18T10:00:00.000Z",
        },
      ],
    });

    renderApplicationWorkspace(application);
    fireEvent.click(await screen.findByRole("button", { name: "yes" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([, init]) => {
          if (init?.method !== "PUT") return false;
          return JSON.stringify(JSON.parse(String(init.body))) === JSON.stringify({
            confirmations: [
              {
                questionId: "production-research",
                response: "yes",
                exampleText: "",
              },
            ],
          });
        }),
      ).toBe(true);
    });
    expect(screen.getByText(/Add a specific example/)).toBeInTheDocument();
  });

  it("warns before downloading an outdated and unvalidated document", async () => {
    installApplicationWorkspaceApiMock({
      documents: [
        {
          id: "document-resume",
          type: "tailored_resume",
          title: "Tailored CV",
          jobId: "job-product-designer",
          applicationIds: ["application-v3"],
          currentVersion: 1,
          createdAt: "2026-07-17T10:00:00.000Z",
          updatedAt: "2026-07-17T10:00:00.000Z",
          generationFingerprint: "a".repeat(64),
          currentGenerationFingerprint: "c".repeat(64),
          generationModel: "test-model",
          inputVersions: {},
          versions: [
            {
              id: "document-resume-v1",
              version: 1,
              content: "Tailored resume content",
              createdAt: "2026-07-17T10:00:00.000Z",
              hasRenderedDocx: false,
              factualValidation: { status: "pending" },
              visualValidation: { status: "pending" },
              diff: [],
            },
          ],
        },
      ],
    });
    const confirmDownload = vi.spyOn(window, "confirm").mockReturnValue(false);

    renderApplicationWorkspace(createV3WorkspaceApplication());

    expect(await screen.findByText("Outdated · v1")).toBeInTheDocument();
    const downloadLink = screen
      .getAllByRole("link", { name: "DOCX" })
      .find((link) => !link.getAttribute("href")?.includes("?version="));

    expect(downloadLink).toBeDefined();
    if (!downloadLink)
      throw new Error("Current document download link is missing");
    expect(fireEvent.click(downloadLink)).toBe(false);
    expect(confirmDownload).toHaveBeenCalledWith(
      expect.stringMatching(
        /fingerprint is outdated.*factual validation has not passed.*automated structural checks have not passed.*rendered document artifact is not available/,
      ),
    );
  });

  it("labels CV content as changes and explains the automated structural checks", async () => {
    installApplicationWorkspaceApiMock({
      documents: [
        {
          id: "validated-resume",
          type: "tailored_resume",
          title: "Validated CV",
          jobId: "job-product-designer",
          applicationIds: ["application-v3"],
          currentVersion: 1,
          createdAt: "2026-07-17T10:00:00.000Z",
          updatedAt: "2026-07-17T10:00:00.000Z",
          generationFingerprint: "b".repeat(64),
          currentGenerationFingerprint: "b".repeat(64),
          generationModel: "test-model",
          inputVersions: {},
          versions: [
            {
              id: "validated-resume-v1",
              version: 1,
              content: JSON.stringify({
                replacements: [
                  {
                    blockId: "summary",
                    spanId: "summary-span-0001",
                    replacement: "Research-led product designer",
                    reason: "Matches the role positioning",
                    evidenceIds: ["profile:headline"],
                  },
                ],
              }),
              createdAt: "2026-07-17T10:00:00.000Z",
              hasRenderedDocx: true,
              factualValidation: { status: "passed" },
              visualValidation: {
                status: "passed",
                sourcePageCount: 2,
                renderedPageCount: 2,
                pageCountChanged: false,
                sourceTextBoxCount: 48,
                renderedTextBoxCount: 49,
                missingTextCount: 0,
                disappearedSourceTextCount: 0,
                textGeometryChangedCount: 0,
                textOutsidePageCount: 0,
                sourceImageCount: 2,
                renderedImageCount: 2,
                sourceImageBoxCount: 2,
                renderedImageBoxCount: 2,
                missingSourceImageCount: 0,
                missingPdfImageCount: 0,
                imageGeometryChangedCount: 0,
                imageOutsidePageCount: 0,
                sourceLinkCount: 3,
                renderedLinkCount: 3,
                missingLinkCount: 0,
                addedLinkCount: 0,
                sourcePdfLinkCount: 3,
                renderedPdfLinkCount: 3,
                missingPdfLinkCount: 0,
                addedPdfLinkCount: 0,
                linkLocationChangedCount: 0,
                linksPreserved: true,
                tableOverflow: false,
                cellOverflowCount: 0,
                tableStructureIssueCount: 0,
                issues: [],
              },
              diff: [],
            },
          ],
        },
      ],
    });

    renderApplicationWorkspace(createV3WorkspaceApplication());

    expect(await screen.findByText("CV change list")).toBeInTheDocument();
    expect(screen.getByText(/not a visual DOCX preview/)).toBeInTheDocument();
    expect(screen.getByText("Rendered geometry checks")).toBeInTheDocument();
    expect(screen.getByText("2 source → 2 rendered · unchanged")).toBeInTheDocument();
    expect(screen.getByText("48 → 49 boxes · 0 PDF missing · 0 source lost · 0 moved · 0 outside")).toBeInTheDocument();
    expect(screen.getByText("DOCX 2 → 2 · PDF boxes 2 → 2 · 0 DOCX missing · 0 PDF missing · 0 moved · 0 outside")).toBeInTheDocument();
    expect(screen.getByText("DOCX 3 → 3 · PDF 3 → 3 · 0 moved")).toBeInTheDocument();
    expect(screen.getByText("0 page · 0 cell overflow · 0 table structure")).toBeInTheDocument();
    expect(screen.getByText("0 issues")).toBeInTheDocument();
    expect(screen.queryByText(/Visual validation/i)).not.toBeInTheDocument();
  });

  it("loads server-side consent and revokes it with stored AI documents", async () => {
    const fetchMock = installApplicationWorkspaceApiMock({
      aiPrivacySettings: {
        consentVersion: "2026-07-18.v2",
        consentedAt: "2026-07-18T10:00:00.000Z",
        hasCurrentConsent: true,
      },
      documents: [{
        id: "document-delete",
        type: "tailored_resume",
        title: "Tailored CV",
        jobId: "job-product-designer",
        applicationIds: ["application-v3"],
        currentVersion: 1,
        createdAt: "2026-07-18T10:00:00.000Z",
        updatedAt: "2026-07-18T10:00:00.000Z",
        generationFingerprint: null,
        currentGenerationFingerprint: null,
        generationModel: null,
        inputVersions: {},
        versions: [{
          id: "document-delete-v1",
          version: 1,
          content: "CV content",
          createdAt: "2026-07-18T10:00:00.000Z",
          hasRenderedDocx: false,
          factualValidation: {},
          visualValidation: {},
          diff: [],
        }],
      }],
      templates: [{
        id: "template-delete",
        type: "cover_letter",
        name: "Stored cover letter",
        fileName: "cover.docx",
        createdAt: "2026-07-18T10:00:00.000Z",
        updatedAt: "2026-07-18T10:00:00.000Z",
      }],
    });

    renderApplicationWorkspace(createV3WorkspaceApplication());

    expect(await screen.findByText("AI provider:")).toBeInTheDocument();
    expect(screen.getByText("OpenAI via OpenClaw/Codex")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Revoke consent" }));
    await waitFor(() => {
      expect(screen.getByText("Consent required")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Delete Tailored CV" })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Delete template Stored cover letter" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input, init]) => String(input).includes("/privacy/ai-consent") && init?.method === "DELETE")).toBe(true);
  });

  it("reuses the resume artifact and recovers a committed pack after response loss", async () => {
    const uploadedAt = "2026-07-18T10:00:00.000Z";
    const sources = [
      {
        id: "resume-source",
        title: "Main CV",
        category: "CV / Resume",
        language: "English",
        file_name: "resume.docx",
        file_size: "20 KB",
        file_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        uploaded_at: uploadedAt,
        data_url: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cv",
      },
      {
        id: "cover-source",
        title: "Main cover",
        category: "Cover Letter",
        language: "English",
        file_name: "cover.docx",
        file_size: "16 KB",
        file_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        uploaded_at: uploadedAt,
        data_url: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cover",
      },
    ];
    const templates = [
      { id: "resume-template", type: "tailored_resume", name: `Main CV · ${uploadedAt}`, fileName: "resume.docx", createdAt: uploadedAt, updatedAt: uploadedAt },
      { id: "cover-template", type: "cover_letter", name: `Main cover · ${uploadedAt}`, fileName: "cover.docx", createdAt: uploadedAt, updatedAt: uploadedAt },
    ];
    const savedDocuments = [
      {
        id: "saved-resume",
        type: "tailored_resume",
        title: "Tailored CV",
        jobId: "job-product-designer",
        applicationIds: ["application-v3"],
        currentVersion: 1,
        createdAt: uploadedAt,
        updatedAt: uploadedAt,
        generationFingerprint: "a".repeat(64),
        currentGenerationFingerprint: "a".repeat(64),
        generationModel: "test-model",
        inputVersions: {},
        versions: [],
      },
      {
        id: "saved-cover",
        type: "cover_letter",
        title: "Cover letter",
        jobId: "job-product-designer",
        applicationIds: ["application-v3"],
        currentVersion: 1,
        createdAt: uploadedAt,
        updatedAt: uploadedAt,
        generationFingerprint: "b".repeat(64),
        currentGenerationFingerprint: "b".repeat(64),
        generationModel: "test-model",
        inputVersions: {},
        versions: [],
      },
    ];
    const recoveredPack = {
      packJobId: "server-uses-request-id",
      status: "completed",
      persistenceMode: "atomic",
      documents: savedDocuments,
      stages: [],
      message: "Application pack saved atomically",
    };
    let assistantCalls = 0;
    let packPostCalls = 0;
    let submittedResume: Record<string, unknown> | undefined;
    installApplicationWorkspaceApiMock({
      templates,
      aiPrivacySettings: {
        consentVersion: "2026-07-18.v2",
        consentedAt: "2026-07-18T10:00:00.000Z",
        hasCurrentConsent: true,
      },
      requestHandler: async (url, method, init) => {
        if (url.pathname === "/assistant/chat" && method === "POST") {
          assistantCalls += 1;
          const request = JSON.parse(String(init?.body)) as {
            message: string;
            generationContext?: { documentType?: string };
          };
          return Response.json({
            message: request.generationContext?.documentType === "tailored_resume"
              ? resumePipelineResponse(request.message)
              : JSON.stringify({ replacements: [{ paragraphId: "paragraph-0002", spanId: "paragraph-0002-span-0001", original: "Reusable body", replacement: "Role-specific body", reason: "Matches the role", evidenceIds: ["source:paragraph-0002-span-0001"] }] }),
            metadata: { generationArtifactId: `generation-artifact-${assistantCalls}` },
          });
        }
        if (url.pathname === "/documents/packs/validate-resume" && method === "POST") {
          return Response.json({
            status: "passed",
            validation: {},
            validationArtifactId: "artifact-1",
            expiresAt: "2026-07-18T10:30:00.000Z",
          });
        }
        if (url.pathname === "/documents/packs" && method === "POST") {
          packPostCalls += 1;
          submittedResume = (JSON.parse(String(init?.body)) as { resume: Record<string, unknown> }).resume;
          throw new TypeError("response lost");
        }
        if (/^\/documents\/packs\/application-pack-/.test(url.pathname) && method === "GET") {
          return Response.json(recoveredPack);
        }
        return undefined;
      },
    });

    const { props } = renderApplicationWorkspace(
      createV3WorkspaceApplication(),
      { profile: createWorkspaceProfile({ documents: JSON.stringify(sources) }) },
    );

    const generatePack = await screen.findByRole("button", { name: "Generate both documents" });
    await waitFor(() => expect(generatePack).toBeEnabled());
    fireEvent.click(generatePack);

    expect(
      await screen.findByText(/recovered after response loss/, {}, { timeout: 4_000 }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/No pack documents were saved/)).not.toBeInTheDocument();
    expect(submittedResume?.validationArtifactId).toBe("artifact-1");
    expect(submittedResume?.generationArtifactId).toBe("generation-artifact-3");
    expect(submittedResume).not.toHaveProperty("content");
    expect(submittedResume).not.toHaveProperty("generationModel");
    expect(submittedResume).not.toHaveProperty("templateId");
    expect(packPostCalls).toBe(3);
    expect(props.onDocumentAttached).toHaveBeenCalledTimes(2);
  });

  it("automatically regenerates a CV after factual validation rejects the first draft", async () => {
    const uploadedAt = "2026-07-18T10:00:00.000Z";
    const source = {
      id: "resume-source",
      title: "Main CV",
      category: "CV / Resume",
      language: "English",
      file_name: "resume.docx",
      file_size: "20 KB",
      file_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      uploaded_at: uploadedAt,
      data_url: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cv",
    };
    const templates = [
      { id: "resume-template", type: "tailored_resume", name: `Main CV · ${uploadedAt}`, fileName: "resume.docx", createdAt: uploadedAt, updatedAt: uploadedAt },
    ];
    const savedDocument = {
      id: "saved-resume",
      type: "tailored_resume",
      title: "Tailored CV",
      jobId: "job-product-designer",
      applicationIds: ["application-v3"],
      currentVersion: 1,
      createdAt: uploadedAt,
      updatedAt: uploadedAt,
      generationFingerprint: "a".repeat(64),
      currentGenerationFingerprint: "a".repeat(64),
      generationModel: "test-model",
      inputVersions: {},
      versions: [],
    };
    const validationMessage = "Document validation failed: block-0015-span-0003 adds a claim not supported by referenced evidence";
    const assistantPrompts: string[] = [];
    let assistantCalls = 0;
    let saveCalls = 0;
    let finalArtifactId = "";
    installApplicationWorkspaceApiMock({
      templates,
      aiPrivacySettings: {
        consentVersion: "2026-07-18.v2",
        consentedAt: uploadedAt,
        hasCurrentConsent: true,
      },
      requestHandler: async (url, method, init) => {
        if (url.pathname === "/assistant/chat" && method === "POST") {
          assistantCalls += 1;
          const request = JSON.parse(String(init?.body)) as { message: string };
          assistantPrompts.push(request.message);
          return Response.json({
            message: resumePipelineResponse(request.message),
            metadata: { generationArtifactId: `generation-artifact-${assistantCalls}` },
          });
        }
        if (url.pathname === "/documents" && method === "POST") {
          saveCalls += 1;
          const request = JSON.parse(String(init?.body)) as { generationArtifactId: string };
          if (saveCalls === 1) {
            return Response.json({ detail: validationMessage }, { status: 422 });
          }
          finalArtifactId = request.generationArtifactId;
          return Response.json(savedDocument, { status: 201 });
        }
        return undefined;
      },
    });

    const { props } = renderApplicationWorkspace(
      createV3WorkspaceApplication(),
      { profile: createWorkspaceProfile({ documents: JSON.stringify([source]) }) },
    );

    const generateResume = await screen.findByRole("button", { name: "Generate Tailored CV" });
    await waitFor(() => expect(generateResume).toBeEnabled());
    fireEvent.click(generateResume);

    await waitFor(() => expect(props.onDocumentAttached).toHaveBeenCalledTimes(1), { timeout: 4_000 });
    const tailoringProgress = screen.getByRole("group", {
      name: "Resume tailoring progress",
    });
    expect(
      within(tailoringProgress).getAllByRole("listitem", {
        name: /completed$/,
      }),
    ).toHaveLength(5);
    expect(
      within(tailoringProgress).getByText(
        "PDF rendered, validated, and saved",
      ),
    ).toBeInTheDocument();
    expect(within(tailoringProgress).getByText("attempt 2")).toBeInTheDocument();
    expect(assistantCalls).toBe(6);
    expect(saveCalls).toBe(2);
    expect(finalArtifactId).toBe("generation-artifact-6");
    expect(assistantPrompts[5]).toContain("previous final draft failed validation");
    expect(assistantPrompts[5]).toContain("block-0015-span-0003");
    expect(assistantPrompts[5]).toContain("PREVIOUS_FINAL_DRAFT_JSON");
    expect(assistantPrompts[5]).toContain("Tailored summary");
    expect(screen.queryByText(validationMessage)).not.toBeInTheDocument();
  });

  it("applies a document-chat instruction and saves a validated new CV version", async () => {
    const uploadedAt = "2026-07-18T10:00:00.000Z";
    const source = {
      id: "resume-source",
      title: "Main CV",
      category: "CV / Resume",
      language: "English",
      file_name: "resume.docx",
      file_size: "20 KB",
      file_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      uploaded_at: uploadedAt,
      data_url: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cv",
    };
    const assistantPrompts: string[] = [];
    const savedDocument = {
      id: "revised-resume",
      type: "tailored_resume",
      title: "Tailored CV",
      jobId: "job-product-designer",
      applicationIds: ["application-v3"],
      currentVersion: 2,
      createdAt: uploadedAt,
      updatedAt: "2026-07-20T10:00:00.000Z",
      generationFingerprint: "c".repeat(64),
      currentGenerationFingerprint: "c".repeat(64),
      generationModel: "test-model",
      inputVersions: {},
      versions: [],
    };
    installApplicationWorkspaceApiMock({
      templates: [
        { id: "resume-template", type: "tailored_resume", name: `Main CV · ${uploadedAt}`, fileName: "resume.docx", createdAt: uploadedAt, updatedAt: uploadedAt },
      ],
      aiPrivacySettings: {
        consentVersion: "2026-07-18.v2",
        consentedAt: uploadedAt,
        hasCurrentConsent: true,
      },
      requestHandler: async (url, method, init) => {
        if (url.pathname === "/assistant/chat" && method === "POST") {
          const request = JSON.parse(String(init?.body)) as { message: string };
          assistantPrompts.push(request.message);
          return Response.json({
            message: resumePipelineResponse(request.message, {
              ...defaultResumeReplacement,
              replacement: "Python automation summary",
              reason: "Requested emphasis",
            }),
            metadata: { generationArtifactId: "chat-revision-artifact" },
          });
        }
        if (url.pathname === "/documents" && method === "POST") {
          return Response.json(savedDocument, { status: 201 });
        }
        return undefined;
      },
    });
    const { props } = renderApplicationWorkspace(
      createV3WorkspaceApplication(),
      { profile: createWorkspaceProfile({ documents: JSON.stringify([source]) }) },
    );

    const instruction = await screen.findByLabelText("Document revision instruction");
    fireEvent.change(instruction, { target: { value: "Emphasize my Python automation experience." } });
    const applyInstruction = screen.getByRole("button", { name: "Apply instruction" });
    await waitFor(() => expect(applyInstruction).toBeEnabled());
    fireEvent.click(applyInstruction);

    await waitFor(() => expect(props.onDocumentAttached).toHaveBeenCalledTimes(1));
    expect(assistantPrompts).toHaveLength(3);
    expect(assistantPrompts[0]).toContain("PASS 1 OF 3");
    expect(assistantPrompts[1]).toContain("PASS 2 OF 3");
    expect(assistantPrompts[2]).toContain("PASS 3 OF 3");
    expect(assistantPrompts.every((prompt) => prompt.includes("Emphasize my Python automation experience."))).toBe(true);
    expect(await screen.findByText(/saved a new CV version/)).toBeInTheDocument();
  });

  it("does not save an unchanged CV when both AI drafts contain no replacements", async () => {
    const uploadedAt = "2026-07-18T10:00:00.000Z";
    const source = {
      id: "resume-source",
      title: "Main CV",
      category: "CV / Resume",
      language: "English",
      file_name: "resume.docx",
      file_size: "20 KB",
      file_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      uploaded_at: uploadedAt,
      data_url: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cv",
    };
    const assistantPrompts: string[] = [];
    let assistantCalls = 0;
    let saveCalls = 0;
    installApplicationWorkspaceApiMock({
      templates: [
        { id: "resume-template", type: "tailored_resume", name: `Main CV · ${uploadedAt}`, fileName: "resume.docx", createdAt: uploadedAt, updatedAt: uploadedAt },
      ],
      aiPrivacySettings: {
        consentVersion: "2026-07-18.v2",
        consentedAt: uploadedAt,
        hasCurrentConsent: true,
      },
      requestHandler: async (url, method, init) => {
        if (url.pathname === "/assistant/chat" && method === "POST") {
          assistantCalls += 1;
          const request = JSON.parse(String(init?.body)) as { message: string };
          assistantPrompts.push(request.message);
          return Response.json({
            message: request.message.includes("PASS 3 OF 3")
              ? JSON.stringify({ atsScan: { skippedSections: [] }, replacements: [] })
              : resumePipelineResponse(request.message),
            metadata: { generationArtifactId: `empty-artifact-${assistantCalls}` },
          });
        }
        if (url.pathname === "/documents" && method === "POST") {
          saveCalls += 1;
        }
        return undefined;
      },
    });

    const { props } = renderApplicationWorkspace(
      createV3WorkspaceApplication(),
      { profile: createWorkspaceProfile({ documents: JSON.stringify([source]) }) },
    );

    const generateResume = await screen.findByRole("button", { name: "Generate Tailored CV" });
    await waitFor(() => expect(generateResume).toBeEnabled());
    fireEvent.click(generateResume);

    expect(
      await screen.findAllByText(
        /did not find any evidence-backed changes for the CV/,
      ),
    ).toHaveLength(2);
    const failedProgress = screen.getByRole("group", {
      name: "Resume tailoring progress",
    });
    expect(
      within(failedProgress).getByRole("listitem", {
        name: "ATS final review: failed",
      }),
    ).toBeInTheDocument();
    expect(
      within(failedProgress).getByRole("listitem", {
        name: "Rendering PDF: pending",
      }),
    ).toBeInTheDocument();
    expect(assistantCalls).toBe(3);
    expect(saveCalls).toBe(0);
    expect(props.onDocumentAttached).not.toHaveBeenCalled();
    expect(assistantPrompts[0]).toContain("PASS 1 OF 3");
    expect(assistantPrompts[1]).toContain("PASS 2 OF 3");
    expect(assistantPrompts[2]).toContain("PASS 3 OF 3");
    expect(assistantPrompts[2]).toContain("do not return an empty replacements array");
  });

  it("saves a generated cover letter without a validation repair pass", async () => {
    const uploadedAt = "2026-07-18T10:00:00.000Z";
    const source = {
      id: "cover-source",
      title: "Main cover",
      category: "Cover Letter",
      language: "English",
      file_name: "cover.docx",
      file_size: "16 KB",
      file_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      uploaded_at: uploadedAt,
      data_url: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cover",
    };
    const savedDocument = {
      id: "saved-cover",
      type: "cover_letter",
      title: "Cover letter",
      jobId: "job-product-designer",
      applicationIds: ["application-v3"],
      currentVersion: 1,
      createdAt: uploadedAt,
      updatedAt: uploadedAt,
      generationFingerprint: "b".repeat(64),
      currentGenerationFingerprint: "b".repeat(64),
      generationModel: "test-model",
      inputVersions: {},
      versions: [],
    };
    const assistantPrompts: string[] = [];
    let assistantCalls = 0;
    let saveCalls = 0;
    let finalArtifactId = "";
    installApplicationWorkspaceApiMock({
      templates: [
        { id: "cover-template", type: "cover_letter", name: `Main cover · ${uploadedAt}`, fileName: "cover.docx", createdAt: uploadedAt, updatedAt: uploadedAt },
      ],
      aiPrivacySettings: {
        consentVersion: "2026-07-18.v2",
        consentedAt: uploadedAt,
        hasCurrentConsent: true,
      },
      requestHandler: async (url, method, init) => {
        if (url.pathname === "/assistant/chat" && method === "POST") {
          assistantCalls += 1;
          const request = JSON.parse(String(init?.body)) as { message: string };
          assistantPrompts.push(request.message);
          const message = JSON.stringify({ replacements: [{ paragraphId: "paragraph-0002", spanId: "paragraph-0002-span-0001", original: "Reusable body", replacement: "Evidence-backed role-specific opening", reason: "Uses verified experience", evidenceIds: ["source:paragraph-0002-span-0001"] }] });
          return Response.json({
            message,
            metadata: { generationArtifactId: `cover-artifact-${assistantCalls}` },
          });
        }
        if (url.pathname === "/documents" && method === "POST") {
          saveCalls += 1;
          const request = JSON.parse(String(init?.body)) as { generationArtifactId: string };
          finalArtifactId = request.generationArtifactId;
          return Response.json(savedDocument, { status: 201 });
        }
        return undefined;
      },
    });

    const { props } = renderApplicationWorkspace(
      createV3WorkspaceApplication(),
      { profile: createWorkspaceProfile({ documents: JSON.stringify([source]) }) },
    );

    const generateCover = await screen.findByRole("button", { name: "Generate Cover letter" });
    await waitFor(() => expect(generateCover).toBeEnabled());
    fireEvent.click(generateCover);

    await waitFor(() => expect(props.onDocumentAttached).toHaveBeenCalledTimes(1), { timeout: 4_000 });
    expect(assistantCalls).toBe(1);
    expect(saveCalls).toBe(1);
    expect(finalArtifactId).toBe("cover-artifact-1");
    expect(assistantPrompts[0]).toContain("Act as an experienced career consultant and recruiter");
    expect(assistantPrompts[0]).toContain("employer need → verified candidate evidence → benefit");
    expect(assistantPrompts[0]).toContain("confirmation:cover-letter-additional-context");
    expect(assistantPrompts[0]).toContain("confirmation:cover-letter-company-contact");
    expect(assistantPrompts[0]).toContain("exact vacancy title");
    expect(assistantPrompts[0]).toContain("confirmation:cover-letter-recipient-name");
    expect(assistantPrompts[0]).toContain("approximately 250–350 words");
    expect(assistantPrompts.every((prompt) => prompt.length <= 11_500)).toBe(true);
  });

  it("automatically repairs the CV before generating and saving an application pack", async () => {
    const uploadedAt = "2026-07-18T10:00:00.000Z";
    const sources = [
      {
        id: "resume-source",
        title: "Main CV",
        category: "CV / Resume",
        language: "English",
        file_name: "resume.docx",
        file_size: "20 KB",
        file_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        uploaded_at: uploadedAt,
        data_url: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cv",
      },
      {
        id: "cover-source",
        title: "Main cover",
        category: "Cover Letter",
        language: "English",
        file_name: "cover.docx",
        file_size: "16 KB",
        file_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        uploaded_at: uploadedAt,
        data_url: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cover",
      },
    ];
    const templates = [
      { id: "resume-template", type: "tailored_resume", name: `Main CV · ${uploadedAt}`, fileName: "resume.docx", createdAt: uploadedAt, updatedAt: uploadedAt },
      { id: "cover-template", type: "cover_letter", name: `Main cover · ${uploadedAt}`, fileName: "cover.docx", createdAt: uploadedAt, updatedAt: uploadedAt },
    ];
    const savedDocuments = [
      {
        id: "saved-resume",
        type: "tailored_resume",
        title: "Tailored CV",
        jobId: "job-product-designer",
        applicationIds: ["application-v3"],
        currentVersion: 1,
        createdAt: uploadedAt,
        updatedAt: uploadedAt,
        generationFingerprint: "a".repeat(64),
        currentGenerationFingerprint: "a".repeat(64),
        generationModel: "test-model",
        inputVersions: {},
        versions: [],
      },
      {
        id: "saved-cover",
        type: "cover_letter",
        title: "Cover letter",
        jobId: "job-product-designer",
        applicationIds: ["application-v3"],
        currentVersion: 1,
        createdAt: uploadedAt,
        updatedAt: uploadedAt,
        generationFingerprint: "b".repeat(64),
        currentGenerationFingerprint: "b".repeat(64),
        generationModel: "test-model",
        inputVersions: {},
        versions: [],
      },
    ];
    const validationMessage = "Document validation failed: block-0015-span-0003 adds a claim not supported by referenced evidence";
    const assistantPrompts: string[] = [];
    let assistantCalls = 0;
    let validationCalls = 0;
    let submittedResumeArtifactId = "";
    installApplicationWorkspaceApiMock({
      templates,
      aiPrivacySettings: {
        consentVersion: "2026-07-18.v2",
        consentedAt: uploadedAt,
        hasCurrentConsent: true,
      },
      requestHandler: async (url, method, init) => {
        if (url.pathname === "/assistant/chat" && method === "POST") {
          assistantCalls += 1;
          const request = JSON.parse(String(init?.body)) as {
            message: string;
            generationContext?: { documentType?: string };
          };
          assistantPrompts.push(request.message);
          return Response.json({
            message: request.generationContext?.documentType === "tailored_resume"
              ? resumePipelineResponse(request.message)
              : JSON.stringify({ replacements: [{ paragraphId: "paragraph-0002", spanId: "paragraph-0002-span-0001", original: "Reusable body", replacement: "Role-specific body", reason: "Matches the role", evidenceIds: ["source:paragraph-0002-span-0001"] }] }),
            metadata: { generationArtifactId: `generation-artifact-${assistantCalls}` },
          });
        }
        if (url.pathname === "/documents/packs/validate-resume" && method === "POST") {
          validationCalls += 1;
          if (validationCalls === 1) {
            return Response.json({ detail: validationMessage }, { status: 422 });
          }
          return Response.json({
            status: "passed",
            validation: {},
            validationArtifactId: "validation-artifact-2",
            expiresAt: "2026-07-18T10:30:00.000Z",
          });
        }
        if (url.pathname === "/documents/packs" && method === "POST") {
          const request = JSON.parse(String(init?.body)) as { resume: { generationArtifactId: string } };
          submittedResumeArtifactId = request.resume.generationArtifactId;
          return Response.json({
            packJobId: "application-pack-repaired",
            status: "completed",
            persistenceMode: "atomic",
            documents: savedDocuments,
            stages: [],
            message: "Application pack saved atomically",
          });
        }
        return undefined;
      },
    });

    const { props } = renderApplicationWorkspace(
      createV3WorkspaceApplication(),
      { profile: createWorkspaceProfile({ documents: JSON.stringify(sources) }) },
    );

    const generatePack = await screen.findByRole("button", { name: "Generate both documents" });
    await waitFor(() => expect(generatePack).toBeEnabled());
    fireEvent.click(generatePack);

    await waitFor(() => expect(props.onDocumentAttached).toHaveBeenCalledTimes(2), { timeout: 4_000 });
    expect(assistantCalls).toBe(7);
    expect(validationCalls).toBe(2);
    expect(assistantPrompts[5]).toContain("previous final draft failed validation");
    expect(assistantPrompts[5]).toContain("block-0015-span-0003");
    expect(submittedResumeArtifactId).toBe("generation-artifact-6");
    expect(screen.queryByText(validationMessage)).not.toBeInTheDocument();
  });

  it("offers only bundled resume templates without preflighting the source as a template", async () => {
    window.localStorage.removeItem(
      "tasko.resume-template.v1.application-v3",
    );
    const source = {
      id: "large-resume-source",
      title: "Large CV",
      category: "CV / Resume",
      language: "English",
      file_name: "large-resume.docx",
      file_size: "80 KB",
      file_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      uploaded_at: "2026-07-18T10:00:00.000Z",
      data_url: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cv",
    };
    const fetchMock = installApplicationWorkspaceApiMock();

    renderApplicationWorkspace(createV3WorkspaceApplication(), {
      profile: createWorkspaceProfile({ documents: JSON.stringify([source]) }),
    });

    const selector = await screen.findByRole("combobox", { name: "Resume template" });
    expect(selector).toHaveValue("classic_single");
    expect(within(selector).getAllByRole("option").map((option) => option.getAttribute("value"))).toEqual([
      "classic_single",
      "modern_single",
      "modern_two_column",
    ]);
    fireEvent.change(selector, { target: { value: "modern_two_column" } });
    expect(selector).toHaveValue("modern_two_column");
    expect(screen.getByText("Modern two-column resume.")).toBeInTheDocument();
    expect(
      window.localStorage.getItem(
        "tasko.resume-template.v1.application-v3",
      ),
    ).toBe("modern_two_column");
    window.localStorage.removeItem(
      "tasko.resume-template.v1.application-v3",
    );
    expect(screen.getByText("Used as the factual source. Its layout is not used as a template.")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([input, init]) => (
        String(input).includes("/documents/templates/preflight")
        && init?.method === "POST"
      )),
    ).toHaveLength(0);
  });

  it("restores persisted workspace uploads and lets the user delete them", async () => {
    const persistedSource = {
      id: "workspace-source-restored",
      applicationId: "application-v3",
      title: "Reloaded CV",
      category: "CV / Resume",
      language: "English",
      fileName: "reloaded-cv.docx",
      fileSize: "24 KB",
      fileType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      uploadedAt: "2026-07-19T09:00:00.000Z",
      dataUrl: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cv",
    };
    const fetchMock = installApplicationWorkspaceApiMock({
      workspaceSources: [persistedSource],
      requestHandler: (url, method) => {
        if (url.pathname === `/documents/workspace-sources/${persistedSource.id}` && method === "DELETE") {
          return new Response(null, { status: 204 });
        }
        return undefined;
      },
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderApplicationWorkspace(createV3WorkspaceApplication());

    const restoredOption = await screen.findByRole("option", { name: /Reloaded CV · reloaded-cv\.docx/ });
    expect(restoredOption).toBeInTheDocument();
    const deleteButton = await screen.findByRole("button", { name: "Delete uploaded source reloaded-cv.docx" });
    fireEvent.click(deleteButton);

    await waitFor(() => {
      expect(screen.queryByRole("option", { name: /Reloaded CV · reloaded-cv\.docx/ })).not.toBeInTheDocument();
    });
    expect(fetchMock.mock.calls.some(([input, init]) => {
      const url = new URL(String(input));
      return url.pathname === `/documents/workspace-sources/${persistedSource.id}`
        && url.searchParams.get("applicationId") === "application-v3"
        && init?.method === "DELETE";
    })).toBe(true);
  });

  it("persists a newly uploaded DOCX before selecting it", async () => {
    let uploadedRequest: Record<string, string> | undefined;
    installApplicationWorkspaceApiMock({
      requestHandler: (url, method, init) => {
        if (url.pathname !== "/documents/workspace-sources" || method !== "POST") return undefined;
        uploadedRequest = JSON.parse(String(init?.body)) as Record<string, string>;
        return Response.json({
          id: "workspace-source-new",
          applicationId: uploadedRequest.applicationId,
          title: uploadedRequest.title,
          category: uploadedRequest.category,
          language: uploadedRequest.language,
          fileName: uploadedRequest.fileName,
          fileSize: "1 KB",
          fileType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          uploadedAt: "2026-07-19T10:00:00.000Z",
          dataUrl: uploadedRequest.dataUrl,
        }, { status: 201 });
      },
    });

    const { container } = renderApplicationWorkspace(createV3WorkspaceApplication());
    await screen.findByText("API online");
    const file = new File(["docx-content"], "target_cv.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    const uploadInput = container.querySelectorAll<HTMLInputElement>('input[type="file"]')[0];
    fireEvent.change(uploadInput, { target: { files: [file] } });

    expect(await screen.findByRole("option", { name: /target cv · target_cv\.docx/ })).toBeInTheDocument();
    expect(uploadedRequest).toMatchObject({
      applicationId: "application-v3",
      category: "CV / Resume",
      fileName: "target_cv.docx",
    });
    expect(uploadedRequest?.dataUrl).toMatch(/^data:.*;base64,/);
  });

  it("does not loop fingerprint updates when the application guide is missing", async () => {
    const fetchMock = installApplicationWorkspaceApiMock();

    renderApplicationWorkspace(createWorkspaceApplicationWithoutGuide());

    expect(
      screen.getByText(/does not have a complete application guide v3/),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getAllByRole("button", { name: "Select source first" }),
      ).toHaveLength(2);
    });
    expect(fetchMock).toHaveBeenCalledTimes(8);
  });
});
