import type { AiMatchMetadata } from "@/shared/types/job";

export const aiMatchFixture: AiMatchMetadata = {
  version: "ai-match-v5",
  revision: "match-revision",
  fingerprint: "a".repeat(64),
  cacheKey: "cache",
  profileHash: "profile",
  vacancyHash: "vacancy",
  model: "test-model",
  promptVersion: "ai-match-prompt-v8",
  source: "openai_api",
  backend: "openai_api",
  score: 82,
  updatedAt: "2026-09-12T10:00:00.000Z",
};
