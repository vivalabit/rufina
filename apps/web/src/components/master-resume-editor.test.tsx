import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import {
  MASTER_RESUME_REVIEW_SECTIONS,
  MasterResumeEditor,
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
  model: "gpt-5.6-terra",
  backend: "openai_api",
};

it("imports, edits, reviews, and confirms a Master Resume once", async () => {
  const requests: Array<{
    path: string;
    body: Record<string, unknown>;
  }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input)).pathname;
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      requests.push({ path, body });

      if (path === "/profile/import-master-resume") {
        return Response.json(importResponse);
      }
      if (path === "/profile/import-master-resume/confirm") {
        return Response.json({
          masterResumeId: masterResume.id,
          version: 1,
          sourceFileId: "source-file-1",
          masterResume: body.masterResume,
          createdAt: "2026-07-25T12:00:00Z",
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    }),
  );

  render(
    <MasterResumeEditor
      apiBaseUrl="http://localhost:8000"
      profileResume={{
        fileName: "ada-resume.docx",
        fileSize: "42 KB",
        dataUrl:
          "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cmVzdW1l",
      }}
    />,
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Import profile resume" }),
  );

  expect(
    await screen.findByRole("dialog", { name: "Review Master Resume" }),
  ).toBeInTheDocument();
  expect(screen.getByText(/DOCX · 2 pages · 2 source fragments/)).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Full name"), {
    target: { value: "Augusta Ada Lovelace" },
  });

  for (const _section of MASTER_RESUME_REVIEW_SECTIONS) {
    fireEvent.click(screen.getByRole("button", { name: "Mark reviewed" }));
  }

  const confirmButton = screen.getByRole("button", {
    name: "Confirm Master Resume",
  });
  expect(confirmButton).toBeEnabled();
  fireEvent.click(confirmButton);

  expect(await screen.findByText("Confirmed · v1")).toBeInTheDocument();
  expect(
    screen.getByText(
      "Master Resume version 1 is confirmed and ready for tailoring.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Choose PDF or DOCX" }),
  ).not.toBeInTheDocument();

  expect(requests).toHaveLength(2);
  expect(requests[0]).toEqual({
    path: "/profile/import-master-resume",
    body: {
      resumeFileName: "ada-resume.docx",
      resumeDataUrl:
        "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cmVzdW1l",
    },
  });
  expect(requests[1].path).toBe(
    "/profile/import-master-resume/confirm",
  );
  expect(requests[1].body).toMatchObject({
    sourceFileId: "source-file-1",
    confirmedSections: MASTER_RESUME_REVIEW_SECTIONS,
    masterResume: {
      id: "master-resume-1",
      basics: { fullName: "Augusta Ada Lovelace" },
    },
  });
});

it("invalidates a reviewed section when its content changes", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json(importResponse)),
  );

  render(
    <MasterResumeEditor
      apiBaseUrl="http://localhost:8000"
      profileResume={{
        fileName: "ada-resume.docx",
        dataUrl: "data:application/octet-stream;base64,cmVzdW1l",
      }}
    />,
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Import profile resume" }),
  );
  await screen.findByRole("dialog", { name: "Review Master Resume" });

  fireEvent.click(screen.getByRole("button", { name: "Mark reviewed" }));
  fireEvent.click(
    screen.getByRole("button", { name: /Contact details/ }),
  );
  expect(screen.getByRole("button", { name: "Reviewed" })).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Headline"), {
    target: { value: "Senior Platform Engineer" },
  });

  expect(
    screen.getByRole("button", { name: "Mark reviewed" }),
  ).toBeInTheDocument();
  expect(screen.getByText("0/7 sections reviewed")).toBeInTheDocument();
});

it("shows an actionable import error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json(
        { detail: "Could not extract source fragments from the attached resume" },
        { status: 422 },
      ),
    ),
  );

  render(
    <MasterResumeEditor
      apiBaseUrl="http://localhost:8000"
      profileResume={{
        fileName: "broken.pdf",
        dataUrl: "data:application/pdf;base64,YnJva2Vu",
      }}
    />,
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Import profile resume" }),
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not extract source fragments from the attached resume",
  );
});
