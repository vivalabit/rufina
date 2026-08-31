import { describe, expect, it } from "vitest";

import { defaultCandidateProfile } from "../model/defaults";
import { parseDocumentEntries } from "../model/entries";
import { hydrateProfileFiles, profilePayloadForApi } from "./mappers";
import type { ProfileFilePayload } from "./dto";

const createId = (prefix: string) => `${prefix}-generated`;

function profileFile(
  id: string,
  kind: ProfileFilePayload["kind"],
): ProfileFilePayload {
  return {
    id,
    kind,
    title: kind === "primary_resume" ? "Resume" : "Certificate",
    category: kind === "primary_resume" ? "CV / Resume" : "Certificate",
    language: "",
    issuer: "",
    notes: "",
    fileName: `${id}.pdf`,
    sizeBytes: 2048,
    contentType: "application/pdf",
    contentSha256: "a".repeat(64),
    createdAt: "2026-08-31T10:00:00Z",
    updatedAt: "2026-08-31T10:00:00Z",
    downloadUrl: `/profile/files/${id}`,
  };
}

describe("profile API mappers", () => {
  it("strips hydrated metadata and inline avatar data from API payloads", () => {
    const payload = profilePayloadForApi({
      ...defaultCandidateProfile,
      name: "Candidate",
      avatar_url: "data:image/png;base64,iVBORw0KGgo=",
      documents: "[]",
      resume_file_id: "resume-id",
    });

    expect(payload).toMatchObject({
      name: "Candidate",
      avatar_url: defaultCandidateProfile.avatar_url,
    });
    expect(payload).not.toHaveProperty("documents");
    expect(payload).not.toHaveProperty("resume_file_id");
  });

  it("hydrates resume and supporting-document metadata", () => {
    const profile = hydrateProfileFiles(
      defaultCandidateProfile,
      [profileFile("resume", "primary_resume"), profileFile("certificate", "supporting_document")],
      createId,
    );

    expect(profile.resume_file_id).toBe("resume");
    expect(profile.resume_file_size).toBe("2 KB");
    expect(parseDocumentEntries(profile.documents, createId)[0]).toMatchObject({
      id: "certificate",
      file_name: "certificate.pdf",
      file_size: "2 KB",
    });
  });
});
