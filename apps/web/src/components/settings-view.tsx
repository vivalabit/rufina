"use client";

import { useEffect, useState } from "react";
import {
  BrainCircuit,
  Check,
  ExternalLink,
  FileText,
  Info,
  KeyRound,
  Save,
  ShieldCheck,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  AI_WORKLOAD_MODEL_OPTIONS,
  isAllowedAIWorkloadModel,
} from "@/features/settings/model/defaults";
import type {
  AIBackendName,
  AIWorkloadReasoningEffort,
  AppSettings,
  AppSettingsUpdate,
  OpenAIReasoningEffort,
} from "@/features/settings/model/types";
import { cn } from "@/lib/utils";

export function SettingsView({
  settings,
  showLogs,
  status,
  message,
  aiStatus,
  aiMessage,
  onConnectionDraftChange,
  onSaveConnection,
  onSaveAi,
  onShowLogsChange,
}: {
  settings: AppSettings;
  showLogs: boolean;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  aiStatus: "idle" | "loading" | "ready" | "error";
  aiMessage: string;
  onConnectionDraftChange: () => void;
  onSaveConnection: (apiKey: string) => Promise<void>;
  onSaveAi: (update: AppSettingsUpdate) => void;
  onShowLogsChange: (value: boolean) => void;
}) {
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const hasApiKeyDraft = apiKeyDraft.trim().length > 0;
  const [aiBackendDraft, setAiBackendDraft] = useState<AIBackendName>(settings.ai_backend);
  const [openAiApiKeyDraft, setOpenAiApiKeyDraft] = useState("");
  const [openAiModelDraft, setOpenAiModelDraft] = useState(settings.openai_api_model);
  const [openAiReasoningDraft, setOpenAiReasoningDraft] = useState<OpenAIReasoningEffort>(
    settings.openai_api_reasoning_effort,
  );
  const [openAiTimeoutDraft, setOpenAiTimeoutDraft] = useState(settings.openai_api_timeout_seconds);
  const [openAiAttemptsDraft, setOpenAiAttemptsDraft] = useState(settings.openai_api_max_attempts);
  const [openAiBackoffDraft, setOpenAiBackoffDraft] = useState(settings.openai_api_retry_backoff_seconds);
  const [aiMatchModelDraft, setAiMatchModelDraft] = useState(settings.ai_match_model);
  const [aiMatchReasoningDraft, setAiMatchReasoningDraft] = useState<AIWorkloadReasoningEffort>(
    settings.ai_match_reasoning,
  );
  const [aiMatchBatchSizeDraft, setAiMatchBatchSizeDraft] = useState(settings.ai_match_batch_size);
  const [aiMatchTimeoutDraft, setAiMatchTimeoutDraft] = useState(settings.ai_match_timeout_seconds);
  const [aiMatchAttemptsDraft, setAiMatchAttemptsDraft] = useState(settings.ai_match_max_attempts);
  const [autoAiMatchEnabledDraft, setAutoAiMatchEnabledDraft] = useState(
    settings.auto_ai_match_enabled,
  );
  const [screeningModelDraft, setScreeningModelDraft] = useState(settings.job_screening_model);
  const [screeningReasoningDraft, setScreeningReasoningDraft] = useState<AIWorkloadReasoningEffort>(
    settings.job_screening_reasoning,
  );
  const [screeningBatchSizeDraft, setScreeningBatchSizeDraft] = useState(settings.job_screening_batch_size);
  const [screeningTimeoutDraft, setScreeningTimeoutDraft] = useState(settings.job_screening_timeout_seconds);
  const [screeningAttemptsDraft, setScreeningAttemptsDraft] = useState(settings.job_screening_max_attempts);
  const [screeningDescriptionLimitDraft, setScreeningDescriptionLimitDraft] = useState(
    settings.job_screening_max_description_chars,
  );
  const hasUsableOpenAiKey = settings.openai_api_key_configured || Boolean(openAiApiKeyDraft.trim());
  const aiConnectionValidationMessage = aiBackendDraft === "openai_api"
    ? !hasUsableOpenAiKey
      ? "Add an OpenAI API key before enabling this mode."
      : !openAiModelDraft.trim()
        ? "Enter a default OpenAI model before enabling this mode."
        : !Number.isFinite(openAiTimeoutDraft) || openAiTimeoutDraft < 10 || openAiTimeoutDraft > 600
          ? "OpenAI timeout must be between 10 and 600 seconds."
          : !Number.isInteger(openAiAttemptsDraft) || openAiAttemptsDraft < 1 || openAiAttemptsDraft > 4
            ? "OpenAI max attempts must be between 1 and 4."
            : !Number.isFinite(openAiBackoffDraft) || openAiBackoffDraft < 0 || openAiBackoffDraft > 10
              ? "OpenAI retry backoff must be between 0 and 10 seconds."
              : ""
    : "";
  const aiMatchValidationMessage = !isAllowedAIWorkloadModel(aiMatchModelDraft)
    ? "Select an allowed model for Full AI Match."
    : !Number.isInteger(aiMatchBatchSizeDraft) || aiMatchBatchSizeDraft < 1 || aiMatchBatchSizeDraft > 100
      ? "Full AI Match batch size must be between 1 and 100."
      : !Number.isFinite(aiMatchTimeoutDraft) || aiMatchTimeoutDraft < 10 || aiMatchTimeoutDraft > 600
        ? "Full AI Match timeout must be between 10 and 600 seconds."
        : !Number.isInteger(aiMatchAttemptsDraft) || aiMatchAttemptsDraft < 1 || aiMatchAttemptsDraft > 4
          ? "Full AI Match max attempts must be between 1 and 4."
          : "";
  const screeningValidationMessage = !isAllowedAIWorkloadModel(screeningModelDraft)
    ? "Select an allowed model for vacancy pre-screening."
    : !Number.isInteger(screeningBatchSizeDraft) || screeningBatchSizeDraft < 1 || screeningBatchSizeDraft > 100
      ? "Pre-screening batch size must be between 1 and 100."
      : !Number.isFinite(screeningTimeoutDraft) || screeningTimeoutDraft < 10 || screeningTimeoutDraft > 600
        ? "Pre-screening timeout must be between 10 and 600 seconds."
        : !Number.isInteger(screeningAttemptsDraft) || screeningAttemptsDraft < 1 || screeningAttemptsDraft > 4
          ? "Pre-screening max attempts must be between 1 and 4."
          : !Number.isInteger(screeningDescriptionLimitDraft)
              || screeningDescriptionLimitDraft < 1_000
              || screeningDescriptionLimitDraft > 200_000
            ? "Pre-screening description limit must be between 1,000 and 200,000 characters."
            : "";
  const aiValidationMessage =
    aiConnectionValidationMessage || aiMatchValidationMessage || screeningValidationMessage;
  const currentKeyPreview = settings.brightdata_api_key_preview || "No key saved";
  const statusMessage =
    status === "error"
      ? message || "Settings save failed"
      : message ||
        (settings.has_brightdata_api_key
          ? "Key is configured and only used server-side"
          : "Add a Bright Data key to enable LinkedIn and Indeed vacancy search.");

  useEffect(() => {
    setAiBackendDraft(settings.ai_backend);
    setOpenAiApiKeyDraft("");
    setOpenAiModelDraft(settings.openai_api_model);
    setOpenAiReasoningDraft(settings.openai_api_reasoning_effort);
    setOpenAiTimeoutDraft(settings.openai_api_timeout_seconds);
    setOpenAiAttemptsDraft(settings.openai_api_max_attempts);
    setOpenAiBackoffDraft(settings.openai_api_retry_backoff_seconds);
    setAiMatchModelDraft(settings.ai_match_model);
    setAiMatchReasoningDraft(settings.ai_match_reasoning);
    setAiMatchBatchSizeDraft(settings.ai_match_batch_size);
    setAiMatchTimeoutDraft(settings.ai_match_timeout_seconds);
    setAiMatchAttemptsDraft(settings.ai_match_max_attempts);
    setAutoAiMatchEnabledDraft(settings.auto_ai_match_enabled);
    setScreeningModelDraft(settings.job_screening_model);
    setScreeningReasoningDraft(settings.job_screening_reasoning);
    setScreeningBatchSizeDraft(settings.job_screening_batch_size);
    setScreeningTimeoutDraft(settings.job_screening_timeout_seconds);
    setScreeningAttemptsDraft(settings.job_screening_max_attempts);
    setScreeningDescriptionLimitDraft(settings.job_screening_max_description_chars);
  }, [
    settings.ai_match_batch_size,
    settings.ai_match_max_attempts,
    settings.ai_match_model,
    settings.ai_match_reasoning,
    settings.ai_match_timeout_seconds,
    settings.auto_ai_match_enabled,
    settings.ai_backend,
    settings.job_screening_batch_size,
    settings.job_screening_max_attempts,
    settings.job_screening_max_description_chars,
    settings.job_screening_model,
    settings.job_screening_reasoning,
    settings.job_screening_timeout_seconds,
    settings.openai_api_key_configured,
    settings.openai_api_key_preview,
    settings.openai_api_max_attempts,
    settings.openai_api_model,
    settings.openai_api_reasoning_effort,
    settings.openai_api_retry_backoff_seconds,
    settings.openai_api_timeout_seconds,
  ]);

  function saveAiBackendSettings() {
    onSaveAi({
      ai_backend: aiBackendDraft,
      ...(openAiApiKeyDraft.trim() ? { openai_api_key: openAiApiKeyDraft.trim() } : {}),
      openai_api_model: openAiModelDraft.trim(),
      openai_api_reasoning_effort: openAiReasoningDraft,
      openai_api_timeout_seconds: openAiTimeoutDraft,
      openai_api_max_attempts: openAiAttemptsDraft,
      openai_api_retry_backoff_seconds: openAiBackoffDraft,
      ai_match_model: aiMatchModelDraft.trim(),
      ai_match_reasoning: aiBackendDraft === "openclaw_codex" ? "off" : aiMatchReasoningDraft,
      ai_match_batch_size: aiMatchBatchSizeDraft,
      ai_match_timeout_seconds: aiMatchTimeoutDraft,
      ai_match_max_attempts: aiMatchAttemptsDraft,
      auto_ai_match_enabled: autoAiMatchEnabledDraft,
      job_screening_model: screeningModelDraft.trim(),
      job_screening_reasoning: aiBackendDraft === "openclaw_codex" ? "off" : screeningReasoningDraft,
      job_screening_batch_size: screeningBatchSizeDraft,
      job_screening_timeout_seconds: screeningTimeoutDraft,
      job_screening_max_attempts: screeningAttemptsDraft,
      job_screening_max_description_chars: screeningDescriptionLimitDraft,
    });
  }

  async function saveBrightDataKey(apiKey: string) {
    try {
      await onSaveConnection(apiKey);
      setApiKeyDraft("");
    } catch {
      // Mutation state owns the error; keep the draft available for retry.
    }
  }

  function clearOpenAiApiKey() {
    setAiBackendDraft("openclaw_codex");
    setOpenAiApiKeyDraft("");
    onSaveAi({ ai_backend: "openclaw_codex", openai_api_key: "" });
  }

  return (
    <section className="job-scroll flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
      <header className="mb-4 flex shrink-0 flex-col gap-3 md:flex-row md:items-start md:justify-between 2xl:mb-5">
        <div>
          <h1 className="page-title text-[24px] leading-tight text-foreground sm:text-[27px] 2xl:text-[31px]">
            Settings
          </h1>
          <p className="mt-1 text-[13px] text-muted 2xl:mt-1.5 2xl:text-base">Application credentials and integrations</p>
        </div>
      </header>

      <div className="grid max-w-[1460px] gap-5">
        <section className="panel p-4 2xl:p-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-md bg-accent/18 text-accent 2xl:h-12 2xl:w-12">
                <FileText className="h-5 w-5 2xl:h-6 2xl:w-6" />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-bold text-foreground 2xl:text-lg">Logs</h2>
                <p className="mt-1 text-[13px] leading-5 text-muted 2xl:text-sm 2xl:leading-6">
                  Show the Logs button in the sidebar and keep local application events.
                </p>
              </div>
            </div>
            <button
              type="button"
              aria-label="Show logs"
              aria-pressed={showLogs}
              onClick={() => onShowLogsChange(!showLogs)}
              className={cn(
                "relative h-6 w-11 shrink-0 rounded-full transition",
                showLogs ? "bg-accent shadow-[0_0_14px_rgba(255,90,0,0.22)]" : "bg-[#fff8f1]",
              )}
            >
              <span className={cn("absolute top-1 h-4 w-4 rounded-full bg-white transition", showLogs ? "right-1" : "left-1")} />
            </button>
          </div>
        </section>

        <section className="panel p-5 2xl:p-7">
          <div className="flex flex-col gap-4 md:flex-row md:items-start">
            <div className="flex min-w-0 items-start gap-3">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-md bg-accent/18 text-accent 2xl:h-12 2xl:w-12">
                <BrainCircuit className="h-5 w-5 2xl:h-6 2xl:w-6" />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-bold text-foreground 2xl:text-lg">AI backend</h2>
                <p className="mt-1 text-[13px] leading-5 text-muted 2xl:text-sm 2xl:leading-6">
                  Choose how Rufina sends new AI operations. Running operations keep the mode they started with.
                </p>
              </div>
            </div>
          </div>

          <div className="mt-6 grid gap-5">
            <fieldset>
              <legend className="sr-only">AI mode</legend>
              <div className="grid gap-3 lg:grid-cols-2">
                {([
                  {
                    value: "openclaw_codex" as const,
                    title: "Codex credits via OpenClaw",
                    description: "Use the configured OpenClaw/Codex route and its available Codex credits.",
                  },
                  {
                    value: "openai_api" as const,
                    title: "OpenAI API",
                    description: "Call the OpenAI Responses API directly with your server-side API key.",
                  },
                ]).map((option) => {
                  const selected = aiBackendDraft === option.value;
                  return (
                    <label
                      key={option.value}
                      className={cn(
                        "cursor-pointer rounded-xl border p-4 transition",
                        selected
                          ? "border-accent/70 bg-accent/[0.09] shadow-[0_0_0_1px_rgba(255,90,0,0.16)]"
                          : "border-border bg-[#fff8f1] hover:border-[#c0bbb6] hover:bg-[#fff3e8]",
                      )}
                    >
                      <span className="flex items-start gap-3">
                        <input
                          type="radio"
                          name="ai-backend"
                          value={option.value}
                          checked={selected}
                          onChange={() => setAiBackendDraft(option.value)}
                          className="mt-1 h-4 w-4 accent-[#fa5d00]"
                        />
                        <span>
                          <span className="block text-sm font-bold text-foreground 2xl:text-base">{option.title}</span>
                          <span className="mt-1 block text-xs leading-5 text-muted">{option.description}</span>
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </fieldset>

            <div className="rounded-lg border border-accent/25 bg-accent/10 px-4 py-3 text-xs leading-5 text-accent">
              Switching applies to new operations. Running chat, document generation, imports, snapshots, and matching jobs keep the mode they started with.
            </div>

            {aiBackendDraft === "openai_api" ? (
              <div className="grid gap-5 rounded-xl border border-border bg-black/15 p-4 sm:p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-bold text-foreground">OpenAI API configuration</h3>
                    <p className="mt-1 text-xs text-muted">The full key remains server-side and is never returned to the browser.</p>
                  </div>
                  <span className={cn(
                    "rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.08em]",
                    hasUsableOpenAiKey
                      ? "border-success/30 bg-success/10 text-success"
                      : "border-accent/25 bg-accent/10 text-accent",
                  )}>
                    {openAiApiKeyDraft.trim() ? "New key ready" : settings.openai_api_key_configured ? "Key configured" : "Key required"}
                  </span>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c] 2xl:text-base">OpenAI API key</span>
                    <input
                      type="password"
                      aria-label="OpenAI API key"
                      value={openAiApiKeyDraft}
                      onChange={(event) => setOpenAiApiKeyDraft(event.target.value)}
                      placeholder={settings.openai_api_key_preview || "Enter an OpenAI API key"}
                      className="h-12 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70 2xl:h-[52px] 2xl:px-4 2xl:text-base"
                      autoComplete="off"
                    />
                    <span className="text-xs font-medium text-muted">
                      {settings.openai_api_key_configured
                        ? `Saved key: ${settings.openai_api_key_preview}. Leave blank to keep it.`
                        : "No API key is configured."}
                    </span>
                  </label>

                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c] 2xl:text-base">OpenAI model</span>
                    <input
                      aria-label="OpenAI model"
                      value={openAiModelDraft}
                      onChange={(event) => setOpenAiModelDraft(event.target.value)}
                      className="h-12 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70 2xl:h-[52px] 2xl:px-4 2xl:text-base"
                    />
                  </label>
                </div>

                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c]">Reasoning effort</span>
                    <select aria-label="OpenAI reasoning effort" value={openAiReasoningDraft} onChange={(event) => setOpenAiReasoningDraft(event.target.value as OpenAIReasoningEffort)} className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70">
                      {(["none", "low", "medium", "high", "xhigh", "max"] as OpenAIReasoningEffort[]).map((effort) => <option key={effort} value={effort}>{effort}</option>)}
                    </select>
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c]">Timeout, seconds</span>
                    <input type="number" aria-label="OpenAI timeout seconds" min={10} max={600} value={openAiTimeoutDraft} onChange={(event) => setOpenAiTimeoutDraft(Number(event.target.value))} className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70" />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c]">Max attempts</span>
                    <input type="number" aria-label="OpenAI max attempts" min={1} max={4} value={openAiAttemptsDraft} onChange={(event) => setOpenAiAttemptsDraft(Number(event.target.value))} className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70" />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c]">Retry backoff, seconds</span>
                    <input type="number" aria-label="OpenAI retry backoff seconds" min={0} max={10} step={0.1} value={openAiBackoffDraft} onChange={(event) => setOpenAiBackoffDraft(Number(event.target.value))} className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70" />
                  </label>
                </div>
              </div>
            ) : settings.openai_api_key_configured ? (
              <div className="flex flex-col gap-3 rounded-lg border border-border bg-[#fff8f1] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-semibold text-foreground">OpenAI API key saved but not in use</p>
                  <p className="mt-1 text-xs text-muted">{settings.openai_api_key_preview} remains stored for a future switch to OpenAI API.</p>
                </div>
                <Button type="button" variant="ghost" className="h-10 shrink-0 rounded-md border border-accent/25 px-4 text-xs text-accent hover:bg-accent/10" disabled={aiStatus === "loading"} onClick={clearOpenAiApiKey}>
                  Delete saved OpenAI API key
                </Button>
              </div>
            ) : null}

            <div className="grid gap-4 xl:grid-cols-2">
              <section className="grid content-start gap-5 rounded-xl border border-accent/25 bg-accent/10 p-4 sm:p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-bold text-foreground 2xl:text-base">Vacancy pre-screening</h3>
                      <span className="rounded-full border border-accent/25 bg-accent/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] text-accent">
                        Cheap model
                      </span>
                    </div>
                    <p className="mt-1.5 text-xs leading-5 text-muted">
                      Runs first and hides rejected vacancies from the client. Decisions follow only each search config.
                    </p>
                  </div>
                </div>

                <label className="grid gap-2">
                  <span className="text-sm font-bold text-[#1d1e1c]">Model</span>
                  <select
                    aria-label="Vacancy pre-screening model"
                    value={screeningModelDraft}
                    onChange={(event) => setScreeningModelDraft(event.target.value)}
                    className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/25"
                  >
                    {AI_WORKLOAD_MODEL_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>

                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c]">Reasoning</span>
                    <select
                      aria-label="Vacancy pre-screening reasoning"
                      value={aiBackendDraft === "openclaw_codex" ? "off" : screeningReasoningDraft}
                      onChange={(event) => setScreeningReasoningDraft(event.target.value as AIWorkloadReasoningEffort)}
                      disabled={aiBackendDraft === "openclaw_codex"}
                      className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/25"
                    >
                      {(["off", "low", "medium", "high", "xhigh", "max"] as AIWorkloadReasoningEffort[]).map((effort) => (
                        <option key={effort} value={effort}>{effort}</option>
                      ))}
                    </select>
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c]">Jobs per request</span>
                    <input
                      type="number"
                      aria-label="Vacancy pre-screening batch size"
                      min={1}
                      max={100}
                      value={screeningBatchSizeDraft}
                      onChange={(event) => setScreeningBatchSizeDraft(Number(event.target.value))}
                      className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/25"
                    />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c]">Timeout, seconds</span>
                    <input
                      type="number"
                      aria-label="Vacancy pre-screening timeout seconds"
                      min={10}
                      max={600}
                      value={screeningTimeoutDraft}
                      onChange={(event) => setScreeningTimeoutDraft(Number(event.target.value))}
                      className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/25"
                    />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c]">Max attempts</span>
                    <input
                      type="number"
                      aria-label="Vacancy pre-screening max attempts"
                      min={1}
                      max={4}
                      value={screeningAttemptsDraft}
                      onChange={(event) => setScreeningAttemptsDraft(Number(event.target.value))}
                      className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/25"
                    />
                  </label>
                </div>

                <label className="grid gap-2">
                  <span className="text-sm font-bold text-[#1d1e1c]">Description limit, characters</span>
                  <input
                    type="number"
                    aria-label="Vacancy pre-screening description limit"
                    min={1_000}
                    max={200_000}
                    step={1_000}
                    value={screeningDescriptionLimitDraft}
                    onChange={(event) => setScreeningDescriptionLimitDraft(Number(event.target.value))}
                    className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/25"
                  />
                </label>
              </section>

              <section className="grid content-start gap-5 rounded-xl border border-accent/25 bg-accent/[0.045] p-4 sm:p-5">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-bold text-foreground 2xl:text-base">Full AI Match</h3>
                    <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] text-accent">
                      Main model
                    </span>
                  </div>
                  <p className="mt-1.5 text-xs leading-5 text-muted">
                    Runs only for vacancies that passed pre-screening and builds the detailed match analysis.
                  </p>
                </div>

                <button
                  type="button"
                  role="switch"
                  aria-label="Auto AI Match"
                  aria-checked={autoAiMatchEnabledDraft}
                  onClick={() => setAutoAiMatchEnabledDraft((enabled) => !enabled)}
                  className="flex min-h-14 w-full items-center justify-between gap-4 rounded-lg border border-border bg-black/15 px-3.5 py-3 text-left transition hover:border-accent/40"
                >
                  <span>
                    <span className="block text-sm font-bold text-foreground">Auto AI Match</span>
                    <span className="mt-1 block text-xs leading-5 text-muted">
                      Automatically analyze every new vacancy immediately after it is added.
                    </span>
                  </span>
                  <span
                    aria-hidden="true"
                    className={cn(
                      "relative h-6 w-11 shrink-0 rounded-full transition",
                      autoAiMatchEnabledDraft
                        ? "bg-accent shadow-[0_0_14px_rgba(255,90,0,0.22)]"
                        : "bg-[#fff8f1]",
                    )}
                  >
                    <span
                      className={cn(
                        "absolute top-1 h-4 w-4 rounded-full bg-white transition",
                        autoAiMatchEnabledDraft ? "right-1" : "left-1",
                      )}
                    />
                  </span>
                </button>

                <label className="grid gap-2">
                  <span className="text-sm font-bold text-[#1d1e1c]">Model</span>
                  <select
                    aria-label="Full AI Match model"
                    value={aiMatchModelDraft}
                    onChange={(event) => setAiMatchModelDraft(event.target.value)}
                    className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                  >
                    {AI_WORKLOAD_MODEL_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>

                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c]">Reasoning</span>
                    <select
                      aria-label="Full AI Match reasoning"
                      value={aiBackendDraft === "openclaw_codex" ? "off" : aiMatchReasoningDraft}
                      onChange={(event) => setAiMatchReasoningDraft(event.target.value as AIWorkloadReasoningEffort)}
                      disabled={aiBackendDraft === "openclaw_codex"}
                      className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                    >
                      {(["off", "low", "medium", "high", "xhigh", "max"] as AIWorkloadReasoningEffort[]).map((effort) => (
                        <option key={effort} value={effort}>{effort}</option>
                      ))}
                    </select>
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c]">Jobs per request</span>
                    <input
                      type="number"
                      aria-label="Full AI Match batch size"
                      min={1}
                      max={100}
                      value={aiMatchBatchSizeDraft}
                      onChange={(event) => setAiMatchBatchSizeDraft(Number(event.target.value))}
                      className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                    />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c]">Timeout, seconds</span>
                    <input
                      type="number"
                      aria-label="Full AI Match timeout seconds"
                      min={10}
                      max={600}
                      value={aiMatchTimeoutDraft}
                      onChange={(event) => setAiMatchTimeoutDraft(Number(event.target.value))}
                      className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                    />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#1d1e1c]">Max attempts</span>
                    <input
                      type="number"
                      aria-label="Full AI Match max attempts"
                      min={1}
                      max={4}
                      value={aiMatchAttemptsDraft}
                      onChange={(event) => setAiMatchAttemptsDraft(Number(event.target.value))}
                      className="h-11 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                    />
                  </label>
                </div>
              </section>
            </div>

            {aiValidationMessage ? <p role="alert" className="text-sm font-semibold text-accent">{aiValidationMessage}</p> : null}

            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <p className={cn("flex items-center gap-3 text-sm font-semibold", aiStatus === "error" ? "text-[#fa5d00]" : aiStatus === "ready" ? "text-success" : "text-muted")}>
                {aiStatus === "error" ? <X className="h-5 w-5" /> : <ShieldCheck className="h-5 w-5" />}
                {aiMessage || (settings.ai_backend === "openai_api" ? "OpenAI API is active" : "Codex credits via OpenClaw is active")}
              </p>
              <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                {aiBackendDraft === "openai_api" && settings.openai_api_key_configured && (
                  <Button
                    type="button"
                    variant="ghost"
                    className="h-12 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
                    disabled={aiStatus === "loading"}
                    onClick={clearOpenAiApiKey}
                  >
                    Delete saved OpenAI API key
                  </Button>
                )}
                <Button
                  type="button"
                  className="h-12 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-7 text-[13px] text-foreground"
                  disabled={
                    aiStatus === "loading"
                    || Boolean(aiValidationMessage)
                  }
                  onClick={saveAiBackendSettings}
                >
                  <Save className="h-4 w-4" />
                  {aiStatus === "loading" ? "Saving..." : "Save AI settings"}
                </Button>
              </div>
            </div>
          </div>
        </section>

        <section className="panel p-5 2xl:p-7">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-md bg-[#0a66c2]/22 text-accent 2xl:h-12 2xl:w-12">
                <KeyRound className="h-5 w-5 2xl:h-6 2xl:w-6" />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-bold text-foreground 2xl:text-lg">Bright Data</h2>
                <p className="mt-1 text-[13px] leading-5 text-muted 2xl:text-sm 2xl:leading-6">
                  LinkedIn and Indeed vacancy search use this server-side API key.
                </p>
              </div>
            </div>
            <span
              className={cn(
                "inline-flex h-8 w-fit items-center gap-2 rounded-md border px-3 text-xs font-bold",
                settings.has_brightdata_api_key
                  ? "border-success/35 bg-success/12 text-success"
                  : "border-border bg-[#fff8f1] text-muted",
              )}
            >
              {settings.has_brightdata_api_key ? <Check className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}
              {settings.has_brightdata_api_key ? "Configured" : "Not configured"}
            </span>
          </div>

          <div className="mt-6 grid gap-5">
            <div className="grid gap-2">
              <p className="text-sm font-bold text-[#1d1e1c] 2xl:text-base">Current key</p>
              <div className="flex min-w-0 overflow-hidden rounded-md border border-border bg-[#ffffff]">
                <div className="min-w-0 flex-1 px-3 py-3 font-mono text-sm font-semibold text-muted 2xl:px-4 2xl:text-base">
                  {currentKeyPreview}
                </div>
              </div>
            </div>

            <label className="grid gap-2">
              <span className="text-sm font-bold text-[#1d1e1c] 2xl:text-base">Bright Data API key</span>
              <input
                type="password"
                value={apiKeyDraft}
                onChange={(event) => {
                  setApiKeyDraft(event.target.value);
                  onConnectionDraftChange();
                }}
                placeholder="Enter your Bright Data API key"
                className="h-12 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70 2xl:h-[52px] 2xl:px-4 2xl:text-base"
                autoComplete="off"
              />
              <span className="text-sm font-medium text-muted">
                You can find your API key in your{" "}
                <a
                  href="https://brightdata.com/cp"
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 font-semibold text-[#fa5d00] transition hover:text-accent"
                >
                  Bright Data dashboard
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
                .
              </span>
            </label>

            <div className="rounded-md border border-border bg-[#fff8f1] px-4 py-4 2xl:px-5 2xl:py-5">
              <div className="grid gap-3 sm:grid-cols-[28px_minmax(0,1fr)]">
                <Info className="mt-0.5 h-5 w-5 text-[#fa5d00]" />
                <div>
                  <h3 className="text-sm font-bold text-[#1d1e1c] 2xl:text-base">How it works</h3>
                  <p className="mt-2 max-w-[720px] text-sm leading-6 text-muted 2xl:text-base 2xl:leading-7">
                    Your API key is saved securely and used for LinkedIn and Indeed vacancy search on the server side.
                    <br />
                    The full key is never returned by the settings API.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <p
                className={cn(
                  "flex items-center gap-3 text-sm font-semibold 2xl:text-base",
                  status === "error"
                    ? "text-[#fa5d00]"
                    : settings.has_brightdata_api_key
                      ? "text-success"
                      : "text-muted",
                )}
              >
                {status === "error" ? <X className="h-5 w-5" /> : <ShieldCheck className="h-5 w-5" />}
                {statusMessage}
              </p>
              <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                {settings.has_brightdata_api_key && (
                  <Button
                    type="button"
                    variant="ghost"
                    className="h-12 w-full rounded-md border border-border bg-transparent px-6 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8] sm:w-auto 2xl:h-[52px] 2xl:text-sm"
                    disabled={status === "loading"}
                    onClick={() => void saveBrightDataKey("")}
                  >
                    Clear key
                  </Button>
                )}
                <Button
                  type="button"
                  className="h-12 w-full rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-7 text-[13px] text-foreground shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#e95300] hover:to-[#e95300] sm:w-auto 2xl:h-[52px] 2xl:text-sm"
                  disabled={status === "loading" || !hasApiKeyDraft}
                  onClick={() => void saveBrightDataKey(apiKeyDraft.trim())}
                >
                  <Save className="h-4 w-4" />
                  {status === "loading" ? "Saving..." : "Save settings"}
                </Button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </section>
  );
}
