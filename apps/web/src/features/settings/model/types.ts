import type { AiBackend } from "@/lib/ai-source";

export type AIBackendName = AiBackend;
export type OpenAIReasoningEffort = "none" | "low" | "medium" | "high" | "xhigh" | "max";
export type AIWorkloadReasoningEffort = "off" | OpenAIReasoningEffort;

export type AppSettings = {
  has_brightdata_api_key: boolean;
  brightdata_api_key_preview: string;
  ai_backend: AIBackendName;
  openai_api_key_configured: boolean;
  openai_api_key_preview: string;
  openai_api_model: string;
  openai_api_reasoning_effort: OpenAIReasoningEffort;
  openai_api_timeout_seconds: number;
  openai_api_max_attempts: number;
  openai_api_retry_backoff_seconds: number;
  ai_match_model: string;
  ai_match_reasoning: AIWorkloadReasoningEffort;
  ai_match_batch_size: number;
  ai_match_timeout_seconds: number;
  ai_match_max_attempts: number;
  auto_ai_match_enabled: boolean;
  job_screening_model: string;
  job_screening_reasoning: AIWorkloadReasoningEffort;
  job_screening_batch_size: number;
  job_screening_timeout_seconds: number;
  job_screening_max_attempts: number;
  job_screening_max_description_chars: number;
};

export type AppSettingsUpdate = Partial<{
  brightdata_api_key: string;
  ai_backend: AIBackendName;
  openai_api_key: string;
  openai_api_model: string;
  openai_api_reasoning_effort: OpenAIReasoningEffort;
  openai_api_timeout_seconds: number;
  openai_api_max_attempts: number;
  openai_api_retry_backoff_seconds: number;
  ai_match_model: string;
  ai_match_reasoning: AIWorkloadReasoningEffort;
  ai_match_batch_size: number;
  ai_match_timeout_seconds: number;
  ai_match_max_attempts: number;
  auto_ai_match_enabled: boolean;
  job_screening_model: string;
  job_screening_reasoning: AIWorkloadReasoningEffort;
  job_screening_batch_size: number;
  job_screening_timeout_seconds: number;
  job_screening_max_attempts: number;
  job_screening_max_description_chars: number;
}>;

export type UiSettings = {
  showLogs: boolean;
};
