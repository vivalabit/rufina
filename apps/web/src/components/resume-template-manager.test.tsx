import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { ResumeTemplateManager } from "@/components/resume-template-manager";
import type { ResumeTemplate } from "@/lib/resume-templates";

const bundledTemplate: ResumeTemplate = {
  id: "modern_two_column",
  kind: "bundled",
  name: "Modern two-column",
  description: "A modern resume with a sidebar.",
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
};

const customTemplate: ResumeTemplate = {
  ...bundledTemplate,
  id: "custom-1",
  kind: "custom",
  name: "Zurich applications",
  description: "Custom design based on Modern two-column.",
  version: 3,
  updatedAt: "2026-07-26T12:00:00Z",
};

function installBlobUrlMocks() {
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:resume-preview"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
}

it("edits, saves, duplicates, and deletes an owner template", async () => {
  installBlobUrlMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const requests: Array<{
    method: string;
    path: string;
    body: Record<string, unknown> | null;
  }> = [];
  let templates = [bundledTemplate, customTemplate];

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      const method = init?.method ?? "GET";
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : null;
      requests.push({ method, path: url.pathname, body });

      if (url.pathname === "/resume-templates" && method === "GET") {
        return Response.json(templates);
      }
      if (
        url.pathname === "/resume-templates/custom-1" &&
        method === "PATCH"
      ) {
        const saved = {
          ...customTemplate,
          ...body,
          version: 4,
          updatedAt: "2026-07-26T13:00:00Z",
        } as ResumeTemplate;
        templates = [bundledTemplate, saved];
        return Response.json(saved);
      }
      if (
        url.pathname === "/resume-templates/custom-1/duplicate" &&
        method === "POST"
      ) {
        const duplicate: ResumeTemplate = {
          ...customTemplate,
          id: "custom-2",
          name: "Zurich applications copy",
          version: 1,
          updatedAt: "2026-07-26T14:00:00Z",
        };
        templates = [bundledTemplate, templates[1], duplicate];
        return Response.json(duplicate, { status: 201 });
      }
      if (
        url.pathname === "/resume-templates/custom-2" &&
        method === "DELETE"
      ) {
        return new Response(null, { status: 204 });
      }
      if (
        url.pathname === "/resume-templates/preview" &&
        method === "POST"
      ) {
        return new Response(new Blob(["pdf"], { type: "application/pdf" }), {
          headers: { "Content-Type": "application/pdf" },
        });
      }
      throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    }),
  );

  render(<ResumeTemplateManager apiBaseUrl="http://localhost:8000" />);

  expect(await screen.findByDisplayValue("Zurich applications")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Template name"), {
    target: { value: "Swiss product roles" },
  });
  fireEvent.change(screen.getByLabelText("Font family"), {
    target: { value: "Georgia" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Comfortable" }));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(
    await screen.findByText("Template saved as version 4."),
  ).toBeInTheDocument();
  const patchRequest = requests.find(
    (request) =>
      request.method === "PATCH" &&
      request.path === "/resume-templates/custom-1",
  );
  expect(patchRequest?.body).toMatchObject({
    name: "Swiss product roles",
    baseTemplateId: "modern_two_column",
    designJson: {
      fontFamily: "Georgia",
      density: "comfortable",
    },
  });

  fireEvent.click(
    screen.getByRole("button", { name: "Duplicate template" }),
  );
  expect(await screen.findByDisplayValue("Zurich applications copy")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Delete template" }));
  await waitFor(() =>
    expect(
      requests.some(
        (request) =>
          request.method === "DELETE" &&
          request.path === "/resume-templates/custom-2",
      ),
    ).toBe(true),
  );
  expect(await screen.findByText("Template deleted.")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Swiss product roles")).toBeInTheDocument();
});

it("creates a personal template from a bundled foundation", async () => {
  installBlobUrlMocks();
  const requests: Array<{
    method: string;
    path: string;
    body: Record<string, unknown> | null;
  }> = [];

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      const method = init?.method ?? "GET";
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : null;
      requests.push({ method, path: url.pathname, body });

      if (url.pathname === "/resume-templates" && method === "GET") {
        return Response.json([bundledTemplate]);
      }
      if (url.pathname === "/resume-templates" && method === "POST") {
        return Response.json(
          {
            ...bundledTemplate,
            ...body,
            id: "custom-created",
            kind: "custom",
            version: 1,
          },
          { status: 201 },
        );
      }
      if (
        url.pathname === "/resume-templates/preview" &&
        method === "POST"
      ) {
        return new Response(new Blob(["pdf"], { type: "application/pdf" }));
      }
      throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    }),
  );

  render(<ResumeTemplateManager apiBaseUrl="http://localhost:8000" />);

  expect(
    await screen.findByDisplayValue("Modern two-column — personal"),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Accent color hex"), {
    target: { value: "#8A1538" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create template" }));

  expect(await screen.findByText("Personal template created.")).toBeInTheDocument();
  const createRequest = requests.find(
    (request) =>
      request.method === "POST" && request.path === "/resume-templates",
  );
  expect(createRequest?.body).toMatchObject({
    name: "Modern two-column — personal",
    baseTemplateId: "modern_two_column",
    designJson: { accentColor: "#8A1538" },
  });
});

it("downloads one portable JSON backup and imports it as a new template", async () => {
  installBlobUrlMocks();
  let downloadedName = "";
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
    function captureDownload(this: HTMLAnchorElement) {
      downloadedName = this.download;
    },
  );
  const backup = {
    format: "rufina.resume-template",
    schemaVersion: 1,
    name: "Zurich applications",
    baseTemplateId: "modern_two_column",
    designJson: customTemplate.designJson,
  };
  const requests: Array<{
    method: string;
    path: string;
    body: Record<string, unknown> | null;
  }> = [];

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      const method = init?.method ?? "GET";
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : null;
      requests.push({ method, path: url.pathname, body });

      if (url.pathname === "/resume-templates" && method === "GET") {
        return Response.json([bundledTemplate, customTemplate]);
      }
      if (
        url.pathname === "/resume-templates/custom-1/export" &&
        method === "GET"
      ) {
        return Response.json(backup, {
          headers: {
            "Content-Disposition":
              'attachment; filename="Zurich-applications.resume-template.local.json"',
          },
        });
      }
      if (
        url.pathname === "/resume-templates/import" &&
        method === "POST"
      ) {
        return Response.json(
          {
            ...customTemplate,
            id: "custom-imported",
            name: "Imported Swiss CV",
            version: 1,
          },
          { status: 201 },
        );
      }
      if (
        url.pathname === "/resume-templates/preview" &&
        method === "POST"
      ) {
        return new Response(new Blob(["pdf"], { type: "application/pdf" }));
      }
      throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    }),
  );

  render(<ResumeTemplateManager apiBaseUrl="http://localhost:8000" />);

  await screen.findByDisplayValue("Zurich applications");
  fireEvent.click(screen.getByRole("button", { name: "Export template" }));
  await waitFor(() =>
    expect(downloadedName).toBe(
      "Zurich-applications.resume-template.local.json",
    ),
  );
  expect(URL.createObjectURL).toHaveBeenCalled();
  expect(URL.revokeObjectURL).toHaveBeenCalled();

  const file = new File(
    [JSON.stringify(backup)],
    "backup.resume-template.local.json",
    { type: "application/json" },
  );
  Object.defineProperty(file, "text", {
    configurable: true,
    value: vi.fn(async () => JSON.stringify(backup)),
  });
  fireEvent.change(
    screen.getByLabelText("Import resume template backup"),
    { target: { files: [file] } },
  );

  expect(
    await screen.findByDisplayValue("Imported Swiss CV"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "Imported “Imported Swiss CV” as a new personal template.",
    ),
  ).toBeInTheDocument();
  const importRequest = requests.find(
    (request) =>
      request.method === "POST" &&
      request.path === "/resume-templates/import",
  );
  expect(importRequest?.body).toEqual(backup);
  expect(importRequest?.body).not.toHaveProperty("ownerId");
  expect(importRequest?.body).not.toHaveProperty("id");
});
