import type { AppSettings, UiSettings } from "./types";

export const defaultAppSettings: AppSettings = {
  has_brightdata_api_key: false,
  brightdata_api_key_preview: "",
  ai_backend: "openclaw_codex",
  openai_api_key_configured: false,
  openai_api_key_preview: "",
  openai_api_model: "gpt-5.6-terra",
  openai_api_reasoning_effort: "medium",
  openai_api_timeout_seconds: 120,
  openai_api_max_attempts: 2,
  openai_api_retry_backoff_seconds: 0.8,
  ai_match_model: "openai/gpt-5.6-terra",
  ai_match_reasoning: "low",
  ai_match_batch_size: 1,
  ai_match_timeout_seconds: 120,
  ai_match_max_attempts: 2,
  auto_ai_match_enabled: false,
  job_screening_model: "openai/gpt-5.6-luna",
  job_screening_reasoning: "off",
  job_screening_batch_size: 10,
  job_screening_timeout_seconds: 60,
  job_screening_max_attempts: 2,
  job_screening_max_description_chars: 12_000,
};

export const AI_WORKLOAD_MODEL_OPTIONS = [
  { value: "openai/gpt-5.6-terra", label: "GPT-5.6 Terra" },
  { value: "openai/gpt-5.6-luna", label: "GPT-5.6 Luna" },
  { value: "openai/gpt-5.5", label: "GPT-5.5" },
] as const;

export const isAllowedAIWorkloadModel = (model: string) =>
  AI_WORKLOAD_MODEL_OPTIONS.some((option) => option.value === model);

export const defaultUiSettings: UiSettings = {
  showLogs: false,
};
