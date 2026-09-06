import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import HomePage from "@/app/page";
import { installApplicationWorkspaceApiMock } from "@/test/application-workspace-harness";

type HomeRequestHandler = (
  url: URL,
  method: string,
  init?: RequestInit,
) => Response | Promise<Response | undefined> | undefined;

function parseBody<T>(init?: RequestInit): T {
  return JSON.parse(String(init?.body)) as T;
}

function installHomeApiMock(handler?: HomeRequestHandler) {
  return installApplicationWorkspaceApiMock({
    requestHandler: async (url, method, init) => {
      const customResponse = await handler?.(url, method, init);
      if (customResponse) return customResponse;

      if (url.pathname === "/job-search/configs" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/jobs" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/jobs/state" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/applications" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/applications/events" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/profile" && method === "GET")
        return Response.json({});
      if (url.pathname === "/profile/files" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/settings" && method === "GET") {
        return Response.json({
          has_brightdata_api_key: false,
          brightdata_api_key_preview: "",
          auto_ai_match_enabled: false,
        });
      }
      return undefined;
    },
  });
}

function profileFile(
  id: string,
  kind: "primary_resume" | "supporting_document" | "avatar",
  overrides: Record<string, unknown> = {},
) {
  const extension = kind === "avatar" ? "png" : "pdf";
  const contentType = kind === "avatar" ? "image/png" : "application/pdf";
  return {
    id,
    kind,
    title: kind === "primary_resume" ? "Resume" : kind === "avatar" ? "Avatar" : "Document",
    category: kind === "avatar" ? "Avatar" : "CV / Resume",
    language: "",
    issuer: "",
    notes: "",
    fileName: `${kind}.${extension}`,
    sizeBytes: 128,
    contentType,
    contentSha256: "a".repeat(64),
    createdAt: "2026-08-30T10:00:00Z",
    updatedAt: "2026-08-30T10:00:00Z",
    downloadUrl: `/profile/files/${id}`,
    ...overrides,
  };
}

function storedApplication(id = "application-file-test") {
  return {
    id,
    status: "applied",
    appliedAt: "2026-08-30T10:00:00Z",
    nextStep: "Follow up",
    notes: "",
    documents: [],
    job: {
      id: `job-${id}`,
      company: "Example AG",
      title: "Platform Engineer",
      location: "Zurich",
      type: "Full-time",
      salary: "Not specified",
      posted: "Today",
      experience: "Mid-level",
      department: "Engineering",
      match: 70,
      logo: "manual",
      overview: "Build reliable platform services.",
      responsibilities: ["Build platform services"],
      requirements: ["Platform engineering experience"],
      skills: ["Platform engineering"],
      salaryAverage: "N/A",
      salaryMin: "N/A",
      salaryMax: "N/A",
      recommendations: [],
      companyInfo: "Example AG",
      reviews: [],
      similarJobs: [],
      applyUrl: "https://example.test/jobs/platform",
      sourceUrl: "https://example.test/jobs/platform",
      addedAt: "2026-08-30T10:00:00Z",
    },
  };
}

async function fillManualApplication(file?: File) {
  const addButtons = await screen.findAllByRole("button", { name: "Add application" });
  fireEvent.click(addButtons[0]);
  fireEvent.change(screen.getByLabelText("Role title"), {
    target: { value: "Platform Engineer" },
  });
  fireEvent.change(screen.getByLabelText("Company"), {
    target: { value: "Example AG" },
  });
  fireEvent.change(screen.getByLabelText("Location"), {
    target: { value: "Zurich" },
  });
  fireEvent.change(screen.getByLabelText("Job posting URL"), {
    target: { value: "https://example.test/jobs/platform" },
  });
  fireEvent.change(screen.getByLabelText("Vacancy description"), {
    target: { value: "Build reliable platform services with Python and PostgreSQL." },
  });
  if (file) {
    fireEvent.change(screen.getByLabelText("Upload another"), {
      target: { files: [file] },
    });
  }
}

it("keeps avatar changes pending until Save and deletes the stored avatar for Use Default", async () => {
  window.history.replaceState(null, "", "#profile");
  const files = [profileFile("avatar-existing", "avatar")];
  const mutations: Array<{ method: string; path: string }> = [];

  installHomeApiMock(async (url, method, init) => {
    if (url.pathname === "/profile" && method === "GET")
      return Response.json({ name: "Avatar Candidate" });
    if (url.pathname === "/profile" && method === "PUT")
      return Response.json(parseBody<Record<string, unknown>>(init));
    if (url.pathname === "/profile/files" && method === "GET")
      return Response.json(files);
    if (url.pathname === "/profile/files" && method === "POST") {
      mutations.push({ method, path: url.pathname });
      return Response.json(profileFile("avatar-new", "avatar"), { status: 201 });
    }
    if (url.pathname === "/profile/files/avatar-existing" && method === "DELETE") {
      mutations.push({ method, path: url.pathname });
      files.splice(0, files.length);
      return new Response(null, { status: 204 });
    }
    return undefined;
  });

  render(<HomePage />);

  fireEvent.click((await screen.findAllByRole("button", { name: "Edit Profile" }))[0]);
  fireEvent.change(screen.getByLabelText("Change Avatar"), {
    target: {
      files: [new File(["new-avatar"], "new-avatar.png", { type: "image/png" })],
    },
  });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(mutations).toEqual([]);

  fireEvent.click(screen.getAllByRole("button", { name: "Edit Profile" })[0]);
  fireEvent.click(screen.getByRole("button", { name: "Use Default" }));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => {
    expect(mutations).toEqual([
      { method: "DELETE", path: "/profile/files/avatar-existing" },
    ]);
  });
});

it("keeps an application document visible when its DELETE request fails", async () => {
  window.history.replaceState(null, "", "#applications");
  const application = storedApplication("application-delete-document");
  const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => undefined);

  installHomeApiMock(async (url, method) => {
    if (url.pathname === "/applications" && method === "GET")
      return Response.json([
        { id: application.id, data: application, revision: 1 },
      ]);
    if (url.pathname === "/documents/workspace-sources/library" && method === "GET") {
      return Response.json([{
        id: "source-proof",
        applicationId: application.id,
        category: "Application Attachment",
        title: "Proof document",
        language: "",
        fileName: "proof.pdf",
        fileSize: "2 KB",
        sizeBytes: 2048,
        fileType: "application/pdf",
        uploadedAt: "2026-08-30T10:00:00Z",
        downloadUrl: `/documents/workspace-sources/source-proof/download?applicationId=${application.id}`,
      }]);
    }
    if (url.pathname === "/documents/workspace-sources/source-proof" && method === "DELETE") {
      return Response.json({ detail: "Delete unavailable" }, { status: 503 });
    }
    return undefined;
  });

  render(<HomePage />);

  expect(await screen.findByRole("link", { name: "Download proof.pdf" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Delete proof.pdf" }));

  await waitFor(() => expect(alertSpy).toHaveBeenCalledWith("Delete unavailable"));
  expect(screen.getByRole("link", { name: "Download proof.pdf" })).toBeInTheDocument();
});

it("keeps the manual application dialog and file draft after an upload failure", async () => {
  window.history.replaceState(null, "", "#applications");
  const requests: string[] = [];

  installHomeApiMock(async (url, method, init) => {
    if (url.pathname === "/applications" && method === "POST") {
      requests.push("create");
      const payload = parseBody<{ id: string; data: unknown }>(init);
      return Response.json({ ...payload, revision: 1 }, { status: 201 });
    }
    if (url.pathname === "/documents/workspace-sources/upload" && method === "POST") {
      requests.push("upload");
      return Response.json({ detail: "Upload unavailable" }, { status: 503 });
    }
    if (url.pathname === "/jobs/ai-match" && method === "POST") {
      requests.push("analyze");
      return Response.json([]);
    }
    return undefined;
  });

  render(<HomePage />);
  await fillManualApplication(
    new File(["%PDF-resume"], "retry-resume.pdf", { type: "application/pdf" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save application" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Upload unavailable");
  expect(screen.getByRole("heading", { name: "Add application" })).toBeInTheDocument();
  expect(screen.getByLabelText("Role title")).toHaveValue("Platform Engineer");
  expect(screen.getByText("retry resume")).toBeInTheDocument();
  expect(requests).toEqual(["create", "upload"]);
});

it("retains uploaded documents when authoritative application analysis omits them", async () => {
  window.history.replaceState(null, "", "#applications");
  let createdApplication: Record<string, unknown> | null = null;
  let applicationId = "";
  let analysisResponses = 0;

  installHomeApiMock(async (url, method, init) => {
    if (url.pathname === "/applications" && method === "POST") {
      const payload = parseBody<{ id: string; data: Record<string, unknown> }>(init);
      applicationId = payload.id;
      createdApplication = payload.data;
      return Response.json({ ...payload, revision: 1 }, { status: 201 });
    }
    if (url.pathname === "/documents/workspace-sources/upload" && method === "POST") {
      return Response.json({
        id: "source-manual-resume",
        applicationId,
        category: "Application Attachment",
        title: "analysis resume",
        language: "",
        fileName: "analysis-resume.pdf",
        fileSize: "1 KB",
        sizeBytes: 11,
        fileType: "application/pdf",
        uploadedAt: "2026-08-30T10:00:00Z",
        downloadUrl: `/documents/workspace-sources/source-manual-resume/download?applicationId=${applicationId}`,
      }, { status: 201 });
    }
    if (url.pathname === "/jobs/ai-match" && method === "POST") {
      const job = parseBody<{ jobs: Array<{ id: string; data: Record<string, unknown> }> }>(init).jobs[0];
      return Response.json([{ id: job.id, data: { ...job.data, match: 88 } }]);
    }
    if (/^\/applications\/[^/]+\/analysis$/.test(url.pathname) && method === "GET") {
      analysisResponses += 1;
      const application = createdApplication as Record<string, unknown>;
      return Response.json({
        id: applicationId,
        data: {
          ...application,
          job: {
            ...(application.job as Record<string, unknown>),
            match: 88,
          },
        },
      });
    }
    return undefined;
  });

  render(<HomePage />);
  await fillManualApplication(
    new File(["%PDF-resume"], "analysis-resume.pdf", { type: "application/pdf" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save application" }));

  await waitFor(() => expect(analysisResponses).toBe(1));
  expect(
    await screen.findByRole("link", { name: "Download analysis-resume.pdf" }),
  ).toBeInTheDocument();
});
