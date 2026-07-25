import assert from "node:assert/strict";
import test from "node:test";

import { getGeneratedDocumentReadiness } from "./document-readiness.ts";

function generatedDocument(overrides = {}) {
  return {
    currentVersion: 1,
    versions: [
      {
        version: 1,
        factualValidation: { status: "passed" },
        visualValidation: { status: "passed" },
        hasRenderedDocx: true,
        ...overrides,
      },
    ],
  };
}

test("requires current fingerprint, validations, and a rendered artifact for readiness", () => {
  assert.equal(
    getGeneratedDocumentReadiness(generatedDocument(), false).ready,
    true,
  );
  assert.equal(
    getGeneratedDocumentReadiness(generatedDocument(), true).ready,
    false,
  );
  assert.equal(
    getGeneratedDocumentReadiness(
      generatedDocument({ factualValidation: { status: "failed" } }),
      false,
    ).ready,
    false,
  );
  assert.equal(
    getGeneratedDocumentReadiness(
      generatedDocument({ visualValidation: { status: "failed" } }),
      false,
    ).ready,
    false,
  );
  assert.equal(
    getGeneratedDocumentReadiness(
      generatedDocument({
        hasRenderedDocx: false,
        hasRenderedArtifact: false,
      }),
      false,
    ).ready,
    false,
  );
  assert.equal(
    getGeneratedDocumentReadiness(
      generatedDocument({
        hasRenderedDocx: false,
        hasRenderedArtifact: true,
      }),
      false,
    ).ready,
    true,
  );
});
