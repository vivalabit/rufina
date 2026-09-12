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
  currentMasterResume?: unknown | null;
  documents?: unknown[];
  resumeTemplates?: unknown[];
  templates?: unknown[];
  requestHandler?: (
    url: URL,
    method: string,
    init?: RequestInit,
  ) => Response | Promise<Response | undefined> | undefined;
};

const baseJob: WorkspaceJob = {
  id: "job-product-designer",
  title: "Senior Product Designer",
  company: "Acme Labs",
  location: "Zurich, Switzerland",
  type: "Full-time",
  overview: "Lead product discovery and delivery for a growing B2B platform.",
  responsibilities: ["Lead discovery", "Partner with product and engineering"],
  requirements: [
    "5+ years of product design experience",
    "Strong research practice",
  ],
  skills: ["Product design", "User research", "Figma"],
  applyUrl: "https://example.com/jobs/product-designer",
};

export function createWorkspaceApplication(
  overrides: ApplicationOverrides = {},
): WorkspaceApplication {
  return {
    id: "application",
    status: "draft",
    nextStep: "Review application",
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
  templates = [
    {
      id: "4a9260bb-dc6a-5b9d-8a3a-1caa1e1433e8",
      type: "cover_letter",
      name: "Standard cover letter",
      fileName: "standard-cover-letter.docx",
      builtIn: true,
      createdAt: "2026-07-28T10:00:00.000Z",
      updatedAt: "2026-07-28T10:00:00.000Z",
    },
  ],
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
      });
    }
    if (url.pathname === "/profile/master-resume" && method === "GET") {
      return currentMasterResume
        ? Response.json(currentMasterResume)
        : Response.json(
            { detail: "Confirmed Master Resume not found" },
            { status: 404 },
          );
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
    onBack: vi.fn(),
    onDocumentAttached: vi.fn(),
    ...overrides,
  };

  return {
    ...render(<ApplicationWorkspace {...props} />),
    props,
  };
}
