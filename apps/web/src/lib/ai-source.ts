export type AiSource =
  | "openclaw_codex"
  | "openclaw_claude"
  | "openai_api"
  | "anthropic_api"
  | "local";
export type AiBackend = Exclude<AiSource, "local">;
export type AiModelFamily = "openai" | "anthropic";

export const AI_BACKENDS: readonly AiBackend[] = [
  "openclaw_codex",
  "openclaw_claude",
  "openai_api",
  "anthropic_api",
];

export function isAiBackend(value: unknown): value is AiBackend {
  return AI_BACKENDS.includes(value as AiBackend);
}

export function isOpenClawBackend(backend: AiSource | null | undefined): boolean {
  return backend === "openclaw_codex" || backend === "openclaw_claude";
}

export function aiModelFamily(backend: AiSource | null | undefined): AiModelFamily {
  return backend === "anthropic_api" || backend === "openclaw_claude" ? "anthropic" : "openai";
}

export function getAiSourceLabel(source: AiSource | null | undefined): string {
  if (source === "openclaw_codex") return "Codex credits via OpenClaw";
  if (source === "openclaw_claude") return "Claude via OpenClaw";
  if (source === "openai_api") return "OpenAI Responses API";
  if (source === "anthropic_api") return "Anthropic Claude API";
  if (source === "local") return "Local fallback";
  return "Unknown AI route";
}
