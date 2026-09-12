import type { AiMatchMetadata } from "@/shared/types/job";

export const aiMatchFixture: AiMatchMetadata = {
  version: "ai-match-v6",
  revision: "match-revision",
  fingerprint: "a".repeat(64),
  cacheKey: "c".repeat(64),
  profileHash: "b".repeat(64),
  vacancyHash: "d".repeat(64),
  model: "test-model",
  promptVersion: "ai-match-prompt-v8",
  source: "openai_api",
  backend: "openai_api",
  score: 82,
  updatedAt: "2026-09-12T10:00:00.000Z",
};
