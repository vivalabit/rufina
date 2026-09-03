import assert from "node:assert/strict";
import test from "node:test";

import {
  canReuseResumeRenderSource,
  resumeArtifactGenerationMode,
  resumeRenderSource,
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
