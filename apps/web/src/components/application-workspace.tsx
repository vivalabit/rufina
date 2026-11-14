"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  CheckCircle2,
  Circle,
  Download,
  ExternalLink,
  FileText,
  HelpCircle,
  LoaderCircle,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";

import { DocumentPdfPreview } from "@/components/document-pdf-preview";
import { Button } from "@/components/ui/button";
import { documentDownloadUrl } from "@/features/applications/api/document-access-client";
import {
  cancelGenerationRun,
  fetchCurrentGenerationRun,
  fetchCurrentMasterResumeSummary,
  fetchGenerationRun,
  fetchGenerationRuns,
  fetchGenerationRunTemplates,
  fetchGenerationRunTemplateThumbnail,
  generationArtifactUrl,
  renderGenerationRun,
  startGenerationRun,
  type CoverageStatus,
  type GenerationRun,
  type GenerationRunCheck,
  type GenerationRunStage,
  type GenerationRunTemplate,
  type MasterResumeSummary,
  type TailoringCoverageItem,
  type TailoringReport,
} from "@/features/applications/api/generation-runs-client";
import {
  generationRequestFromSettings,
  generationResumeTemplate,
  normalizeDocumentPreparationSettings,
  rememberDocumentTemplateId,
  rememberedDocumentTemplateId,
  type DocumentPreparationSettings,
  type PreparationDocumentType,
  type PreparationLanguage,
} from "@/features/applications/model/document-preparation";
import { normalizeJobsChJobUrl } from "@/lib/job-url";
import { cn } from "@/lib/utils";
import type {
  ApplicationDocument,
  ApplicationStatus,
  LegacyCandidateConfirmation,
} from "@/shared/types/application";
import type { Job } from "@/shared/types/job";

type WorkspaceApplication = {
  id: string;
  status: ApplicationStatus;
  nextStep: string;
  notes: string;
  job: Pick<
    Job,
    | "id"
    | "title"
    | "company"
    | "location"
    | "type"
    | "overview"
    | "responsibilities"
    | "requirements"
    | "skills"
    | "applyUrl"
    | "sourceUrl"
  >;
  documents: ApplicationDocument[];
  documentPreparation?: DocumentPreparationSettings;
  legacyCandidateConfirmations?: LegacyCandidateConfirmation[];
};

export type ApplicationWorkspaceProps = {
  application: WorkspaceApplication | null;
  backLabel?: string;
  onBack: () => void;
  onPreparationSettingsChange: (
    applicationId: string,
    settings: DocumentPreparationSettings,
  ) => Promise<unknown> | void;
  onStatusChange?: (applicationId: string, status: ApplicationStatus) => void;
  /** Start tailoring as soon as the workspace opens, when no run exists yet. */
  autoStart?: boolean;
  onAutoStartHandled?: () => void;
};

type DocumentType = "tailored_resume" | "cover_letter";
type WorkspaceAction = "" | "start" | "cancel" | "render";

const workflowSteps: Array<{
  id: GenerationRunStage;
  label: string;
  waitingLabel: string;
  detail: string;
}> = [
  {
    id: "sources",
    label: "Vacancy",
    waitingLabel: "Reading the vacancy",
    detail: "Finding the skills and tasks the posting asks for.",
  },
  {
    id: "fit",
    label: "Plan",
    waitingLabel: "Selecting your experience",
    detail: "Ranking the statements of your profile against the vacancy.",
  },
  {
    id: "draft",
    label: "Wording",
    waitingLabel: "Writing",
    detail: "Rephrasing your statements in the words of the vacancy.",
  },
  {
    id: "review",
    label: "Fact check",
    waitingLabel: "Checking facts",
    detail: "Comparing every sentence with your profile.",
  },
  {
    id: "pdf_checks",
    label: "Documents",
    waitingLabel: "Building the documents",
    detail: "Rendering the PDF and fitting it to the page limit.",
  },
];

const stageOrder: Record<GenerationRunStage, number> = {
  sources: 0,
  fit: 1,
  draft: 2,
  review: 3,
  pdf_checks: 4,
  final_review: 5,
};

const activeStatuses = ["queued", "running", "awaiting_approval"];
const terminalStatuses = ["completed", "failed", "cancelled"];

function documentLabel(type: PreparationDocumentType) {
  return type === "tailored_resume" ? "CV" : "Cover letter";
}

function latestArtifact(run: GenerationRun, artifactType: string) {
  return [...run.artifacts]
    .filter((artifact) => artifact.artifactType === artifactType)
    .sort((a, b) => b.version - a.version)[0] ?? null;
}

function runTemplateId(run: GenerationRun) {
  const created = run.events.find((event) => event.kind === "run.created");
  return generationResumeTemplate(
    run.result.render?.templateId
      ?? latestArtifact(run, "resume_pdf")?.metadata.templateId
      ?? latestArtifact(run, "cover_letter_pdf")?.metadata.templateId
      ?? created?.data.documentTemplateId
      ?? created?.data.resumeTemplateId,
  ).id;
}

/** The latest result of every check that applies to the files currently shown. */
function currentChecks(run: GenerationRun): GenerationRunCheck[] {
  const templateId = run.result.render?.templateId;
  const latest = new Map<string, GenerationRunCheck>();
  for (const check of run.checks) {
    const checkedTemplate = check.data.templateId;
    if (templateId && typeof checkedTemplate === "string" && checkedTemplate !== templateId) {
      continue;
    }
    latest.set(`${check.checkType}:${String(check.data.document ?? "")}`, check);
  }
  return [...latest.values()];
}

function checkMessage(check: GenerationRunCheck) {
  if (typeof check.data.message === "string" && check.data.message) {
    return check.data.message;
  }
  return check.checkType.replaceAll("_", " ");
}

function downloadAll(documents: NonNullable<GenerationRun["result"]["documents"]>) {
  documents.forEach((document, index) => {
    window.setTimeout(() => {
      const link = globalThis.document.createElement("a");
      link.href = documentDownloadUrl(document.id, document.version);
      link.download = "";
      globalThis.document.body.append(link);
      link.click();
      link.remove();
    }, index * 180);
  });
}

function runVersionLabel(run: GenerationRun, index: number) {
  const version = Math.max(
    1,
    ...((run.result.documents ?? []).map((document) => document.version)),
  );
  return `Version ${version || index + 1}`;
}

function runErrorMessage(run: GenerationRun | null) {
  const code = run?.error?.code ?? "";
  if (code === "wording_failed" || code === "cover_letter_failed") {
    return "The model did not return text that passes the fact check. Nothing was changed; try again.";
  }
  if (code === "document_render_failed") {
    return "The documents could not be rendered. Try again, or pick another template.";
  }
  if (code === "profile_incomplete" && run?.error?.message) {
    return run.error.message;
  }
  if (code === "invalid_snapshot") {
    return "This run was created by an earlier version of Rufina. Start a new one.";
  }
  if (run?.error?.retryable) {
    return "The AI service did not answer. Your profile and documents were not changed; try again.";
  }
  return "This run could not be completed. Check the details, then try again.";
}

export function ApplicationWorkspace({
  application,
  backLabel = "Applications",
  onBack,
  onPreparationSettingsChange,
  onStatusChange,
  autoStart = false,
  onAutoStartHandled,
}: ApplicationWorkspaceProps) {
  const applicationId = application?.id ?? "";
  const [settings, setSettings] = useState(() => initialSettings(application));
  const [run, setRun] = useState<GenerationRun | null>(null);
  const [runs, setRuns] = useState<GenerationRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [masterResume, setMasterResume] = useState<MasterResumeSummary | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [action, setAction] = useState<WorkspaceAction>("");
  const [pendingTemplateId, setPendingTemplateId] = useState("");
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<DocumentType>("tailored_resume");
  const [revisionRequest, setRevisionRequest] = useState("");
  const [isPreparingRevision, setIsPreparingRevision] = useState(false);
  const terminalRefreshRef = useRef("");
  const autoStartRef = useRef(false);

  const displayedRun = useMemo(
    () => runs.find((candidate) => candidate.id === selectedRunId) ?? run,
    [run, runs, selectedRunId],
  );

  const refreshHistory = useCallback(async (signal?: AbortSignal) => {
    if (!applicationId) return;
    try {
      setRuns(await fetchGenerationRuns(applicationId, signal));
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      // History is supplementary; the active run remains usable.
    }
  }, [applicationId]);

  const refreshRun = useCallback(async (signal?: AbortSignal) => {
    if (!applicationId) return null;
    const current = await fetchCurrentGenerationRun(applicationId, signal);
    setRun(current);
    return current;
  }, [applicationId]);

  useEffect(() => {
    setSettings(initialSettings(application));
    // The saved options of an application are the only input here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [application?.documentPreparation, applicationId]);

  useEffect(() => {
    const controller = new AbortController();
    setRun(null);
    setRuns([]);
    setSelectedRunId("");
    setIsPreparingRevision(false);
    setError("");
    setLoadState("loading");
    if (!applicationId) return () => controller.abort();
    void Promise.all([
      refreshRun(controller.signal),
      refreshHistory(controller.signal),
      fetchCurrentMasterResumeSummary(controller.signal).then(setMasterResume),
    ])
      .then(() => setLoadState("ready"))
      .catch((caught) => {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setError(caught instanceof Error ? caught.message : "The workspace could not be loaded.");
        setLoadState("error");
      });
    return () => controller.abort();
  }, [applicationId, refreshHistory, refreshRun]);

  useEffect(() => {
    if (!run || !activeStatuses.includes(run.status)) return;
    const controller = new AbortController();
    const interval = window.setInterval(() => {
      void fetchGenerationRun(applicationId, run.id, controller.signal)
        .then((next) => {
          setRun(next);
          if (terminalStatuses.includes(next.status)) {
            void refreshHistory(controller.signal);
          }
        })
        .catch((caught) => {
          if (caught instanceof DOMException && caught.name === "AbortError") return;
          setError(caught instanceof Error ? caught.message : "Live status was interrupted.");
        });
    }, 1_000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [applicationId, refreshHistory, run]);

  useEffect(() => {
    if (!run || !terminalStatuses.includes(run.status)) return;
    if (terminalRefreshRef.current === `${run.id}:${run.revision}`) return;
    terminalRefreshRef.current = `${run.id}:${run.revision}`;
    void refreshHistory();
  }, [refreshHistory, run]);

  async function persist(next: DocumentPreparationSettings) {
    if (!applicationId) return;
    setSettings(next);
    await onPreparationSettingsChange(applicationId, next);
  }

  function updateSettings(
    update: (current: DocumentPreparationSettings) => DocumentPreparationSettings,
  ) {
    const next = update(settings);
    setSettings(next);
    void Promise.resolve(onPreparationSettingsChange(applicationId, next)).catch((caught: unknown) => {
      setError(caught instanceof Error ? caught.message : "Document options could not be saved.");
    });
  }

  async function startRun(preferences = settings.userPreferences) {
    if (!applicationId || action) return;
    setAction("start");
    setError("");
    try {
      const nextSettings = { ...settings, userPreferences: preferences.trim() };
      await persist(nextSettings);
      const started = await startGenerationRun(applicationId, {
        ...generationRequestFromSettings(nextSettings),
        idempotencyKey: `generation-${crypto.randomUUID?.() ?? Date.now().toString(36)}`,
      });
      setRun(started);
      setSelectedRunId("");
      setRevisionRequest("");
      setIsPreparingRevision(false);
      await refreshHistory();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Tailoring could not be started.");
    } finally {
      setAction("");
    }
  }

  // One click on a vacancy opens this workspace and starts tailoring right away.
  useEffect(() => {
    if (!autoStart || autoStartRef.current || loadState !== "ready") return;
    autoStartRef.current = true;
    onAutoStartHandled?.();
    if (!run && profileHasExperience(masterResume)) void startRun();
    // Runs once, when the workspace has loaded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, loadState]);

  async function cancel() {
    if (!run || action) return;
    setAction("cancel");
    setError("");
    try {
      setRun(await cancelGenerationRun(applicationId, run));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The run could not be cancelled.");
      await refreshRun();
    } finally {
      setAction("");
    }
  }

  async function switchTemplate(target: GenerationRun, templateId: string) {
    if (action || templateId === runTemplateId(target)) return;
    setAction("render");
    setPendingTemplateId(templateId);
    setError("");
    try {
      const updated = await renderGenerationRun(applicationId, target, templateId);
      setRun((current) => (current?.id === updated.id ? updated : current));
      setRuns((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      rememberDocumentTemplateId(templateId);
      updateSettings((current) => ({
        ...current,
        formatting: {
          ...current.formatting,
          resumeTemplateId: templateId,
          coverLetterTemplateId: templateId,
        },
      }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The template could not be applied.");
      await Promise.all([refreshRun(), refreshHistory()]);
    } finally {
      setAction("");
      setPendingTemplateId("");
    }
  }

  if (!application) {
    return (
      <section className="grid min-h-[520px] place-items-center px-5 py-10">
        <div className="max-w-md text-center">
          <FileText className="mx-auto h-8 w-8 text-accent" />
          <h1 className="mt-4 text-xl font-bold">No application selected</h1>
          <Button type="button" variant="ghost" onClick={onBack} className="mt-5 border border-border">
            <ArrowLeft className="h-4 w-4" /> {backLabel}
          </Button>
        </div>
      </section>
    );
  }

  const jobUrl = normalizeJobsChJobUrl(application.job.applyUrl || application.job.sourceUrl || "");
  const isActive = Boolean(run && activeStatuses.includes(run.status));
  const isReady = displayedRun?.status === "completed";
  const completedRuns = runs.filter((candidate) => candidate.status === "completed");
  const hasPreviousDocuments = Boolean(isReady || application.documents.length);
  const isPreparing = !run || (isPreparingRevision && !isActive);
  const showResult = Boolean(isReady && displayedRun && !isPreparingRevision);

  return (
    <section className="application-workspace job-scroll h-full overflow-y-auto">
      <div className={cn("mx-auto w-full px-4 py-4 sm:px-6 lg:px-8", showResult ? "max-w-[1540px]" : "max-w-[1180px]")}>
        <header>
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-2 text-sm font-medium text-muted transition hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> {backLabel}
          </button>
          <div className="mt-2 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h1 className="text-2xl font-semibold leading-[1.2] tracking-[0.015em] text-foreground sm:text-[28px]">
                {application.job.title}
              </h1>
              <p className="mt-1 text-base leading-[1.5] text-muted">
                {application.job.company}
                {application.job.location ? ` · ${application.job.location}` : ""}
                {application.job.type ? ` · ${application.job.type}` : ""}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2.5">
              {isActive ? (
                <span className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#fff3e8] px-4 text-[13px] font-bold text-accent">
                  <LoaderCircle className="h-4 w-4 animate-spin" /> Tailoring
                </span>
              ) : null}
              {showResult && displayedRun?.result.documents?.length ? (
                <Button type="button" onClick={() => downloadAll(displayedRun.result.documents ?? [])} className="rounded-xl px-5 text-[13px]">
                  <Download className="h-4 w-4" /> Download PDF
                </Button>
              ) : null}
              {jobUrl ? (
                <a
                  href={jobUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-2 text-base font-medium !text-accent transition hover:underline"
                >
                  Open application <ExternalLink className="h-3.5 w-3.5" />
                </a>
              ) : null}
              {isReady && application.status !== "applied" && onStatusChange ? (
                <Button type="button" variant="ghost" onClick={() => onStatusChange(application.id, "applied")} className="rounded-xl border border-border text-[13px]">
                  Mark submitted
                </Button>
              ) : application.status === "applied" ? (
                <span className="inline-flex h-10 items-center gap-2 rounded-xl border border-emerald-200 bg-white px-4 text-[13px] font-bold text-emerald-700">
                  <Check className="h-4 w-4" /> Submitted
                </span>
              ) : null}
            </div>
          </div>
        </header>

        {error ? (
          <div role="alert" className="mt-4 flex items-start justify-between gap-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-800">
            <span>{error}</span>
            <button type="button" aria-label="Dismiss error" onClick={() => setError("")}>
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        <div className={cn("mt-4 grid items-start gap-6", showResult && "xl:grid-cols-[minmax(0,1fr)_340px]")}>
          <main className="min-w-0">
            {isReady && run && displayedRun?.id !== run.id && ["failed", "cancelled"].includes(run.status) && !isPreparingRevision ? (
              <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-[13px] leading-5 text-amber-900">
                The latest run {run.status === "failed" ? "did not complete" : "was stopped"}. You are viewing a previous version.
                <button type="button" className="ml-2 font-semibold underline" onClick={() => setSelectedRunId("")}>View latest run</button>
              </div>
            ) : null}
            {loadState === "loading" ? <LoadingWorkspace /> : null}
            {loadState === "error" && !run ? (
              <WorkspaceFailure message={error} onRetry={() => window.location.reload()} />
            ) : null}
            {loadState === "ready" && isPreparing ? (
              <TailorPanel
                settings={settings}
                masterResume={masterResume}
                onChange={updateSettings}
                onStart={() => void startRun()}
                action={action}
                isRevision={hasPreviousDocuments}
                onCancel={run ? () => setIsPreparingRevision(false) : undefined}
              />
            ) : null}
            {run && activeStatuses.includes(run.status) ? (
              <RunProgress run={run} onCancel={() => void cancel()} action={action} />
            ) : null}
            {run?.status === "failed" && !isReady && !isPreparingRevision ? (
              <WorkspaceFailure
                message={runErrorMessage(run)}
                details={run.error?.message}
                onRetry={() => void startRun()}
                onViewPrevious={completedRuns[0] ? () => setSelectedRunId(completedRuns[0].id) : undefined}
              />
            ) : null}
            {run?.status === "cancelled" && !isReady && !isPreparingRevision ? (
              <WorkspaceFailure
                cancelled
                message="This run was stopped. Your profile and earlier documents were not changed."
                onRetry={() => void startRun()}
                onViewPrevious={completedRuns[0] ? () => setSelectedRunId(completedRuns[0].id) : undefined}
              />
            ) : null}
            {showResult && displayedRun ? (
              <DocumentResult
                applicationId={applicationId}
                run={displayedRun}
                completedRuns={completedRuns}
                selectedRunId={selectedRunId}
                activeTab={activeTab}
                revisionRequest={revisionRequest}
                pendingTemplateId={pendingTemplateId}
                action={action}
                onSelectRun={(id) => setSelectedRunId(id || completedRuns[0]?.id || "")}
                onTabChange={setActiveTab}
                onRevisionRequest={setRevisionRequest}
                onRevise={() => void startRun(revisionRequest.trim() || settings.userPreferences)}
                onChangeOptions={() => setIsPreparingRevision(true)}
                onPickTemplate={(templateId) => void switchTemplate(displayedRun, templateId)}
              />
            ) : null}
          </main>

          {showResult && displayedRun ? <ResultSummary run={displayedRun} /> : null}
        </div>
      </div>
    </section>
  );
}

/** A profile without any role cannot be tailored; an unknown shape is left to the server. */
function profileHasExperience(masterResume: MasterResumeSummary | null) {
  if (!masterResume) return false;
  const experiences = masterResume.masterResume.experiences;
  return !Array.isArray(experiences) || experiences.length > 0;
}

function initialSettings(application: WorkspaceApplication | null) {
  const settings = normalizeDocumentPreparationSettings(application?.documentPreparation);
  if (application?.documentPreparation) return settings;
  // A new application starts with the template the person picked last.
  const templateId = rememberedDocumentTemplateId();
  return {
    ...settings,
    formatting: {
      ...settings.formatting,
      resumeTemplateId: templateId,
      coverLetterTemplateId: templateId,
    },
  };
}

function LoadingWorkspace() {
  return (
    <div className="workspace-card grid min-h-[420px] place-items-center">
      <div className="text-center">
        <LoaderCircle className="mx-auto h-7 w-7 animate-spin text-accent" />
        <p className="mt-3 text-[13px] font-semibold text-muted">Restoring application workspace…</p>
      </div>
    </div>
  );
}

function TailorPanel({ settings, masterResume, onChange, onStart, action, isRevision = false, onCancel }: {
  settings: DocumentPreparationSettings;
  masterResume: MasterResumeSummary | null;
  onChange: (update: (current: DocumentPreparationSettings) => DocumentPreparationSettings) => void;
  onStart: () => void;
  action: string;
  isRevision?: boolean;
  onCancel?: () => void;
}) {
  const template = generationResumeTemplate(settings.formatting.resumeTemplateId);
  const hasExperience = profileHasExperience(masterResume);
  return (
    <section className="workspace-card p-5 lg:p-7">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-2xl">
          <h2 className="text-2xl font-semibold leading-[1.26]">
            {isRevision ? "Tailor again" : "Tailor your resume to this vacancy"}
          </h2>
          <p className="mt-2 text-base leading-[1.5] text-muted">
            Your profile is the only source. Rufina selects and rephrases what you wrote there,
            and checks every number and technology against it. You pick the template when the
            documents are ready.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {onCancel ? (
            <Button type="button" variant="ghost" onClick={onCancel} disabled={Boolean(action)} className="h-12 rounded-md text-sm">
              Back to documents
            </Button>
          ) : null}
          <Button
            type="button"
            onClick={onStart}
            disabled={!settings.documentTypes.length || !hasExperience || Boolean(action)}
            className="h-12 rounded-md px-7 text-base"
          >
            {action === "start" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {settings.documentTypes.includes("tailored_resume") ? "Tailor resume" : "Write cover letter"}
          </Button>
        </div>
      </div>
      {!hasExperience ? (
        <div role="alert" className="mt-4 rounded-md border border-border bg-[#fff8f1] px-4 py-3 text-[13px] leading-[1.35] text-muted">
          Documents are built from your profile. Add your experience to the profile first.
        </div>
      ) : null}
      <div className="mt-5 grid gap-4 border-t border-border pt-5 lg:grid-cols-[1.2fr_0.8fr_0.8fr] lg:gap-6">
        <fieldset>
          <legend className="text-sm font-semibold leading-[1.4]">Documents</legend>
          <div className="mt-2 grid grid-cols-2 gap-3">
            {(["tailored_resume", "cover_letter"] as const).map((type) => {
              const selected = settings.documentTypes.includes(type);
              return (
                <label key={type} className={cn("flex cursor-pointer items-center gap-2 rounded-md border px-3 py-3 transition has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent has-[:focus-visible]:ring-offset-2", selected ? "border-[#e3d6c5] bg-[#fff8f1]" : "border-border bg-white")}>
                  <input
                    type="checkbox"
                    aria-label={documentLabel(type)}
                    className="sr-only"
                    checked={selected}
                    onChange={() => onChange((current) => ({
                      ...current,
                      documentTypes: selected
                        ? current.documentTypes.filter((item) => item !== type)
                        : [...current.documentTypes, type],
                    }))}
                  />
                  <span className={cn("grid h-5 w-5 shrink-0 place-items-center rounded-full border", selected ? "border-accent bg-accent text-white" : "border-border text-transparent")}>
                    <Check className="h-3 w-3" />
                  </span>
                  <span className="text-sm font-medium leading-[1.4]">{documentLabel(type)}</span>
                </label>
              );
            })}
          </div>
        </fieldset>
        <label className="text-sm font-semibold leading-[1.4]">Language
          <select
            aria-label="Document language"
            value={settings.languageChoice ?? "Auto"}
            onChange={(event) => onChange((current) => ({ ...current, languageChoice: event.target.value as PreparationLanguage }))}
            className="mt-2 h-11 w-full rounded-md border px-4 text-base font-normal"
          >
            <option value="Auto">Same as the vacancy</option>
            <option value="English">English</option>
            <option value="German">German</option>
          </select>
        </label>
        <label className="text-sm font-semibold leading-[1.4]">CV page limit
          <select
            aria-label="CV page limit"
            value={settings.formatting.resumeMaxPages}
            disabled={!settings.documentTypes.includes("tailored_resume")}
            onChange={(event) => onChange((current) => ({
              ...current,
              formatting: {
                ...current.formatting,
                resumeMaxPages:
                  event.target.value === "auto" ? "auto" : (Number(event.target.value) as 1 | 2 | 3),
              },
            }))}
            className="mt-2 h-11 w-full rounded-md border px-4 text-base font-normal disabled:opacity-50"
          >
            <option value="auto">Auto (by experience)</option>
            <option value="1">1 page</option>
            <option value="2">2 pages</option>
            <option value="3">3 pages</option>
          </select>
        </label>
      </div>
      <label className="mt-4 flex min-w-0 flex-col text-sm font-semibold leading-[1.4]">
        <span>Your wishes <span className="ml-1 text-[13px] font-normal text-muted">Optional. Style and emphasis only; facts come from your profile.</span></span>
        <textarea
          aria-label="Your wishes"
          value={settings.userPreferences}
          maxLength={10_000}
          onChange={(event) => onChange((current) => ({ ...current, userPreferences: event.target.value }))}
          placeholder="For example: emphasize backend work, keep sentences short."
          className="mt-2 h-20 min-h-16 w-full resize-y rounded-md border px-4 py-3 text-base font-normal leading-[1.5] placeholder:text-[#8e8b87]"
        />
      </label>
      <p className="mt-4 text-[13px] leading-[1.35] text-muted">
        Template: <span className="font-semibold text-foreground">{template.name}</span>. You can switch it in one click on the result, without tailoring again.
      </p>
    </section>
  );
}

function RunProgress({ run, onCancel, action }: { run: GenerationRun; onCancel: () => void; action: string }) {
  const current = stageOrder[run.stage];
  return (
    <section className="workspace-card p-6 sm:p-8">
      <div className="mx-auto max-w-lg">
        <h2 className="text-xl font-semibold">Tailoring your documents</h2>
        <p className="mt-1 text-[13px] leading-5 text-muted">This usually takes less than a minute. You can leave this page; the run continues.</p>
        <ol aria-label="Tailoring progress" className="mt-6 grid gap-4">
          {workflowSteps.map((step, index) => {
            const complete = index < current;
            const active = index === current && run.status !== "queued";
            const waiting = run.status === "queued" && index === 0;
            return (
              <li key={step.id} aria-current={active || waiting ? "step" : undefined} className="flex items-start gap-3">
                <span className={cn(
                  "mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full border text-[13px] font-semibold",
                  complete ? "border-accent bg-accent text-white" : active || waiting ? "border-accent text-accent" : "border-border text-muted",
                )}>
                  {complete ? <Check className="h-3.5 w-3.5" /> : active || waiting ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : index + 1}
                </span>
                <span>
                  <span className={cn("block text-sm font-semibold", complete || active || waiting ? "text-foreground" : "text-muted")}>
                    {active || waiting ? step.waitingLabel : step.label}
                  </span>
                  {active || waiting ? <span className="mt-0.5 block text-[13px] leading-5 text-muted">{step.detail}</span> : null}
                </span>
              </li>
            );
          })}
        </ol>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={Boolean(action) || run.cancelRequested} className="mt-6 rounded-xl border border-border text-[13px]">
          {run.cancelRequested ? "Stopping…" : "Stop"}
        </Button>
      </div>
    </section>
  );
}

function WorkspaceFailure({ message, details, onRetry, onViewPrevious, cancelled = false }: {
  message: string;
  details?: string;
  onRetry: () => void;
  onViewPrevious?: () => void;
  cancelled?: boolean;
}) {
  return (
    <section className="workspace-card grid min-h-[420px] place-items-center p-6 text-center">
      <div className="w-full max-w-md">
        <span className={cn("mx-auto grid h-14 w-14 place-items-center rounded-2xl", cancelled ? "bg-[#fff3e8] text-accent" : "bg-red-50 text-red-700")}>
          {cancelled ? <Circle className="h-6 w-6" /> : <AlertTriangle className="h-6 w-6" />}
        </span>
        <h2 className="mt-4 text-lg font-semibold">{cancelled ? "Run stopped" : "Tailoring did not finish"}</h2>
        <p className="mt-2 text-[13px] leading-5 text-muted">{message}</p>
        {details ? (
          <details className="mt-4 text-left text-[13px] leading-5">
            <summary className="cursor-pointer font-medium">Technical details</summary>
            <p className="mt-2 max-h-52 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-stone-50 p-3 text-muted">{details}</p>
          </details>
        ) : null}
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          {onViewPrevious ? <Button type="button" variant="outline" onClick={onViewPrevious} className="rounded-xl text-[13px]">View last version</Button> : null}
          <Button type="button" onClick={onRetry} className="rounded-xl text-[13px]"><RefreshCw className="h-4 w-4" /> Try again</Button>
        </div>
      </div>
    </section>
  );
}

function DocumentResult({ applicationId, run, completedRuns, selectedRunId, activeTab, revisionRequest, pendingTemplateId, action, onSelectRun, onTabChange, onRevisionRequest, onRevise, onChangeOptions, onPickTemplate }: {
  applicationId: string;
  run: GenerationRun;
  completedRuns: GenerationRun[];
  selectedRunId: string;
  activeTab: DocumentType;
  revisionRequest: string;
  pendingTemplateId: string;
  action: WorkspaceAction;
  onSelectRun: (runId: string) => void;
  onTabChange: (tab: DocumentType) => void;
  onRevisionRequest: (value: string) => void;
  onRevise: () => void;
  onChangeOptions: () => void;
  onPickTemplate: (templateId: string) => void;
}) {
  const documents = run.result.documents ?? [];
  const tab = documents.some((item) => item.type === activeTab) ? activeTab : documents[0]?.type ?? activeTab;
  const document = documents.find((item) => item.type === tab);
  const prefix = tab === "tailored_resume" ? "resume" : "cover_letter";
  const pdf = latestArtifact(run, `${prefix}_pdf`);
  const docx = latestArtifact(run, `${prefix}_docx`);
  const pages = run.result.render?.pages?.[tab];
  return (
    <section className="workspace-card overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-border px-4 sm:flex-row sm:items-center sm:justify-between">
        <div role="tablist" aria-label="Generated documents" className="flex gap-6">
          {(["tailored_resume", "cover_letter"] as const).map((type) => {
            const available = documents.some((item) => item.type === type);
            return (
              <button
                key={type}
                type="button"
                role="tab"
                aria-selected={tab === type}
                disabled={!available}
                onClick={() => onTabChange(type)}
                className={cn("border-b-2 px-1 py-4 text-[13px] font-bold transition", tab === type ? "border-accent text-foreground" : "border-transparent text-muted", !available && "opacity-40")}
              >
                {documentLabel(type)}
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2 pb-3 sm:pb-0">
          {pages ? <span className="text-[13px] leading-[1.35] text-muted">{pages} {pages === 1 ? "page" : "pages"}</span> : null}
          <select
            aria-label="Document version"
            value={run.id === completedRuns[0]?.id ? "" : selectedRunId}
            onChange={(event) => onSelectRun(event.target.value)}
            className="h-9 rounded-lg border px-3 text-[13px] font-bold"
          >
            <option value="">Latest version</option>
            {completedRuns.filter((item) => item.id !== completedRuns[0]?.id).map((item, index) => (
              <option key={item.id} value={item.id}>
                {runVersionLabel(item, index + 1)} · {new Date(item.createdAt).toLocaleDateString()}
              </option>
            ))}
          </select>
          {document ? (
            <a
              href={documentDownloadUrl(document.id, document.version)}
              download
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border px-3 text-[13px] font-bold transition hover:bg-[#fff3e8]"
              aria-label={`Download ${documentLabel(tab)} as PDF`}
            >
              <Download className="h-3.5 w-3.5" /> PDF
            </a>
          ) : null}
          {docx ? (
            <a
              href={generationArtifactUrl(applicationId, run.id, docx.id)}
              download={docx.fileName}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border px-3 text-[13px] font-bold transition hover:bg-[#fff3e8]"
              aria-label={`Download ${documentLabel(tab)} as Word`}
            >
              <Download className="h-3.5 w-3.5" /> Word
            </a>
          ) : null}
        </div>
      </div>

      <TemplatePicker
        applicationId={applicationId}
        run={run}
        pendingTemplateId={pendingTemplateId}
        disabled={Boolean(action)}
        onPick={onPickTemplate}
      />

      {document ? (
        <div className={cn("bg-[#f3f1ef] p-3 transition-opacity sm:p-5", action === "render" && "opacity-50")}>
          <DocumentPdfPreview
            document={{
              id: document.id,
              title: documentLabel(document.type),
              currentVersion: document.version,
              versions: [{
                version: document.version,
                artifact: { fileName: pdf?.fileName ?? `${document.type}.pdf`, contentType: "application/pdf" },
              }],
            }}
            label={documentLabel(document.type)}
          />
        </div>
      ) : (
        <div className="grid min-h-[320px] place-items-center px-6 text-center text-[13px] leading-5 text-muted">
          {tab === "cover_letter" && run.documentTypes.includes("cover_letter")
            ? "The cover letter was not created because its text did not pass the fact check. Tailor again to retry."
            : "This document was not part of the run."}
        </div>
      )}

      <div className="border-t border-border p-4">
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <MessageSquareText className="absolute left-3 top-3 h-4 w-4 text-muted" />
            <textarea
              aria-label="Change request"
              value={revisionRequest}
              maxLength={10_000}
              onChange={(event) => onRevisionRequest(event.target.value)}
              placeholder="Ask for a change, for example: more emphasis on data pipelines, shorter summary."
              className="h-11 min-h-11 w-full resize-y rounded-xl border py-2.5 pl-9 pr-3 text-[13px] leading-5"
            />
          </div>
          <Button type="button" variant="outline" onClick={onRevise} disabled={Boolean(action)} className="h-11 rounded-xl text-[13px]">
            {action === "start" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Tailor again
          </Button>
          <Button type="button" variant="ghost" onClick={onChangeOptions} disabled={Boolean(action)} className="h-11 rounded-xl border border-border text-[13px]">
            Options
          </Button>
        </div>
        <p className="mt-2 text-[13px] leading-4 text-muted">Tailoring again creates a new version from your current profile. Earlier versions stay available.</p>
      </div>
    </section>
  );
}

function TemplatePicker({ applicationId, run, pendingTemplateId, disabled, onPick }: {
  applicationId: string;
  run: GenerationRun;
  pendingTemplateId: string;
  disabled: boolean;
  onPick: (templateId: string) => void;
}) {
  const [templates, setTemplates] = useState<GenerationRunTemplate[]>([]);
  const selectedId = runTemplateId(run);
  const hasResume = run.documentTypes.includes("tailored_resume");

  useEffect(() => {
    const controller = new AbortController();
    void fetchGenerationRunTemplates(applicationId, run.id, controller.signal)
      .then(setTemplates)
      .catch(() => {
        // Without the gallery the documents stay usable in their current template.
      });
    return () => controller.abort();
  }, [applicationId, run.id]);

  if (!templates.length) return null;
  return (
    <fieldset disabled={disabled} className="border-b border-border px-4 py-4">
      <legend className="sr-only">Template</legend>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-semibold">Template</p>
        <p className="text-[13px] leading-4 text-muted">One click re-renders the same content. Nothing is rewritten.</p>
      </div>
      <div className="job-scroll mt-3 flex gap-3 overflow-x-auto pb-1">
        {templates.map((template) => {
          const selected = template.id === selectedId;
          const pending = template.id === pendingTemplateId;
          return (
            <button
              key={template.id}
              type="button"
              aria-pressed={selected}
              aria-label={`${template.name} template`}
              title={template.description}
              onClick={() => onPick(template.id)}
              className={cn(
                "group relative w-[132px] shrink-0 rounded-lg border bg-white p-1.5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2",
                selected ? "border-accent shadow-[0_0_0_1px_var(--color-rufina-flame)]" : "border-border hover:border-[#d8c7b3]",
                disabled && !pending && "opacity-60",
              )}
            >
              <span className="relative block aspect-[210/297] overflow-hidden rounded-md bg-[#f3f1ef]">
                {hasResume ? <TemplateThumbnail url={template.thumbnailUrl} alt="" /> : <FileText className="absolute inset-0 m-auto h-6 w-6 text-muted" />}
                {pending ? (
                  <span className="absolute inset-0 grid place-items-center bg-white/70">
                    <LoaderCircle className="h-5 w-5 animate-spin text-accent" />
                  </span>
                ) : null}
                {selected && !pending ? (
                  <span className="absolute right-1.5 top-1.5 grid h-5 w-5 place-items-center rounded-full bg-accent text-white">
                    <Check className="h-3 w-3" />
                  </span>
                ) : null}
              </span>
              <span className="mt-1.5 block truncate text-[13px] font-semibold">{template.name}</span>
              <span className={cn("block text-[11px] font-medium leading-4", template.atsSafe ? "text-emerald-700" : "text-amber-700")}>
                {template.atsSafe ? "ATS-friendly" : "Design · ATS risk"}
              </span>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

function TemplateThumbnail({ url, alt }: { url: string; alt: string }) {
  const [source, setSource] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl = "";
    setSource("");
    setFailed(false);
    void fetchGenerationRunTemplateThumbnail(url, controller.signal)
      .then((blob) => {
        if (typeof URL.createObjectURL !== "function") return;
        objectUrl = URL.createObjectURL(blob);
        setSource(objectUrl);
      })
      .catch((caught) => {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setFailed(true);
      });
    return () => {
      controller.abort();
      if (objectUrl && typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(objectUrl);
    };
  }, [url]);

  if (source) {
    // eslint-disable-next-line @next/next/no-img-element -- a blob URL of an authenticated API image
    return <img src={source} alt={alt} className="h-full w-full object-cover object-top" />;
  }
  return failed
    ? <FileText className="absolute inset-0 m-auto h-6 w-6 text-muted" />
    : <LoaderCircle className="absolute inset-0 m-auto h-4 w-4 animate-spin text-muted" />;
}

const coverageStyles: Record<CoverageStatus, string> = {
  experience: "border-emerald-200 bg-emerald-50 text-emerald-800",
  skills: "border-amber-200 bg-amber-50 text-amber-900",
  missing: "border-border bg-white text-muted line-through decoration-[#c0bbb6]",
};

const coverageTitles: Record<CoverageStatus, string> = {
  experience: "Shown in your experience",
  skills: "Listed in your skills only",
  missing: "Not in the resume",
};

function ResultSummary({ run }: { run: GenerationRun }) {
  const report: TailoringReport | undefined = run.result.tailoring;
  const checks = currentChecks(run);
  const warnings = run.result.warnings ?? [];
  const changes = report?.changes ?? run.result.review?.meaningfulChanges ?? [];
  const before = report?.score?.before;
  const after = report?.score?.after;
  const coverage = report?.coverage ?? [];
  const gaps = report?.gaps ?? [];
  const knockouts = report?.knockouts ?? [];
  const usage = run.result.usage;
  return (
    <aside className="workspace-card p-5" aria-label="Tailoring summary">
      {typeof after === "number" ? (
        <div>
          <h2 className="text-base font-semibold">Vacancy match</h2>
          <div className="mt-3 flex items-end gap-3">
            {typeof before === "number" && before !== after ? (
              <>
                <span className="text-2xl font-semibold leading-none text-muted" aria-label={`Before tailoring: ${before}`}>{before}</span>
                <span aria-hidden="true" className="pb-0.5 text-muted">→</span>
              </>
            ) : null}
            <span
              className={cn("text-4xl font-semibold leading-none", after >= 80 ? "text-emerald-700" : after >= 60 ? "text-foreground" : "text-amber-700")}
              aria-label={`After tailoring: ${after}`}
            >
              {after}
            </span>
            <span className="pb-1 text-[13px] text-muted">of 100</span>
          </div>
          <p className="mt-2 text-[13px] leading-5 text-muted">
            Share of the skills in the vacancy that a reader finds in your resume. A forecast by Rufina, not the grade of an applicant tracking system.
          </p>
        </div>
      ) : (
        <h2 className="text-base font-semibold">Summary</h2>
      )}

      {coverage.length ? (
        <div className="mt-5 border-t border-border pt-4">
          <CoverageGroup title="Required" items={coverage.filter((item) => item.importance === "required")} />
          <CoverageGroup title="Nice to have" items={coverage.filter((item) => item.importance === "preferred")} />
          <ul className="mt-3 grid gap-1 text-[12px] leading-4 text-muted">
            {(Object.keys(coverageTitles) as CoverageStatus[]).map((status) => (
              <li key={status} className="flex items-center gap-2">
                <span className={cn("inline-block h-2.5 w-2.5 rounded-full border", coverageStyles[status])} />
                {coverageTitles[status]}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {knockouts.length ? (
        <div className="mt-5 border-t border-border pt-4">
          <h3 className="text-sm font-semibold">Must-haves</h3>
          <ul className="mt-3 grid gap-2.5">
            {knockouts.map((item) => (
              <li key={`${item.kind}:${item.requirement}`} className="flex gap-2 text-[13px] leading-5">
                {item.met === true ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                  : item.met === false ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
                  : <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-muted" />}
                <span>
                  {item.requirement}
                  <span className="block text-[12px] leading-4 text-muted">
                    {item.met === null ? "Check this yourself" : item.detail}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {changes.length ? (
        <div className="mt-5 border-t border-border pt-4">
          <h3 className="text-sm font-semibold">What changed</h3>
          <ul className="mt-3 grid gap-2.5">
            {changes.map((change) => (
              <li key={change} className="flex gap-2 text-[13px] leading-5">
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" />{change}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {gaps.length ? (
        <div className="mt-5 border-t border-border pt-4">
          <h3 className="text-sm font-semibold">Not in your profile</h3>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {gaps.map((gap) => (
              <span key={gap.label} className={cn("rounded-full border px-2.5 py-1 text-[12px] font-semibold", gap.importance === "required" ? "border-amber-300 bg-amber-50 text-amber-900" : "border-border text-muted")}>
                {gap.label}
              </span>
            ))}
          </div>
          <p className="mt-2 text-[13px] leading-5 text-muted">
            These were not added, because your profile does not mention them. If you have this experience, add it to your profile and tailor again.
          </p>
        </div>
      ) : null}

      {checks.length || warnings.length ? (
        <div className="mt-5 border-t border-border pt-4">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold"><ShieldCheck className="h-4 w-4 text-accent" /> Checks</h3>
          <ul className="mt-3 grid gap-2.5">
            {checks.map((check) => (
              <li key={check.id} className={cn("flex gap-2 text-[13px] leading-5", check.status === "failed" && "text-red-800")}>
                {check.status === "passed"
                  ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                  : <AlertTriangle className={cn("mt-0.5 h-4 w-4 shrink-0", check.status === "failed" ? "text-red-700" : "text-amber-700")} />}
                {checkMessage(check)}
              </li>
            ))}
            {warnings.filter((warning) => !checks.some((check) => checkMessage(check) === warning)).map((warning) => (
              <li key={warning} className="flex gap-2 text-[13px] leading-5">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />{warning}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="mt-5 border-t border-border pt-4 text-[12px] leading-4 text-muted">
        {run.model}
        {typeof usage?.seconds === "number" ? ` · ${Math.round(usage.seconds)} s` : ""}
        {usage?.inputTokens || usage?.outputTokens ? ` · ${((usage.inputTokens ?? 0) + (usage.outputTokens ?? 0)).toLocaleString()} tokens` : ""}
      </p>
    </aside>
  );
}

function CoverageGroup({ title, items }: { title: string; items: TailoringCoverageItem[] }) {
  if (!items.length) return null;
  return (
    <div className="mb-3">
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span
            key={`${item.importance}:${item.label}`}
            title={coverageTitles[item.after]}
            className={cn("rounded-full border px-2.5 py-1 text-[12px] font-semibold", coverageStyles[item.after])}
          >
            {item.label}
            <span className="sr-only">: {coverageTitles[item.after]}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
