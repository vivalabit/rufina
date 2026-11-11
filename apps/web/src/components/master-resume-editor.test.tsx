import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import {
  MASTER_RESUME_REVIEW_SECTIONS,
  ProfileResumeImport,
  type MasterResume,
} from "@/components/master-resume-editor";

const masterResume: MasterResume = {
  schemaVersion: "1.0",
  id: "master-resume-1",
  language: "English",
  basics: {
    fullName: "Ada Lovelace",
    headline: "Platform Engineer",
    email: "ada@example.com",
    phone: "",
    location: "Zurich",
    linkedin: "",
    github: "",
    portfolio: "",
  },
  summary: {
    text: "Platform engineer building reliable services.",
    evidenceIds: ["source:summary"],
  },
  experiences: [
    {
      id: "experience:acme",
      company: "Acme AG",
      title: "Platform Engineer",
      employmentType: "Full-time",
      location: "Zurich",
      startDate: "2022-01",
      endDate: "",
      isCurrent: true,
      stack: [{ id: "technology:python", technology: "Python", context: "Billing API", evidence_ids: ["source:experience"] }],
      responsibilities: [{ id: "responsibility:api", responsibility: "API ownership", decisions: "Selected queues" }],
      projects: [{ id: "work-project:ledger", name: "Ledger", description: "Reconciliation", project_type: "Internal",
        team: "4 engineers", systems: "Billing API", users: "Finance", load: "100k invoices/day" }],
      bullets: [
        {
          id: "bullet:acme:api",
          text: "Built reliable Python services.",
          evidenceIds: ["source:experience"],
        },
      ],
    },
  ],
  skills: [
    {
      id: "skill:python",
      name: "Python",
      category: "Programming",
      evidenceIds: ["source:experience"],
    },
  ],
  education: [],
  projects: [],
  certifications: [],
  languages: [],
  additionalSections: [],
  evidence: [
    {
      id: "source:summary",
      type: "source",
      text: "Platform engineer building reliable services.",
    },
    {
      id: "source:experience",
      type: "source",
      text: "Built reliable Python services using Python at Acme AG.",
    },
  ],
  sectionOrder: ["summary", "experience", "skills"],
};

const importResponse = {
  profileRevision: 1,
  sourceFileId: "source-file-1",
  masterResume,
  source: {
    sourceFormat: "docx",
    layout: "one_column",
    pageCount: 2,
    usedOcr: false,
    fragments: [
      { id: "source:summary", text: "Summary" },
      { id: "source:experience", text: "Experience" },
    ],
  },
  reviewSections: [
    { name: "contacts", itemCount: 5 },
    { name: "summary", itemCount: 1 },
    { name: "skills", itemCount: 1 },
    { name: "experience", itemCount: 1 },
    { name: "education", itemCount: 0 },
    { name: "projects", itemCount: 0 },
    { name: "certifications", itemCount: 0 },
  ],
  model: "gpt-6.1-sol",
  backend: "openai_api",
};

const originalFile = new File(["resume-bytes"], "ada-resume.docx", {
  type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
});
const source = { id: "source-file-1", fileName: originalFile.name, sizeBytes: originalFile.size,
  createdAt: "2026-09-16T12:00:00Z", downloadUrl: "/profile/sources/source-file-1", status: "pending", canReview: true, profileVersion: null };

function selectFile() {
  fireEvent.change(screen.getByLabelText("Choose resume to import"), { target: { files: [originalFile] } });
}

it("optionally imports a source, reviews details and saves to the profile without attaching a primary resume", async () => {
  const requests: Array<{ path: string; body: BodyInit | null | undefined }> = [];
  const saved = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname;
    requests.push({ path, body: init?.body });
    if (path === "/profile/imports" && init?.method === "POST") return Response.json(source);
    if (path.endsWith("/preview")) return Response.json(importResponse);
    if (path === "/profile/import-master-resume/confirm") return Response.json({
      masterResumeId: "default", version: 2, sourceFileId: source.id,
      masterResume: JSON.parse(String(init?.body)).masterResume, createdAt: source.createdAt,
    });
    if (path === "/profile/imports") return Response.json([{ ...source, status: "imported", canReview: false, profileVersion: 2 }]);
    throw new Error(`Unexpected request: ${path}`);
  }));
  const view = render(<ProfileResumeImport onProfileSaved={saved} />);
  expect(requests).toHaveLength(0);
  expect(screen.getByRole("button", { name: "Import from resume" })).toBeEnabled();
  expect(screen.queryByText("Profile resume")).not.toBeInTheDocument();
  selectFile();
  await screen.findByRole("dialog", { name: "Review resume import" });
  fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Augusta Ada Lovelace" } });
  for (const section of MASTER_RESUME_REVIEW_SECTIONS) {
    if (section === "experience") {
      expect(screen.getByLabelText("Load / scale")).toHaveValue("100k invoices/day");
      expect(screen.queryByLabelText("Where it was used")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Remove Python" })).toBeInTheDocument();
      fireEvent.change(screen.getByRole("textbox", { name: "Stack" }), { target: { value: "PostgreSQL" } });
      fireEvent.blur(screen.getByRole("textbox", { name: "Stack" }));
    }
    fireEvent.click(screen.getByRole("button", { name: "Mark reviewed" }));
  }
  fireEvent.click(screen.getByRole("button", { name: "Save to profile" }));
  await screen.findByText("Imported information saved to your profile.");
  expect(saved).toHaveBeenCalledOnce();
  expect(requests[0]).toEqual({ path: "/profile/imports", body: originalFile });
  expect(requests[1].path).toBe("/profile/imports/source-file-1/preview");
  expect(JSON.parse(String(requests[2].body))).toMatchObject({ sourceFileId: source.id, expectedProfileRevision: 1,
    confirmedSections: MASTER_RESUME_REVIEW_SECTIONS, masterResume: { basics: { fullName: "Augusta Ada Lovelace" },
      experiences: [expect.objectContaining({ stack: [
        expect.objectContaining({ id: "technology:python", technology: "Python", context: "Billing API", evidence_ids: ["source:experience"] }),
        expect.objectContaining({ id: expect.any(String), technology: "PostgreSQL", context: "" }),
      ] })] } });
  view.unmount();
  render(<ProfileResumeImport />);
  fireEvent.click(screen.getByRole("button", { name: "Import history" }));
  expect(await screen.findByRole("link", { name: originalFile.name })).toHaveAttribute("href", "http://localhost:8000/profile/sources/source-file-1");
  expect(screen.getByText(/Saved to profile · v2/)).toBeInTheDocument();
});

it("invalidates reviewed sections after an edit and retains the draft if saving fails", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname;
    if (path === "/profile/imports" && init?.method === "POST") return Response.json(source);
    if (path.endsWith("/preview")) return Response.json(importResponse);
    return Response.json({ detail: "Profile changed; reload it before saving" }, { status: 409 });
  }));
  render(<ProfileResumeImport />);
  selectFile();
  await screen.findByRole("dialog", { name: "Review resume import" });
  fireEvent.click(screen.getByRole("button", { name: "Mark reviewed" }));
  fireEvent.click(screen.getByRole("button", { name: /Contact details/ }));
  expect(screen.getByRole("button", { name: "Reviewed" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Headline"), { target: { value: "Senior Platform Engineer" } });
  expect(screen.getByRole("button", { name: "Mark reviewed" })).toBeInTheDocument();
  for (let index = 0; index < MASTER_RESUME_REVIEW_SECTIONS.length; index += 1) fireEvent.click(screen.getByRole("button", { name: "Mark reviewed" }));
  fireEvent.click(screen.getByRole("button", { name: "Save to profile" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Profile changed");
  fireEvent.click(screen.getByRole("button", { name: /Contact details/ }));
  expect(screen.getByLabelText("Headline")).toHaveValue("Senior Platform Engineer");
});

it("keeps a failed import source in history and can retry its review", async () => {
  let fail = true;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname;
    if (path === "/profile/imports") return Response.json(init?.method === "POST" ? source : [source]);
    if (fail) return Response.json({ detail: "Import unavailable; source saved" }, { status: 503 });
    return Response.json(importResponse);
  }));
  render(<ProfileResumeImport />);
  selectFile();
  expect(await screen.findByRole("alert")).toHaveTextContent("Import unavailable; source saved");
  fireEvent.click(screen.getByRole("button", { name: "Import history" }));
  await screen.findByRole("link", { name: originalFile.name });
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: "Review import" }));
  expect(await screen.findByRole("dialog", { name: "Review resume import" })).toBeInTheDocument();
});
