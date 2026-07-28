import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildDocumentGenerationPrompt } from "@/components/application-workspace";
import { AI_GENERATION_REQUEST_TIMEOUT_MS } from "@/lib/api-client";
import {
  createLegacyWorkspaceApplication,
  createV3WorkspaceApplication,
  createWorkspaceApplicationWithoutGuide,
  createWorkspaceProfile,
  installApplicationWorkspaceApiMock,
  renderApplicationWorkspace,
} from "@/test/application-workspace-harness";

describe("cover letter generation prompt", () => {
  it("requires a recruiter-friendly second paragraph instead of copied CV metrics", () => {
    const prompt = buildDocumentGenerationPrompt("English");

    expect(prompt).toContain(
      "The second substantive body paragraph must give a concise, recruiter-friendly synthesis",
    );
    expect(prompt).toContain(
      "Do not copy, closely paraphrase, enumerate, or compress achievement bullets from the resume in this paragraph.",
    );
    expect(prompt).toContain(
      "Do not include metrics, percentages, counts, revenue, time savings, or other numbers in this paragraph.",
    );
    expect(prompt).toContain(
      "Include at most one concise, verified example elsewhere in the letter",
    );
    expect(prompt).toContain(
      "Fill every editable field in the bundled cover-letter template instead of leaving placeholder text unchanged.",
    );
    expect(prompt).toContain(
      "Keep the recipient block in exactly four lines",
    );
    expect(prompt).toContain(
      "street and building number; postal code, city, and country",
    );
    expect(prompt).toContain(
      "confirmation:company-header-research",
    );
    expect(prompt).toContain(
      "immediately after the greeting the first substantive sentence must naturally state that the candidate knows or has spoken with that employee",
    );
    expect(prompt).toContain(
      "strengthened the candidate's positive impression of the company and interest in the role",
    );
    expect(prompt).toContain(
      "never claim or imply that the employee recommended, endorsed, or recruited the candidate",
    );
    expect(prompt).not.toContain(
      "a paragraph with the strongest matching evidence",
    );
  });
});

const consent = {
  consentVersion: "2026-07-18.v2",
  consentedAt: "2026-07-25T10:00:00.000Z",
  hasCurrentConsent: true,
};

const resumeDesign = {
  accentColor: "#2B2B2B",
  fontFamily: "Georgia",
  fontScale: 1,
  density: "standard",
  pageMargins: { top: 15, right: 15, bottom: 15, left: 15 },
  headingStyle: "underlined",
  skillsStyle: "inline",
  sidebarWidth: 0,
  sidebarSections: [],
};

const generationResumeTemplates = [
  {
    id: "4ce57ea1-74a2-44cb-90c2-bfe24c549233",
    kind: "custom",
    name: "My Swiss CV",
    description: "Personal design based on Modern Two Column.",
    layout: "two_column",
    columns: 2,
    baseTemplateId: "modern_two_column",
    version: 2,
    designJson: {
      ...resumeDesign,
      accentColor: "#8A1538",
      fontFamily: "Inter",
      sidebarWidth: 32,
      sidebarSections: ["skills", "education"],
    },
  },
  {
    id: "classic_single",
    kind: "bundled",
    name: "Classic",
    description: "Traditional single-column resume.",
    layout: "single_column",
    columns: 1,
    baseTemplateId: "classic_single",
    designJson: resumeDesign,
  },
  {
    id: "modern_single",
    kind: "bundled",
    name: "Modern",
    description: "Modern single-column resume.",
    layout: "single_column",
    columns: 1,
    baseTemplateId: "modern_single",
    designJson: {
      ...resumeDesign,
      accentColor: "#176B87",
      fontFamily: "Inter",
    },
  },
  {
    id: "modern_two_column",
    kind: "bundled",
    name: "Modern two-column",
    description: "Modern resume with a sidebar.",
    layout: "two_column",
    columns: 2,
    baseTemplateId: "modern_two_column",
    designJson: {
      ...resumeDesign,
      accentColor: "#243B53",
      fontFamily: "Inter",
      sidebarWidth: 32,
      sidebarSections: ["skills", "education"],
    },
  },
];

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
      await screen.findByText("Master Resume · v1 confirmed"),
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

  it("offers personal and built-in templates and persists a custom UUID", async () => {
    window.localStorage.removeItem(
      "tasko.resume-template.v1.application-v3",
    );
    installApplicationWorkspaceApiMock({
      resumeTemplates: generationResumeTemplates,
    });
    renderApplicationWorkspace(createV3WorkspaceApplication());

    const selector = await screen.findByRole("combobox", {
      name: "Resume template",
    });
    expect(
      within(selector)
        .getAllByRole("option")
        .map((option) => option.getAttribute("value")),
    ).toEqual([
      "4ce57ea1-74a2-44cb-90c2-bfe24c549233",
      "classic_single",
      "modern_single",
      "modern_two_column",
    ]);
    expect(
      within(selector).getByRole("group", { name: "My templates" }),
    ).toBeInTheDocument();
    expect(
      within(selector).getByRole("group", { name: "Built-in" }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Use My Swiss CV resume template",
      }),
    );
    expect(selector).toHaveValue("4ce57ea1-74a2-44cb-90c2-bfe24c549233");
    expect(
      window.localStorage.getItem(
        "tasko.resume-template.v1.application-v3",
      ),
    ).toBe("4ce57ea1-74a2-44cb-90c2-bfe24c549233");
    window.localStorage.removeItem(
      "tasko.resume-template.v1.application-v3",
    );
  });

  it("falls back when the persisted custom template was deleted", async () => {
    window.localStorage.setItem(
      "tasko.resume-template.v1.application-v3",
      "deleted-custom-template",
    );
    installApplicationWorkspaceApiMock();
    renderApplicationWorkspace(createV3WorkspaceApplication());

    const selector = await screen.findByRole("combobox", {
      name: "Resume template",
    });
    await waitFor(() => expect(selector).toHaveValue("classic_single"));
    expect(
      screen.getByText(
        "Your previously selected resume template is no longer available. An available built-in template was selected.",
      ),
    ).toBeInTheDocument();
    expect(
      window.localStorage.getItem(
        "tasko.resume-template.v1.application-v3",
      ),
    ).toBe("classic_single");
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
            applicationId: "application-v3",
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
    fireEvent.click(
      screen.getByRole("button", { name: /Final review/ }),
    );
    const finalReviewHeading = await screen.findByRole("heading", {
      name: "Review, download and apply",
    });
    const finalReviewSection = finalReviewHeading.closest("section");
    expect(finalReviewSection).not.toBeNull();
    expect(
      within(finalReviewSection as HTMLElement).getByRole("link", {
        name: "DOCX",
      }),
    ).toHaveAttribute(
      "href",
      "http://localhost:8000/resume-tailoring/ats-final-review/ats-review-1/docx?templateId=classic_single",
    );
    expect(
      within(finalReviewSection as HTMLElement).getByRole("link", {
        name: "DOCX",
      }),
    ).toHaveAttribute("download", "Alex-Morgan-resume.docx");
  });

  it("re-renders a ready FinalResume with a custom UUID without rerunning AI", async () => {
    const customTemplateId = generationResumeTemplates[0].id;
    window.localStorage.setItem(
      "tasko.resume-template.v1.application-v3",
      customTemplateId,
    );
    const classic = generatedPdfDocument("classic_single");
    const custom = {
      ...generatedPdfDocument(customTemplateId),
      id: "pdf-document-custom",
    };
    const requestOrder: string[] = [];
    const fetchMock = installApplicationWorkspaceApiMock({
      documents: [classic],
      resumeTemplates: generationResumeTemplates,
      aiPrivacySettings: { hasCurrentConsent: false },
      requestHandler: async (url, method, init) => {
        if (
          url.pathname === `/documents/${classic.id}` &&
          method === "GET"
        ) {
          return Response.json(classic);
        }
        if (
          url.pathname === `/documents/${classic.id}/download` &&
          method === "GET"
        ) {
          return new Response(new Blob(["%PDF-classic"]));
        }
        if (
          url.pathname ===
            "/resume-tailoring/ats-final-review/ats-review-1/pdf" &&
          method === "GET"
        ) {
          requestOrder.push(`pdf:${url.searchParams.get("templateId")}`);
          return new Response(new Blob(["%PDF-custom"]), {
            headers: { "X-Rufina-Document-Id": custom.id },
          });
        }
        if (
          url.pathname === `/documents/${custom.id}/attachments` &&
          method === "POST"
        ) {
          requestOrder.push("attach");
          expect(JSON.parse(String(init?.body))).toEqual({
            applicationId: "application-v3",
          });
          return Response.json(custom);
        }
        if (
          url.pathname === `/documents/${custom.id}` &&
          method === "GET"
        ) {
          return Response.json(custom);
        }
        if (
          url.pathname === `/documents/${custom.id}/download` &&
          method === "GET"
        ) {
          return new Response(new Blob(["%PDF-custom"]));
        }
        return undefined;
      },
    });
    const { props } = renderApplicationWorkspace(
      createV3WorkspaceApplication(),
    );

    const selector = await screen.findByRole("combobox", {
      name: "Resume template",
    });
    await waitFor(() => expect(selector).toHaveValue(customTemplateId));
    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));

    await waitFor(
      () => expect(props.onDocumentAttached).toHaveBeenCalledTimes(1),
      { timeout: 4_000 },
    );
    expect(requestOrder).toEqual([`pdf:${customTemplateId}`, "attach"]);
    expect(
      fetchMock.mock.calls.some(([input, init]) =>
        [
          "/resume-tailoring/senior-recruiter-analysis",
          "/resume-tailoring/experience-rewrite",
          "/resume-tailoring/ats-final-review",
        ].some(
          (path) =>
            new URL(String(input)).pathname === path &&
            init?.method === "POST",
        ),
      ),
    ).toBe(false);
    expect(
      screen.queryByRole("dialog", { name: /AI data disclosure/i }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByText(
        "Saved finalResume rendered with the selected template",
      ),
    ).toBeInTheDocument();
    window.localStorage.removeItem(
      "tasko.resume-template.v1.application-v3",
    );
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

  it("uses the built-in cover-letter template without upload or preflight", async () => {
    const fetchMock = installApplicationWorkspaceApiMock();
    renderApplicationWorkspace(createV3WorkspaceApplication());

    expect(
      await screen.findByText("Standard cover letter"),
    ).toBeInTheDocument();
    expect(screen.getByText(/no DOCX upload required/)).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Source cover letter" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Upload DOCX")).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("/documents/templates/preflight"),
      ),
    ).toBe(false);
    expect(
      screen.queryByText("Is a recruiter or hiring contact named?"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Personalize your documents"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Document context")).not.toBeInTheDocument();

    const recruiterName = screen.getByRole("textbox", {
      name: "Recruiter name",
    });
    const companyContactName = screen.getByRole("textbox", {
      name: "Company contact name",
    });
    const generateCoverLetter = screen.getByRole("button", {
      name: "Generate Cover letter",
    });
    expect(
      recruiterName.compareDocumentPosition(generateCoverLetter)
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      recruiterName.compareDocumentPosition(companyContactName)
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      companyContactName.compareDocumentPosition(generateCoverLetter)
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    fireEvent.change(recruiterName, {
      target: { value: "Taylor Smith" },
    });
    fireEvent.change(companyContactName, {
      target: { value: "Marco Rossi" },
    });
    expect(recruiterName).toHaveValue("Taylor Smith");
    expect(companyContactName).toHaveValue("Marco Rossi");
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([input, init]) => (
          String(input).includes("/applications/application-v3/confirmations")
          && init?.method === "PUT"
          && String(init.body).includes('"questionId":"cover-letter-company-contact"')
          && String(init.body).includes('"exampleText":"Marco Rossi"')
        )),
      ).toBe(true);
    });
  });

  it("offers PDF and DOCX downloads for a generated cover letter", async () => {
    const coverLetterDocument = {
      ...generatedPdfDocument("classic_single"),
      id: "cover-letter-downloads",
      type: "cover_letter",
      title: "Cover letter · Senior Product Designer · Acme Labs",
      versions: [
        {
          id: "cover-letter-version",
          version: 1,
          content: JSON.stringify({
            replacements: [
              {
                paragraphId: "paragraph-0002",
                spanId: "paragraph-0002-span-0001",
                original: "Original",
                replacement: "Tailored opening",
                reason: "Role fit",
                evidenceIds: ["vacancy:title"],
              },
            ],
          }),
          createdAt: "2026-07-28T10:00:00.000Z",
          hasRenderedDocx: true,
          hasRenderedArtifact: true,
          artifact: {
            fileName: "Acme-cover-letter.docx",
            contentType:
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            templateId: "standard-cover-letter",
            templateVersion: null,
          },
          factualValidation: { status: "passed" },
          visualValidation: { status: "passed" },
          diff: [],
        },
      ],
    };
    installApplicationWorkspaceApiMock({
      documents: [coverLetterDocument],
    });
    renderApplicationWorkspace(createV3WorkspaceApplication());

    const deleteButton = await screen.findByRole("button", {
      name: "Delete Cover letter",
    });
    const coverLetterCard = deleteButton.closest("article");
    expect(coverLetterCard).not.toBeNull();
    const pdfDownloads = within(coverLetterCard as HTMLElement).getAllByRole(
      "link",
      { name: "PDF" },
    );
    const docxDownloads = within(coverLetterCard as HTMLElement).getAllByRole(
      "link",
      { name: "DOCX" },
    );

    expect(pdfDownloads[0]).toHaveAttribute(
      "href",
      "http://localhost:8000/documents/cover-letter-downloads/pdf",
    );
    expect(pdfDownloads[0]).toHaveAttribute(
      "download",
      "Acme-cover-letter.pdf",
    );
    expect(docxDownloads[0]).toHaveAttribute(
      "href",
      "http://localhost:8000/documents/cover-letter-downloads/download",
    );
    expect(
      pdfDownloads[0].compareDocumentPosition(docxDownloads[0])
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      within(coverLetterCard as HTMLElement).getByText(
        "Download the current cover letter as PDF or editable DOCX.",
      ),
    ).toBeInTheDocument();
  });

  it("does not loop when the application guide is missing", async () => {
    const fetchMock = installApplicationWorkspaceApiMock();
    renderApplicationWorkspace(createWorkspaceApplicationWithoutGuide());

    expect(
      screen.getByText(/does not have a complete application guide v3/),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getAllByRole("button", { name: "Refresh analysis first" }),
      ).toHaveLength(2);
    });
    expect(fetchMock.mock.calls.length).toBeLessThan(12);
  });
});
