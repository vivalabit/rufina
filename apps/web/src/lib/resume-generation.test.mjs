import assert from "node:assert/strict";
import test from "node:test";

import {
  canReuseResumeRenderSource,
  resumeArtifactGenerationMode,
  resumeRenderSource,
  resumeRenderUrl,
} from "./resume-generation.ts";

test("resolves legacy ATS and Imaginator render sources", () => {
  const ats = { sourceAtsFinalReviewId: "ats-1" };
  const imaginator = { sourceImaginatorResumeId: "imaginator-1" };

  assert.deepEqual(resumeRenderSource(ats), {
    kind: "ats_final_review",
    id: "ats-1",
  });
  assert.deepEqual(resumeRenderSource(imaginator), {
    kind: "imaginator",
    id: "imaginator-1",
  });
  assert.equal(resumeArtifactGenerationMode(ats), "recruiter_xyz_ats");
  assert.equal(resumeArtifactGenerationMode(imaginator), "imaginator");
});

test("builds mode-specific PDF and DOCX render URLs", () => {
  assert.equal(
    resumeRenderUrl(
      "http://localhost:8000",
      { kind: "ats_final_review", id: "ats 1" },
      "pdf",
      "classic_single",
    ),
    "http://localhost:8000/resume-tailoring/ats-final-review/ats%201/pdf?templateId=classic_single",
  );
  assert.equal(
    resumeRenderUrl(
      "http://localhost:8000",
      { kind: "imaginator", id: "imag 1" },
      "docx",
      "my template",
    ),
    "http://localhost:8000/resume-tailoring/imaginator/imag%201/docx?templateId=my%20template",
  );
});

test("reuses only a current render source from the selected mode", () => {
  const artifact = {
    sourceImaginatorResumeId: "imaginator-1",
    provenance: { generationMode: "imaginator" },
  };

  assert.deepEqual(
    canReuseResumeRenderSource(artifact, {
      isOutdated: false,
      selectedMode: "imaginator",
    }),
    { kind: "imaginator", id: "imaginator-1" },
  );
  assert.equal(
    canReuseResumeRenderSource(artifact, {
      isOutdated: false,
      selectedMode: "recruiter_xyz_ats",
    }),
    null,
  );
  assert.equal(
    canReuseResumeRenderSource(artifact, {
      isOutdated: true,
      selectedMode: "imaginator",
    }),
    null,
  );
});
