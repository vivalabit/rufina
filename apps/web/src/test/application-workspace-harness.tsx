import type { ComponentProps } from "react";
import { render } from "@testing-library/react";
import { vi } from "vitest";

import { ApplicationWorkspace } from "@/components/application-workspace";

type ApplicationWorkspaceProps = ComponentProps<typeof ApplicationWorkspace>;
type WorkspaceApplication = NonNullable<
  ApplicationWorkspaceProps["application"]
>;
type WorkspaceJob = WorkspaceApplication["job"];

type ApplicationOverrides = Omit<Partial<WorkspaceApplication>, "job"> & {
  job?: Partial<WorkspaceJob>;
};

type WorkspaceApiOptions = {
  confirmationPutResponse?: unknown[];
  confirmations?: unknown[];
  currentMasterResume?: unknown | null;
  documents?: unknown[];
  resumeTemplates?: unknown[];
  templates?: unknown[];
  workspaceSources?: unknown[];
  aiPrivacySettings?: Partial<{
    currentBackend: "openclaw_codex" | "openai_api";
    consentBackend: "openclaw_codex" | "openai_api" | null;
    consentVersion: string | null;
    consentedAt: string | null;
    hasCurrentConsent: boolean;
    retentionDays: number;
    lastAiActivityAt: string | null;
    aiDataExpiresAt: string | null;
  }>;
  requestHandler?: (
    url: URL,
    method: string,
    init?: RequestInit,
  ) => Response | Promise<Response | undefined> | undefined;
};

const baseJob: Omit<WorkspaceJob, "aiMatch"> = {
  id: "job-product-designer",
  title: "Senior Product Designer",
  company: "Acme Labs",
  location: "Zurich, Switzerland",
  type: "Full-time",
  match: 86,
  overview: "Lead product discovery and delivery for a growing B2B platform.",
  responsibilities: ["Lead discovery", "Partner with product and engineering"],
  requirements: [
    "5+ years of product design experience",
    "Strong research practice",
  ],
  skills: ["Product design", "User research", "Figma"],
  applyUrl: "https://example.com/jobs/product-designer",
};

export function createWorkspaceProfile(
  overrides: Partial<ApplicationWorkspaceProps["profile"]> = {},
): ApplicationWorkspaceProps["profile"] {
  return {
    name: "Alex Morgan",
    current_role: "Product Designer",
    desired_role: "Senior Product Designer",
    location: "Zurich, Switzerland",
    headline: "Product designer for complex B2B workflows",
    skills: "Product design, user research, prototyping",
    experience: "Six years designing B2B software products.",
    education: "BA Interaction Design",
    documents: "",
    resume_file_name: "",
    resume_file_size: "",
    resume_updated_at: "",
    resume_data_url: "",
    ...overrides,
  };
}

export function createLegacyWorkspaceApplication(
  overrides: ApplicationOverrides = {},
): WorkspaceApplication {
  return createWorkspaceApplication({
    ...overrides,
    id: overrides.id ?? "application-legacy",
    job: {
      ...overrides.job,
      aiMatch: overrides.job?.aiMatch ?? {
        version: "ai-match-v1",
        reasons: ["Relevant product design experience"],
        gaps: ["Leadership scope needs validation"],
        updatedAt: "2026-07-01T10:00:00.000Z",
      },
    },
  });
}

export function createV3WorkspaceApplication(
  overrides: ApplicationOverrides = {},
): WorkspaceApplication {
  return createWorkspaceApplication({
    ...overrides,
    id: overrides.id ?? "application-v3",
    job: {
      ...overrides.job,
      aiMatch: overrides.job?.aiMatch ?? {
        version: "ai-match-v3",
        revision: "match-revision-v3",
        fingerprint: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        reasons: ["Strong product discovery background"],
        gaps: ["Confirm formal people-management experience"],
        updatedAt: "2026-07-15T10:00:00.000Z",
        applicationGuide: {
          language: "English",
          positioning:
            "Position Alex as a research-led designer who aligns cross-functional teams.",
          readiness: "needs_confirmation",
          roleMission:
            "Turn complex B2B workflows into clear, validated product experiences.",
          hiringPriorities: [
            "Discovery leadership",
            "Cross-functional collaboration",
          ],
          mustHave: ["B2B product design"],
          niceToHave: ["People leadership"],
          hardConstraints: [],
          evidenceMatrix: [
            {
              requirement: "B2B product design",
              importance: "required",
              status: "verified",
              evidence: "Six years designing B2B software products.",
              action: "Lead with recent product outcomes.",
              sourceIds: ["profile:experience:designer:achievement-product-delivery"],
              sources: [
                {
                  id: "profile:experience:designer:achievement-product-delivery",
                  label: "Experience · achievement",
                  excerpt: "Six years designing B2B software products.",
                },
              ],
            },
          ],
          clarificationQuestions: [],
          resumePlan: {
            targetHeadline: "Senior B2B Product Designer",
            summaryFocus: "Research-led product delivery",
            evidenceToLead: ["B2B workflow design"],
            bulletStrategy: ["Quantify product outcomes"],
          },
          coverLetterPlan: {
            openingAngle: "Connect discovery experience to Acme's platform.",
            proofPoints: ["Cross-functional product delivery"],
            motivationAngle: "Complex B2B products",
          },
          cvImprovements: ["Make product outcomes measurable"],
          coverLetterStrategy: ["Use one concrete discovery example"],
          risks: ["Do not imply unverified people-management experience"],
          keywords: ["Product discovery", "B2B", "User research"],
          applicationQuestions: ["Describe a complex workflow you simplified."],
          finalChecklist: ["Verify every claim against the source CV."],
        },
      },
    },
  });
}

export function createWorkspaceApplicationWithoutGuide(
  overrides: ApplicationOverrides = {},
): WorkspaceApplication {
  return createWorkspaceApplication({
    ...overrides,
    id: overrides.id ?? "application-without-guide",
    job: {
      ...overrides.job,
      aiMatch: overrides.job?.aiMatch ?? {
        version: "ai-match-v3",
        reasons: ["Relevant product design experience"],
        gaps: ["Application guide has not been generated"],
        updatedAt: "2026-07-16T10:00:00.000Z",
      },
    },
  });
}

function createWorkspaceApplication(
  overrides: ApplicationOverrides,
): WorkspaceApplication {
  return {
    id: "application",
    status: "draft",
    nextStep: "Prepare application pack",
    notes: "",
    documents: [],
    ...overrides,
    job: {
      ...baseJob,
      ...overrides.job,
    },
  };
}

export function installApplicationWorkspaceApiMock({
  confirmationPutResponse = [],
  confirmations = [],
  currentMasterResume = {
    masterResumeId: "master-resume-1",
    version: 1,
    masterResume: {},
    createdAt: "2026-07-25T10:00:00.000Z",
    updatedAt: "2026-07-25T10:00:00.000Z",
  },
  documents = [],
  resumeTemplates = [
    {
      id: "classic_single",
      kind: "bundled",
      name: "Classic Single",
      description: "Traditional single-column resume.",
      layout: "single_column",
      columns: 1,
      baseTemplateId: "classic_single",
      designJson: {
        accentColor: "#2B2B2B",
        fontFamily: "Georgia",
        fontScale: 1,
        density: "standard",
        pageMargins: { top: 15, right: 15, bottom: 15, left: 15 },
        headingStyle: "underlined",
        skillsStyle: "inline",
        sidebarWidth: 0,
        sidebarSections: [],
      },
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
        accentColor: "#176B87",
        fontFamily: "Inter",
        fontScale: 1,
        density: "standard",
        pageMargins: { top: 14, right: 14, bottom: 14, left: 14 },
        headingStyle: "accent-rule",
        skillsStyle: "pills",
        sidebarWidth: 0,
        sidebarSections: [],
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
        accentColor: "#243B53",
        fontFamily: "Inter",
        fontScale: 1,
        density: "compact",
        pageMargins: { top: 12, right: 12, bottom: 12, left: 12 },
        headingStyle: "accent-rule",
        skillsStyle: "pills",
        sidebarWidth: 32,
        sidebarSections: ["skills", "education"],
      },
    },
  ],
  templates = [],
  workspaceSources = [],
  aiPrivacySettings = {},
  requestHandler,
}: WorkspaceApiOptions = {}) {
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";
    const customResponse = await requestHandler?.(url, method, init);
    if (customResponse) return customResponse;

    if (url.pathname === "/health" && method === "GET") {
      return Response.json({ status: "ok" });
    }
    if (url.pathname === "/documents" && method === "GET") {
      return Response.json(documents);
    }
    if (url.pathname === "/documents/templates/library" && method === "GET") {
      return Response.json(templates);
    }
    if (url.pathname === "/resume-templates" && method === "GET") {
      return Response.json(resumeTemplates);
    }
    if (url.pathname === "/documents/workspace-sources/library" && method === "GET") {
      return Response.json(workspaceSources);
    }
    if (url.pathname === "/documents/templates/preflight" && method === "POST") {
      const request = JSON.parse(String(init?.body)) as {
        type: "cover_letter" | "tailored_resume";
        name: string;
        fileName: string;
      };
      const template = templates.find((item) => {
        if (!item || typeof item !== "object") return false;
        const candidate = item as { type?: string; name?: string; fileName?: string };
        return candidate.type === request.type
          && candidate.name === request.name
          && candidate.fileName === request.fileName;
      }) ?? {
        id: `${request.type}-preflight-template`,
        type: request.type,
        name: request.name,
        fileName: request.fileName,
        createdAt: "2026-07-18T10:00:00.000Z",
        updatedAt: "2026-07-18T10:00:00.000Z",
      };
      return Response.json({
        supported: true,
        template,
        editableCount: 3,
        immutableCount: 2,
        immutableElements: [
          { id: "block-0001", type: "heading", text: "Profile", reason: "AI changes targeting this protected element will be rejected" },
        ],
        rejectedElements: [],
        aiContext: {
          maxCharacters: 32000,
          contextBudgetCharacters: 28000,
          estimatedCharacters: 12000,
          includedCharacters: 12000,
          truncated: false,
          source: {
            totalElements: 5,
            includedElements: 5,
            omittedElements: 0,
            estimatedCharacters: 5000,
            includedCharacters: 5000,
            truncated: false,
          },
        },
        warnings: [],
      });
    }
    if (url.pathname === "/assistant/config" && method === "GET") {
      return Response.json({
        providerName: "OpenAI via OpenClaw/Codex",
        backend: "openclaw_codex",
        consentVersion: "2026-07-18.v2",
      });
    }
    if (url.pathname === "/privacy/ai-consent" && method === "GET") {
      return Response.json({
        providerName: "OpenAI via OpenClaw/Codex",
        currentBackend: "openclaw_codex",
        currentConsentVersion: "2026-07-18.v2",
        consentVersion: null,
        consentBackend: null,
        consentedAt: null,
        hasCurrentConsent: false,
        retentionDays: 30,
        lastAiActivityAt: null,
        aiDataExpiresAt: null,
        ...aiPrivacySettings,
      });
    }
    if (url.pathname === "/privacy/ai-consent" && method === "PUT") {
      const request = JSON.parse(String(init?.body)) as { backend: "openclaw_codex" | "openai_api"; version: string; retentionDays: number };
      return Response.json({
        providerName: "OpenAI via OpenClaw/Codex",
        currentBackend: "openclaw_codex",
        currentConsentVersion: "2026-07-18.v2",
        consentVersion: request.version,
        consentBackend: request.backend,
        consentedAt: "2026-07-19T10:00:00.000Z",
        hasCurrentConsent: true,
        retentionDays: request.retentionDays,
        lastAiActivityAt: null,
        aiDataExpiresAt: null,
      });
    }
    if (url.pathname === "/privacy/ai-consent" && method === "DELETE") {
      return new Response(null, { status: 204 });
    }
    if (url.pathname === "/profile/master-resume" && method === "GET") {
      return currentMasterResume
        ? Response.json(currentMasterResume)
        : Response.json(
            { detail: "Confirmed Master Resume not found" },
            { status: 404 },
          );
    }
    if (
      /^\/applications\/[^/]+\/confirmations$/.test(url.pathname) &&
      method === "GET"
    ) {
      return Response.json(confirmations);
    }
    if (
      /^\/applications\/[^/]+\/confirmations$/.test(url.pathname) &&
      method === "PUT"
    ) {
      return Response.json(confirmationPutResponse);
    }

    throw new Error(
      `Unhandled ApplicationWorkspace request: ${method} ${url.pathname}`,
    );
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function renderApplicationWorkspace(
  application: ApplicationWorkspaceProps["application"],
  overrides: Partial<Omit<ApplicationWorkspaceProps, "application">> = {},
) {
  const props: ApplicationWorkspaceProps = {
    application,
    profile: createWorkspaceProfile(),
    onBack: vi.fn(),
    onOpenAssistant: vi.fn(),
    onDocumentAttached: vi.fn(),
    onMarkApplied: vi.fn(),
    onRefreshAnalysis: vi.fn(),
    isAnalysisRefreshing: false,
    ...overrides,
  };

  return {
    ...render(<ApplicationWorkspace {...props} />),
    props,
  };
}
