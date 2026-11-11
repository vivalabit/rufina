import { aiModelFamily, type AiBackend, type AiModelFamily } from "@/lib/ai-source";

import type { AIModelOption, AppSettings, UiSettings } from "./types";

// Mirrors app/core/ai_models.py. The settings response carries the options of
// the saved backend; this copy lets the form switch providers before saving.
export const AI_MODEL_CATALOG: Record<AiModelFamily, readonly AIModelOption[]> = {
  openai: [
    { value: "openai/gpt-6.1-sol", label: "GPT-6.1 Sol" },
    { value: "openai/gpt-6-luna", label: "GPT-6 Luna" },
    { value: "openai/gpt-5.5", label: "GPT-5.5" },
  ],
  anthropic: [
    { value: "anthropic/claude-sonnet-5-5", label: "Claude Sonnet 5.5" },
    { value: "anthropic/claude-haiku-5-5", label: "Claude Haiku 5.5" },
    { value: "anthropic/claude-opus-5-5", label: "Claude Opus 5.5" },
  ],
};

export type AIWorkload = "screening" | "match" | "documents";

export const AI_WORKLOAD_DEFAULT_MODELS: Record<AiModelFamily, Record<AIWorkload, string>> = {
  openai: {
    screening: "openai/gpt-6-luna",
    match: "openai/gpt-6.1-sol",
    documents: "openai/gpt-6.1-sol",
  },
  anthropic: {
    screening: "anthropic/claude-haiku-5-5",
    match: "anthropic/claude-sonnet-5-5",
    documents: "anthropic/claude-sonnet-5-5",
  },
};

export const aiModelOptionsFor = (backend: AiBackend) => AI_MODEL_CATALOG[aiModelFamily(backend)];

export const defaultWorkloadModel = (backend: AiBackend, workload: AIWorkload) =>
  AI_WORKLOAD_DEFAULT_MODELS[aiModelFamily(backend)][workload];

/** Settings may hold a bare provider model name; selectors use prefixed identifiers. */
export const workloadModelValue = (backend: AiBackend, model: string) => {
  const name = model.trim();
  if (!name || name.includes("/")) return name;
  return `${aiModelFamily(backend)}/${name}`;
};

export const defaultAppSettings: AppSettings = {
  has_brightdata_api_key: false,
  brightdata_api_key_preview: "",
  ai_backend: "openclaw_codex",
  ai_model_family: "openai",
  ai_model_options: [...AI_MODEL_CATALOG.openai],
  anthropic_api_key_configured: false,
  anthropic_api_key_preview: "",
  anthropic_api_model: "claude-sonnet-5-5",
  anthropic_api_effort: "medium",
  document_generation_model: "openai/gpt-6.1-sol",
  openai_api_key_configured: false,
  openai_api_key_preview: "",
  openai_api_model: "gpt-6.1-sol",
  openai_api_reasoning_effort: "medium",
  openai_api_timeout_seconds: 120,
  openai_api_max_attempts: 2,
  openai_api_retry_backoff_seconds: 0.8,
  ai_match_model: "openai/gpt-6.1-sol",
  ai_match_reasoning: "low",
  ai_match_batch_size: 1,
  ai_match_timeout_seconds: 120,
  ai_match_max_attempts: 2,
  auto_ai_match_enabled: false,
  job_screening_model: "openai/gpt-6-luna",
  job_screening_reasoning: "off",
  job_screening_batch_size: 10,
  job_screening_timeout_seconds: 60,
  job_screening_max_attempts: 2,
  job_screening_max_description_chars: 12_000,
};

export const AI_WORKLOAD_MODEL_OPTIONS = AI_MODEL_CATALOG.openai;

export const isAllowedAIWorkloadModel = (model: string, backend: AiBackend = "openclaw_codex") =>
  aiModelOptionsFor(backend).some((option) => option.value === model);

export const defaultUiSettings: UiSettings = {
  showLogs: false,
};
