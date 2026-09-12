import assert from "node:assert/strict";
import test from "node:test";

import {
  getAiMatchAnalysisStatus,
} from "./ai-match.ts";

test("rejects match payloads without authoritative match metadata", () => {
  assert.equal(
    getAiMatchAnalysisStatus({ version: "ai-match-v4", score: 91 }),
    "outdated",
  );
  assert.equal(
    getAiMatchAnalysisStatus({ version: "ai-match-v3", score: 91 }),
    "outdated",
  );
});

test("accepts an authoritative ai-match-v4 score and explanation", () => {
  const match = {
    version: "ai-match-v4",
    revision: "match-revision",
    fingerprint: "a".repeat(64),
    score: 88,
    reasons: ["Relevant platform experience"],
    gaps: [],
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
