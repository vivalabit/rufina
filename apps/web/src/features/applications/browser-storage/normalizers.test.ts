import { describe, expect, it } from "vitest";

import type {
  ApplicationEvent,
  TrackedApplication,
} from "@/shared/types/application";
import type { Job } from "@/shared/types/job";

import {
  normalizeApplicationDocuments,
  normalizeStoredApplicationEvents,
  normalizeStoredApplications,
  removeLegacyDemoApplicationEvents,
  removeLegacyDemoApplications,
} from "./normalizers";
import { applicationPayloadForStorage } from "./serialization";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "linkedin-job-1",
    company: "Example",
    title: "Engineer",
    location: "Zurich",
    type: "Full-time",
    salary: "N/A",
    posted: "1h ago",
    experience: "Mid-level",
    department: "Engineering",
    match: 50,
    logo: "linkedin",
    overview: "",
    responsibilities: [],
    requirements: [],
    skills: [],
    salaryAverage: "N/A",
    salaryMin: "N/A",
    salaryMax: "N/A",
    recommendations: [],
    companyInfo: "",
    reviews: [],
    similarJobs: [],
    ...overrides,
  };
}

function application(
  overrides: Partial<TrackedApplication> = {},
): TrackedApplication {
  return {
    id: "application-1",
    job: job(),
    status: "applied",
    appliedAt: "2026-08-01T10:00:00.000Z",
    nextStep: "Interview",
    notes: "Notes",
    documents: [],
    ...overrides,
  };
}

function applicationEvent(
  overrides: Partial<ApplicationEvent> = {},
): ApplicationEvent {
  return {
    id: "event-1",
    applicationId: "application-1",
    type: "interview",
    status: "scheduled",
    title: "Interview",
    startsAt: "2026-09-01T10:00:00.000Z",
    durationMinutes: 30,
    timezone: "Europe/Zurich",
    location: "Remote",
    notes: "",
    ...overrides,
  };
}

describe("application browser-storage normalizers", () => {
  it("normalizes legacy document aliases using the original array index", () => {
    expect(
      normalizeApplicationDocuments([
        null,
        {
          data_url: "  data:application/pdf;base64,QQ==  ",
          title: " Legacy resume ",
        },
        { dataUrl: "/legacy/resume.docx", file_name: "resume.docx" },
      ]),
    ).toEqual([
      expect.objectContaining({
        id: "legacy-application-document-2",
        fileName: "legacy-document-2.pdf",
        legacyDataUrl: "data:application/pdf;base64,QQ==",
        title: "Legacy resume",
      }),
      expect.objectContaining({
        id: "legacy-application-document-3",
        fileName: "resume.docx",
        downloadUrl: "/legacy/resume.docx",
      }),
    ]);
  });

  it("rejects invalid applications and normalizes nested jobs and documents", () => {
    const normalized = normalizeStoredApplications([
      { ...application(), status: "unknown" },
      application({
        documents: [
          {
            id: "document-1",
            kind: "uploaded",
            title: "Resume",
            fileName: "resume.pdf",
            fileSize: "1 KB",
            fileType: "application/pdf",
            uploadedAt: "2026-08-01T10:00:00.000Z",
            downloadUrl: "/resume.pdf",
          },
        ],
      }),
    ]);

    expect(normalized).toHaveLength(1);
    expect(normalized[0].job.logo).toBe("linkedin");
    expect(normalized[0].documents[0]?.fileName).toBe("resume.pdf");
  });

  it("defaults invalid event state while retaining a valid outcome", () => {
    const [normalized] = normalizeStoredApplicationEvents([
      applicationEvent({
        status: "broken" as ApplicationEvent["status"],
        outcome: "negative",
      }),
      { id: "incomplete" },
    ]);

    expect(normalized.status).toBe("scheduled");
    expect(normalized.outcome).toBe("negative");
  });

  it("removes exact legacy demo applications and events", () => {
    const demoId = "application-stripe-senior-product-designer";

    expect(
      removeLegacyDemoApplications([
        application({ id: demoId }),
        application(),
      ]).map((item) => item.id),
    ).toEqual(["application-1"]);
    expect(
      removeLegacyDemoApplicationEvents([
        applicationEvent({ applicationId: demoId }),
        applicationEvent(),
      ]).map((item) => item.applicationId),
    ).toEqual(["application-1"]);
  });

  it("serializes without documents and does not mutate the application", () => {
    const source = application({
      documents: [
        {
          id: "document-1",
          kind: "uploaded",
          title: "Resume",
          fileName: "resume.pdf",
          fileSize: "1 KB",
          fileType: "application/pdf",
          uploadedAt: "2026-08-01T10:00:00.000Z",
          downloadUrl: "/resume.pdf",
          legacyDataUrl: "data:application/pdf;base64,QQ==",
        },
      ],
    });

    expect(applicationPayloadForStorage(source)).not.toHaveProperty("documents");
    expect(source.documents).toHaveLength(1);
  });
});
