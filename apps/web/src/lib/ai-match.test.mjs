import assert from "node:assert/strict";
import test from "node:test";

import {
  getAiMatchAnalysisStatus,
} from "./ai-match.ts";

test("rejects match payloads without authoritative match metadata", () => {
  assert.equal(
    getAiMatchAnalysisStatus({ version: "ai-match-v6", score: 91 }),
    "outdated",
  );
  assert.equal(
    getAiMatchAnalysisStatus({ version: "ai-match-v3", score: 91 }),
    "outdated",
  );
});

test("accepts an authoritative ai-match-v6 score without analysis", () => {
  const match = {
    version: "ai-match-v6",
    revision: "match-revision",
    fingerprint: "a".repeat(64),
    profileHash: "b".repeat(64),
    vacancyHash: "c".repeat(64),
    score: 88,
  };

  assert.equal(getAiMatchAnalysisStatus(match), "current");
  assert.equal(
    getAiMatchAnalysisStatus({
      ...match,
      revision: undefined,
      fingerprint: undefined,
    }),
    "outdated",
  );
});


test("rejects legacy versions and invalid scores", () => {
  const match = {
    version: "ai-match-v6",
    revision: "match-revision",
    fingerprint: "a".repeat(64),
    profileHash: "b".repeat(64),
    vacancyHash: "c".repeat(64),
    score: 88,
  };
  assert.equal(getAiMatchAnalysisStatus({ ...match, version: "ai-match-v4" }), "outdated");
  for (const score of [-1, 101, 1.5, NaN, Infinity, "88", null]) {
    assert.equal(getAiMatchAnalysisStatus({ ...match, score }), "outdated");
  }
  for (const score of [0, 100]) {
    assert.equal(getAiMatchAnalysisStatus({ ...match, score }), "current");
  }
});

test("distinguishes a failed calculation from missing and zero scores", () => {
  const match = {
    version: "ai-match-v6",
    revision: "match-revision",
    fingerprint: "a".repeat(64),
    profileHash: "b".repeat(64),
    vacancyHash: "c".repeat(64),
    score: 0,
  };

  assert.equal(getAiMatchAnalysisStatus(undefined), "missing");
  assert.equal(getAiMatchAnalysisStatus(match), "current");
  assert.equal(
    getAiMatchAnalysisStatus({ ...match, providerError: "Provider timed out" }),
    "failed",
  );
});
