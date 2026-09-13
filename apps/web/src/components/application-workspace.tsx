"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  Download,
  ExternalLink,
  FileCheck2,
  FileText,
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
  answerGenerationRun,
  cancelGenerationRun,
  fetchCurrentGenerationRun,
  fetchCurrentMasterResumeSummary,
  fetchGenerationRun,
  fetchGenerationRuns,
  startGenerationRun,
  type GenerationRun,
  type GenerationRunCheck,
  type GenerationRunStage,
  type MasterResumeSummary,
} from "@/features/applications/api/generation-runs-client";
import {
  generationRequestFromSettings,
  normalizeDocumentPreparationSettings,
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
};

const workflowStages: Array<{
  id: GenerationRunStage;
  label: string;
  waitingLabel: string;
}> = [
  { id: "sources", label: "Sources", waitingLabel: "Preparing sources" },
  { id: "fit", label: "Fit", waitingLabel: "Evaluating fit" },
  { id: "draft", label: "Draft & review", waitingLabel: "Writing drafts" },
  { id: "pdf_checks", label: "PDF checks", waitingLabel: "Checking PDFs" },
  { id: "final_review", label: "Final review", waitingLabel: "Finalizing" },
];

const stageOrder: Record<GenerationRunStage, number> = {
  sources: 0,
  fit: 1,
  draft: 2,
  review: 2,
  pdf_checks: 3,
  final_review: 4,
};

type WorkspaceTab = "tailored_resume" | "cover_letter" | "changes";

function documentLabel(type: PreparationDocumentType) {
  return type === "tailored_resume" ? "CV" : "Cover letter";
}

function backendLabel(backend: string) {
  return backend === "openai_api" ? "OpenAI API" : "OpenClaw";
}

function titleCase(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function sourceVersions(run: GenerationRun | null) {
  const event = run?.events.find((item) => item.kind === "run.created");
  return {
    application: Number(event?.data.applicationRevision) || null,
    vacancy: Number(event?.data.vacancyRevision) || null,
    masterResume: Number(event?.data.masterProfileVersion) || null,
  };
}

function latestFinalArtifact(
  run: GenerationRun,
  type: "tailored_resume" | "cover_letter",
) {
  const preferred = type === "tailored_resume" ? "resume_pdf" : "cover_letter_pdf";
  return [...run.artifacts]
    .reverse()
    .find((artifact) =>
      artifact.documentType === type
      && artifact.contentType === "application/pdf"
      && artifact.artifactType === preferred
    ) ?? null;
}

function checkLabel(check: GenerationRunCheck) {
  const labels: Record<string, string> = {
    text_layer: "PDF text is readable",
    page_count: "Page count is within the limit",
    required_identity: "Name and contact details verified",
    protected_dates: "Employment dates match the profile",
    keyword_coverage: "Relevant vacancy terms are covered",
    glyphs: "No broken or missing glyphs",
    geometry: "Layout stays within page bounds",
  };
  return labels[check.checkType] ?? titleCase(check.checkType);
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

function runErrorMessage(run: GenerationRun | null, fallback = "Something went wrong.") {
  return run?.error?.message || fallback;
}

export function ApplicationWorkspace({
  application,
  backLabel = "Applications",
  onBack,
  onPreparationSettingsChange,
  onStatusChange,
}: ApplicationWorkspaceProps) {
  const applicationId = application?.id ?? "";
  const [settings, setSettings] = useState(() =>
    normalizeDocumentPreparationSettings(application?.documentPreparation),
  );
  const [run, setRun] = useState<GenerationRun | null>(null);
  const [runs, setRuns] = useState<GenerationRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [masterResume, setMasterResume] = useState<MasterResumeSummary | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [action, setAction] = useState<"" | "start" | "answer" | "cancel">("");
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("tailored_resume");
  const [revisionRequest, setRevisionRequest] = useState("");
  const terminalRefreshRef = useRef("");

  const displayedRun = useMemo(
    () => runs.find((candidate) => candidate.id === selectedRunId) ?? run,
    [run, runs, selectedRunId],
  );

  const refreshHistory = useCallback(async (signal?: AbortSignal) => {
    if (!applicationId) return;
    try {
      const history = await fetchGenerationRuns(applicationId, signal);
      setRuns(history);
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
    const controller = new AbortController();
    setSettings(normalizeDocumentPreparationSettings(application?.documentPreparation));
    setRun(null);
    setRuns([]);
    setSelectedRunId("");
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
  }, [application?.documentPreparation, applicationId, refreshHistory, refreshRun]);

  useEffect(() => {
    if (!run || !["queued", "running", "awaiting_approval"].includes(run.status)) return;
    const controller = new AbortController();
    const interval = window.setInterval(() => {
      void fetchGenerationRun(applicationId, run.id, controller.signal)
        .then((next) => {
          setRun(next);
          if (["completed", "failed", "cancelled"].includes(next.status)) {
            void refreshHistory(controller.signal);
          }
        })
        .catch((caught) => {
          if (caught instanceof DOMException && caught.name === "AbortError") return;
          setError(caught instanceof Error ? caught.message : "Live status was interrupted.");
        });
    }, 1_500);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [applicationId, refreshHistory, run]);

  useEffect(() => {
    if (!run || !["completed", "failed", "cancelled"].includes(run.status)) return;
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
      const request = generationRequestFromSettings(nextSettings);
      const started = await startGenerationRun(applicationId, {
        ...request,
        formattingParameters: {
          ...request.formattingParameters,
          ...(request.formattingParameters.tailored_resume
            ? {
                tailored_resume: {
                  ...request.formattingParameters.tailored_resume,
                  language: masterResume?.masterResume.language || nextSettings.language,
                },
              }
            : {}),
          ...(request.formattingParameters.cover_letter
            ? {
                cover_letter: {
                  ...request.formattingParameters.cover_letter,
                  language: nextSettings.language,
                },
              }
            : {}),
        },
        idempotencyKey: `generation-${crypto.randomUUID?.() ?? Date.now().toString(36)}`,
      });
      setRun(started);
      setSelectedRunId("");
      setRevisionRequest("");
      await refreshHistory();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The document run could not be started.");
    } finally {
      setAction("");
    }
  }

  async function answer(response: "continue" | "stop") {
    if (!run || action) return;
    setAction("answer");
    setError("");
    try {
      const updated = await answerGenerationRun(applicationId, run, response);
      setRun(updated);
      await refreshHistory();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The decision could not be saved.");
      await refreshRun();
    } finally {
      setAction("");
    }
  }

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
  const versions = sourceVersions(run);
  const isActive = Boolean(run && ["queued", "running", "awaiting_approval"].includes(run.status));
  const isReady = displayedRun?.status === "completed";
  const passedChecks = displayedRun?.checks.filter((check) => check.status === "passed") ?? [];
  const failedChecks = displayedRun?.checks.filter((check) => check.status === "failed") ?? [];
  const review = displayedRun?.result.review;
  const fit = displayedRun?.result.fit;
  const visualReview = displayedRun?.result.visualReview;
  const completedRuns = runs.filter((candidate) => candidate.status === "completed");

  return (
    <section className="application-workspace job-scroll h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-[1540px] px-4 py-5 sm:px-6 lg:px-8">
        <header>
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-1 text-xs font-semibold text-muted transition hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> {backLabel}
          </button>
          <div className="mt-3 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <h1 className="text-2xl font-black tracking-[-0.03em] text-foreground sm:text-[30px]">
                {application.job.title}
              </h1>
              <p className="mt-1.5 text-sm text-muted">
                {application.job.company}
                {application.job.location ? ` · ${application.job.location}` : ""}
                {application.job.type ? ` · ${application.job.type}` : ""}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2.5">
              {isReady ? (
                <span className="inline-flex h-10 items-center gap-2 rounded-xl bg-emerald-50 px-4 text-xs font-bold text-emerald-800">
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-600" /> Ready for your review
                </span>
              ) : isActive ? (
                <span className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#fff3e8] px-4 text-xs font-bold text-accent">
                  <LoaderCircle className="h-4 w-4 animate-spin" /> Run in progress
                </span>
              ) : null}
              {isReady && displayedRun?.result.documents?.length ? (
                <Button type="button" onClick={() => downloadAll(displayedRun.result.documents ?? [])} className="rounded-xl px-5 text-xs">
                  <Download className="h-4 w-4" /> Download documents
                </Button>
              ) : null}
              {jobUrl ? (
                <a
                  href={jobUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex h-10 items-center gap-2 rounded-xl border border-accent bg-white px-4 text-xs font-bold text-foreground transition hover:bg-[#fff3e8]"
                >
                  Open application <ExternalLink className="h-3.5 w-3.5" />
                </a>
              ) : null}
              {isReady && application.status !== "applied" && onStatusChange ? (
                <Button type="button" variant="ghost" onClick={() => onStatusChange(application.id, "applied")} className="rounded-xl border border-border text-xs">
                  Mark submitted
                </Button>
              ) : application.status === "applied" ? (
                <span className="inline-flex h-10 items-center gap-2 rounded-xl border border-emerald-200 bg-white px-4 text-xs font-bold text-emerald-700">
                  <Check className="h-4 w-4" /> Submitted
                </span>
              ) : null}
            </div>
          </div>
        </header>

        <WorkflowProgress run={run} />

        {error ? (
          <div role="alert" className="mt-4 flex items-start justify-between gap-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-800">
            <span>{error}</span>
            <button type="button" aria-label="Dismiss error" onClick={() => setError("")}>
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        <div className="mt-5 grid items-start gap-4 lg:grid-cols-[280px_minmax(0,1fr)] 2xl:grid-cols-[300px_minmax(560px,1fr)_310px]">
          <ApplicationBrief
            application={application}
            run={run}
            masterResume={masterResume}
            settings={settings}
            versions={versions}
          />

          <main className="min-w-0">
            {loadState === "loading" ? <LoadingWorkspace /> : null}
            {loadState === "error" && !run ? (
              <WorkspaceFailure message={error} onRetry={() => window.location.reload()} />
            ) : null}
            {loadState !== "loading" && !run ? (
              <PreparationPanel settings={settings} masterResume={masterResume} onChange={updateSettings} onStart={() => void startRun()} action={action} />
            ) : null}
            {run?.status === "awaiting_approval" ? (
              <FitApproval run={run} onAnswer={answer} action={action} />
            ) : null}
            {run && ["queued", "running"].includes(run.status) ? (
              <RunProgress run={run} onCancel={() => void cancel()} action={action} />
            ) : null}
            {run?.status === "failed" ? (
              <WorkspaceFailure message={runErrorMessage(run)} onRetry={() => void startRun()} />
            ) : null}
            {run?.status === "cancelled" ? (
              <WorkspaceFailure cancelled message="This run was stopped. Your source documents were not changed." onRetry={() => void startRun()} />
            ) : null}
            {isReady && displayedRun ? (
              <DocumentReview
                run={displayedRun}
                completedRuns={completedRuns}
                selectedRunId={selectedRunId}
                activeTab={activeTab}
                revisionRequest={revisionRequest}
                onSelectRun={setSelectedRunId}
                onTabChange={setActiveTab}
                onRevisionRequest={setRevisionRequest}
                onRevise={() => void startRun(revisionRequest)}
                action={action}
              />
            ) : null}
          </main>

          <ReviewSummary
            className="lg:col-span-2 2xl:col-span-1"
            run={displayedRun}
            fit={fit}
            review={review}
            visualSummary={visualReview?.summary}
            passedChecks={passedChecks}
            failedChecks={failedChecks}
          />
        </div>
      </div>
    </section>
  );
}

function WorkflowProgress({ run }: { run: GenerationRun | null }) {
  const current = run ? stageOrder[run.stage] : 0;
  return (
    <ol aria-label="Application document workflow" className="mt-5 grid gap-2 sm:grid-cols-5 sm:gap-0">
      {workflowStages.map((stage, index) => {
        const complete = Boolean(run && (index < current || run.status === "completed"));
        const active = !complete && index === current;
        return (
          <li key={stage.id} aria-current={active ? "step" : undefined} className="flex min-w-0 items-center">
            <span className={cn(
              "grid h-8 w-8 shrink-0 place-items-center rounded-full border text-xs font-black",
              complete ? "border-accent bg-accent text-white" : active ? "border-accent bg-accent text-white" : "border-border bg-white text-muted",
            )}>
              {complete ? <Check className="h-4 w-4" /> : index + 1}
            </span>
            <span className={cn("ml-3 whitespace-nowrap text-xs font-bold", active || complete ? "text-foreground" : "text-muted")}>{stage.label}</span>
            {index < workflowStages.length - 1 ? (
              <span aria-hidden="true" className={cn("mx-4 hidden h-px min-w-4 flex-1 sm:block", index < current ? "bg-accent" : "bg-border")} />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function ApplicationBrief({
  application,
  run,
  masterResume,
  settings,
  versions,
}: {
  application: WorkspaceApplication;
  run: GenerationRun | null;
  masterResume: MasterResumeSummary | null;
  settings: DocumentPreparationSettings;
  versions: ReturnType<typeof sourceVersions>;
}) {
  const recentEvents = (run?.events ?? []).slice(-5).reverse();
  return (
    <aside className="workspace-card p-5">
      <h2 className="text-base font-black">Application brief</h2>
      <div className="mt-4 grid gap-3">
        <SourceRow title="Job description" subtitle={versions.vacancy ? `Snapshot · v${versions.vacancy}` : "Full posting saved"} ready={Boolean(application.job.overview || application.job.requirements.length)} />
        <SourceRow title="Master Resume" subtitle={`Version ${versions.masterResume ?? masterResume?.version ?? "—"} · Confirmed`} ready={Boolean(masterResume || versions.masterResume)} />
      </div>
      <div className="my-5 h-px bg-border" />
      <h3 className="text-sm font-black">Documents</h3>
      <div className="mt-3 grid gap-2">
        {["tailored_resume", "cover_letter"].map((type) => (
          <div key={type} className="flex items-center gap-2 text-xs font-semibold">
            <span className={cn("grid h-5 w-5 place-items-center rounded-md border", settings.documentTypes.includes(type as PreparationDocumentType) ? "border-accent bg-accent text-white" : "border-border text-transparent")}>
              <Check className="h-3 w-3" />
            </span>
            {documentLabel(type as PreparationDocumentType)}
          </div>
        ))}
      </div>
      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-[11px]">
        <dt className="text-muted">CV language</dt><dd className="text-right font-semibold">{masterResume?.masterResume.language || settings.language}</dd>
        <dt className="text-muted">Letter language</dt><dd className="text-right font-semibold">{settings.language}</dd>
        <dt className="text-muted">CV template</dt><dd className="truncate text-right font-semibold">ModernCV · Banking</dd>
        <dt className="text-muted">Letter template</dt><dd className="truncate text-right font-semibold">Classic letter</dd>
        {run ? <><dt className="text-muted">Executor</dt><dd className="truncate text-right font-semibold">{backendLabel(run.backend)}</dd></> : null}
      </dl>
      {recentEvents.length ? (
        <div className="mt-5 border-t border-border pt-4">
          <h3 className="text-[10px] font-black uppercase tracking-[0.12em] text-muted">Activity</h3>
          <ol className="mt-3 grid gap-2.5">
            {recentEvents.map((event) => (
              <li key={event.sequence} className="flex gap-2 text-[10px] leading-4 text-muted">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                <span><strong className="font-bold text-foreground">{titleCase(event.kind)}</strong><br />{new Date(event.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </aside>
  );
}

function SourceRow({ title, subtitle, ready }: { title: string; subtitle: string; ready: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-border bg-[#fff8f1]"><FileText className="h-4 w-4" /></span>
      <span className="min-w-0 flex-1"><span className="block text-xs font-semibold">{title}</span><span className="mt-0.5 block truncate text-[10px] text-muted">{subtitle}</span></span>
      {ready ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" /> : <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" />}
    </div>
  );
}

function LoadingWorkspace() {
  return <div className="workspace-card grid min-h-[520px] place-items-center"><div className="text-center"><LoaderCircle className="mx-auto h-7 w-7 animate-spin text-accent" /><p className="mt-3 text-xs font-semibold text-muted">Restoring application workspace…</p></div></div>;
}

function PreparationPanel({ settings, masterResume, onChange, onStart, action }: {
  settings: DocumentPreparationSettings;
  masterResume: MasterResumeSummary | null;
  onChange: (update: (current: DocumentPreparationSettings) => DocumentPreparationSettings) => void;
  onStart: () => void;
  action: string;
}) {
  return (
    <section className="workspace-card overflow-hidden">
      <div className="border-b border-border px-5 py-4 sm:px-6">
        <p className="text-[10px] font-black uppercase tracking-[0.14em] text-accent">Sources</p>
        <h2 className="mt-1 text-lg font-black">Prepare your application pack</h2>
        <p className="mt-1 text-xs leading-5 text-muted">Rufina snapshots the confirmed profile and full vacancy before the AI run starts.</p>
      </div>
      <div className="grid gap-5 p-5 sm:p-6">
        {!masterResume ? (
          <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-900">Confirm a Master Resume in Profile before generating application documents.</div>
        ) : null}
        <fieldset>
          <legend className="text-xs font-black">Documents</legend>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {(["tailored_resume", "cover_letter"] as const).map((type) => {
              const selected = settings.documentTypes.includes(type);
              return (
                <label key={type} className={cn("flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition", selected ? "border-accent bg-[#fff7ef]" : "border-border bg-white")}>
                  <input type="checkbox" className="sr-only" checked={selected} onChange={() => onChange((current) => ({ ...current, documentTypes: selected ? current.documentTypes.filter((item) => item !== type) : [...current.documentTypes, type] }))} />
                  <span className={cn("mt-0.5 grid h-5 w-5 place-items-center rounded-md border", selected ? "border-accent bg-accent text-white" : "border-border text-transparent")}><Check className="h-3 w-3" /></span>
                  <span><span className="block text-xs font-bold">{documentLabel(type)}</span><span className="mt-1 block text-[10px] leading-4 text-muted">{type === "tailored_resume" ? "Tailored from confirmed profile facts" : "Written for this vacancy and company"}</span></span>
                </label>
              );
            })}
          </div>
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-xs font-bold">Vacancy / letter language
            <select aria-label="Vacancy and letter language" value={settings.language} onChange={(event) => onChange((current) => ({ ...current, language: event.target.value as PreparationLanguage }))} className="mt-2 h-11 w-full rounded-xl border px-3 text-xs font-semibold">
              <option value="English">English</option><option value="German">German</option>
            </select>
            <span className="mt-1.5 block text-[9px] font-normal leading-4 text-muted">The CV keeps the confirmed profile language ({masterResume?.masterResume.language || settings.language}).</span>
          </label>
          <label className="text-xs font-bold">CV page limit
            <select aria-label="CV page limit" value={settings.formatting.resumeMaxPages} onChange={(event) => onChange((current) => ({ ...current, formatting: { ...current.formatting, resumeMaxPages: Number(event.target.value) as 1 | 2 | 3 } }))} className="mt-2 h-11 w-full rounded-xl border px-3 text-xs font-semibold">
              <option value="1">1 page</option><option value="2">2 pages</option><option value="3">3 pages</option>
            </select>
          </label>
        </div>
        <div className="grid gap-3 rounded-xl border border-border bg-[#fffaf5] p-4 sm:grid-cols-2">
          <div><p className="text-[10px] font-black uppercase tracking-[0.12em] text-muted">CV template</p><p className="mt-1 text-xs font-bold">ModernCV · Banking</p><p className="mt-1 text-[10px] text-muted">Original upstream LaTeX template</p></div>
          <div><p className="text-[10px] font-black uppercase tracking-[0.12em] text-muted">Cover letter template</p><p className="mt-1 text-xs font-bold">Classic letter</p><p className="mt-1 text-[10px] text-muted">Original upstream LaTeX template</p></div>
        </div>
        <label className="text-xs font-bold">Your preferences
          <textarea aria-label="Your preferences" value={settings.userPreferences} maxLength={10_000} onChange={(event) => onChange((current) => ({ ...current, userPreferences: event.target.value }))} placeholder="For example: emphasize design systems and keep the tone direct." className="mt-2 min-h-24 w-full resize-y rounded-xl border px-3 py-3 text-xs leading-5" />
        </label>
        <div className="flex flex-col gap-3 border-t border-border pt-5 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-xl text-[10px] leading-4 text-muted">The first run evaluates fit and pauses for your approval before writing. Generation never marks the application as submitted.</p>
          <Button type="button" onClick={onStart} disabled={!masterResume || !settings.documentTypes.length || Boolean(action)} className="rounded-xl px-5 text-xs">
            {action === "start" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Start application
          </Button>
        </div>
      </div>
    </section>
  );
}

function FitApproval({ run, onAnswer, action }: { run: GenerationRun; onAnswer: (response: "continue" | "stop") => void; action: string }) {
  const fit = run.result.fit ?? {};
  return (
    <section className="workspace-card overflow-hidden">
      <div className="border-b border-border px-5 py-4 sm:px-6"><p className="text-[10px] font-black uppercase tracking-[0.14em] text-accent">Fit</p><h2 className="mt-1 text-lg font-black">Review the match before writing</h2></div>
      <div className="p-5 sm:p-6">
        <div className="flex flex-col gap-5 rounded-2xl border border-border bg-[#fffaf5] p-5 sm:flex-row sm:items-center">
          <div className="grid h-24 w-24 shrink-0 place-items-center rounded-full bg-[conic-gradient(var(--color-rufina-flame)_0deg,var(--color-rufina-flame)_var(--fit-score),#eadfd4_var(--fit-score),#eadfd4_360deg)] p-2" style={{ "--fit-score": `${Math.max(0, Math.min(100, fit.overallScore ?? 0)) * 3.6}deg` } as CSSProperties}><span className="grid h-full w-full place-items-center rounded-full bg-white text-2xl font-black">{fit.overallScore ?? "—"}</span></div>
          <div><span className="rounded-full bg-emerald-100 px-2.5 py-1 text-[9px] font-black uppercase tracking-wide text-emerald-800">{fit.recommendation ?? "Review"}</span><p className="mt-3 text-sm font-bold leading-6">{fit.summary ?? "The fit assessment is ready."}</p></div>
        </div>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <FitList title="Strengths" items={fit.strengths ?? []} positive />
          <FitList title="Honest gaps" items={fit.gaps ?? []} />
        </div>
        {(fit.keywords ?? []).length ? <div className="mt-5"><h3 className="text-xs font-black">Relevant terms</h3><div className="mt-2 flex flex-wrap gap-2">{fit.keywords?.map((keyword) => <span key={keyword.term} className={cn("rounded-full border px-2.5 py-1 text-[9px] font-bold", keyword.support === "supported" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800")}>{keyword.term}</span>)}</div></div> : null}
        {(fit.clarificationQuestions ?? []).length ? <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4"><h3 className="text-xs font-black text-amber-950">Questions from the fit review</h3><ul className="mt-2 grid gap-2">{fit.clarificationQuestions?.map((question) => <li key={question} className="flex gap-2 text-[11px] leading-5 text-amber-900"><span aria-hidden="true">?</span>{question}</li>)}</ul><p className="mt-2 text-[9px] leading-4 text-amber-800">Stop and add answers to your confirmed profile if they introduce new facts. Continuing keeps the gaps explicit.</p></div> : null}
        <div className="mt-6 flex flex-col gap-3 border-t border-border pt-5 sm:flex-row sm:items-center sm:justify-between"><p className="text-xs font-semibold">{run.pendingQuestion?.prompt ?? "Continue with the CV and cover letter?"}</p><div className="flex gap-2"><Button type="button" variant="ghost" disabled={Boolean(action)} onClick={() => onAnswer("stop")} className="rounded-xl border border-border text-xs">Stop</Button><Button type="button" disabled={Boolean(action)} onClick={() => onAnswer("continue")} className="rounded-xl px-5 text-xs">{action === "answer" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ChevronRight className="h-4 w-4" />} Continue</Button></div></div>
      </div>
    </section>
  );
}

function FitList({ title, items, positive = false }: { title: string; items: string[]; positive?: boolean }) {
  return <div className="rounded-xl border border-border p-4"><h3 className="text-xs font-black">{title}</h3><ul className="mt-3 grid gap-2">{items.length ? items.map((item) => <li key={item} className="flex gap-2 text-[11px] leading-5"><span className={cn("mt-1 grid h-4 w-4 shrink-0 place-items-center rounded-full", positive ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-800")}>{positive ? <Check className="h-2.5 w-2.5" /> : "!"}</span>{item}</li>) : <li className="text-[11px] text-muted">None identified.</li>}</ul></div>;
}

function RunProgress({ run, onCancel, action }: { run: GenerationRun; onCancel: () => void; action: string }) {
  const current = stageOrder[run.stage];
  const currentStage = workflowStages[current];
  return (
    <section className="workspace-card grid min-h-[560px] place-items-center p-6 text-center">
      <div className="max-w-md"><span className="mx-auto grid h-16 w-16 place-items-center rounded-2xl bg-[#fff3e8] text-accent"><LoaderCircle className="h-7 w-7 animate-spin" /></span><p className="mt-5 text-[10px] font-black uppercase tracking-[0.14em] text-accent">{currentStage?.label}</p><h2 className="mt-2 text-xl font-black">{currentStage?.waitingLabel}</h2><p className="mt-2 text-xs leading-5 text-muted">The author and independent reviewer are working from immutable snapshots. You can leave this page; progress will be restored when you return.</p><div className="mt-5 rounded-xl border border-border bg-[#fffaf5] px-4 py-3 text-left text-[10px] leading-4 text-muted"><strong className="text-foreground">{backendLabel(run.backend)}</strong> · {run.model}<br />Run {run.id.slice(0, 8)} · revision {run.revision}</div><Button type="button" variant="ghost" disabled={Boolean(action) || run.cancelRequested} onClick={onCancel} className="mt-5 rounded-xl border border-border text-xs">{action === "cancel" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}{run.cancelRequested ? "Cancellation requested" : "Cancel run"}</Button></div>
    </section>
  );
}

function WorkspaceFailure({ message, onRetry, cancelled = false }: { message: string; onRetry: () => void; cancelled?: boolean }) {
  return <section className="workspace-card grid min-h-[520px] place-items-center p-6 text-center"><div className="max-w-md"><span className={cn("mx-auto grid h-14 w-14 place-items-center rounded-2xl", cancelled ? "bg-[#fff3e8] text-accent" : "bg-red-50 text-red-700")}>{cancelled ? <Circle className="h-6 w-6" /> : <AlertTriangle className="h-6 w-6" />}</span><h2 className="mt-4 text-lg font-black">{cancelled ? "Run stopped" : "Generation needs attention"}</h2><p className="mt-2 text-xs leading-5 text-muted">{message}</p><Button type="button" onClick={onRetry} className="mt-5 rounded-xl text-xs"><RefreshCw className="h-4 w-4" /> Start a new run</Button></div></section>;
}

function DocumentReview({ run, completedRuns, selectedRunId, activeTab, revisionRequest, onSelectRun, onTabChange, onRevisionRequest, onRevise, action }: {
  run: GenerationRun;
  completedRuns: GenerationRun[];
  selectedRunId: string;
  activeTab: WorkspaceTab;
  revisionRequest: string;
  onSelectRun: (runId: string) => void;
  onTabChange: (tab: WorkspaceTab) => void;
  onRevisionRequest: (value: string) => void;
  onRevise: () => void;
  action: string;
}) {
  const document = run.result.documents?.find((item) => item.type === activeTab);
  const artifact = activeTab === "changes" ? null : latestFinalArtifact(run, activeTab);
  return (
    <section className="workspace-card overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-border px-4 sm:flex-row sm:items-center sm:justify-between">
        <div role="tablist" aria-label="Generated documents" className="flex gap-6">
          {(["tailored_resume", "cover_letter", "changes"] as const).map((tab) => {
            const disabled = tab !== "changes" && !run.documentTypes.includes(tab);
            return <button key={tab} type="button" role="tab" aria-selected={activeTab === tab} disabled={disabled} onClick={() => onTabChange(tab)} className={cn("border-b-2 px-1 py-4 text-xs font-bold transition", activeTab === tab ? "border-accent text-accent" : "border-transparent text-muted", disabled && "opacity-40")}>{tab === "changes" ? "Changes" : documentLabel(tab)}</button>;
          })}
        </div>
        <div className="flex items-center gap-2 pb-3 sm:pb-0">
          <select aria-label="Document version" value={selectedRunId} onChange={(event) => onSelectRun(event.target.value)} className="h-9 rounded-lg border px-3 text-[10px] font-bold">
            <option value="">Latest version</option>
            {completedRuns.filter((item) => item.id !== completedRuns[0]?.id).map((item, index) => <option key={item.id} value={item.id}>{runVersionLabel(item, index + 1)} · {new Date(item.createdAt).toLocaleDateString()}</option>)}
          </select>
          {document ? <a href={documentDownloadUrl(document.id, document.version)} download className="grid h-9 w-9 place-items-center rounded-lg border border-border text-muted transition hover:bg-[#fff3e8] hover:text-foreground" aria-label={`Download ${documentLabel(document.type)}`}><Download className="h-4 w-4" /></a> : null}
        </div>
      </div>
      {activeTab === "changes" ? (
        <ChangesPanel run={run} />
      ) : document ? (
        <div className="bg-[#f3f1ef] p-3 sm:p-5">
          <DocumentPdfPreview document={{ id: document.id, title: documentLabel(document.type), currentVersion: document.version, versions: [{ version: document.version, artifact: { fileName: artifact?.fileName ?? `${document.type}.pdf`, contentType: "application/pdf" } }] }} label={documentLabel(document.type)} />
        </div>
      ) : (
        <div className="grid min-h-[520px] place-items-center text-xs text-muted">This document was not included in the run.</div>
      )}
      <div className="border-t border-border p-4">
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1"><MessageSquareText className="absolute left-3 top-3 h-4 w-4 text-muted" /><textarea aria-label="Revision request" value={revisionRequest} maxLength={10_000} onChange={(event) => onRevisionRequest(event.target.value)} placeholder="Request a factual change or a different emphasis…" className="min-h-11 w-full resize-y rounded-xl border py-2.5 pl-10 pr-3 text-xs leading-5" /></div>
          <Button type="button" variant="outline" onClick={onRevise} disabled={!revisionRequest.trim() || Boolean(action)} className="h-11 rounded-xl text-xs">{action === "start" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Create revision</Button>
        </div>
        <p className="mt-2 text-[9px] leading-4 text-muted">A revision starts a new immutable run and repeats author review, PDF compilation, and all checks.</p>
      </div>
    </section>
  );
}

function ChangesPanel({ run }: { run: GenerationRun }) {
  const changes = run.result.review?.meaningfulChanges ?? [];
  return <div className="min-h-[520px] p-5 sm:p-6"><p className="text-[10px] font-black uppercase tracking-[0.14em] text-accent">Reviewer report</p><h2 className="mt-1 text-lg font-black">What changed</h2><p className="mt-2 text-xs leading-5 text-muted">{run.result.review?.summary ?? "The independent review completed."}</p><ol className="mt-5 grid gap-3">{changes.length ? changes.map((change, index) => <li key={`${change}-${index}`} className="flex gap-3 rounded-xl border border-border px-4 py-3 text-xs leading-5"><span className="grid h-6 w-6 shrink-0 place-items-center rounded-full border border-border text-[10px] font-black">{index + 1}</span>{change}</li>) : <li className="rounded-xl border border-border px-4 py-3 text-xs text-muted">No content revisions were required.</li>}</ol></div>;
}

function ReviewSummary({ className, run, fit, review, visualSummary, passedChecks, failedChecks }: {
  className?: string;
  run: GenerationRun | null;
  fit: GenerationRun["result"]["fit"];
  review: GenerationRun["result"]["review"];
  visualSummary?: string;
  passedChecks: GenerationRunCheck[];
  failedChecks: GenerationRunCheck[];
}) {
  const complete = run?.status === "completed" && failedChecks.length === 0;
  return (
    <aside className={cn("workspace-card p-5", className)}>
      <h2 className="text-base font-black">Review summary</h2>
      <div className={cn("mt-4 rounded-xl border p-4", complete ? "border-emerald-100 bg-emerald-50" : "border-border bg-[#fffaf5]")}>
        <div className="flex gap-3"><span className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-full text-white", complete ? "bg-emerald-600" : "bg-muted")}>{complete ? <Check className="h-5 w-5" /> : <ShieldCheck className="h-5 w-5" />}</span><div><p className="text-xs font-black">{complete ? "Checks complete" : run ? "Review in progress" : "Not started"}</p><p className="mt-1 text-[10px] leading-4 text-muted">{complete ? "Both documents are ready to inspect" : "Verified results appear here"}</p></div></div>
      </div>
      {passedChecks.length ? <ul className="mt-4 grid gap-3">{passedChecks.slice(-7).map((check) => <li key={check.id} className="flex gap-2 text-[11px] leading-4"><CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />{checkLabel(check)}</li>)}</ul> : null}
      {failedChecks.length ? <ul className="mt-4 grid gap-3">{failedChecks.map((check) => <li key={check.id} className="flex gap-2 text-[11px] leading-4 text-red-800"><AlertTriangle className="h-4 w-4 shrink-0" />{checkLabel(check)}</li>)}</ul> : null}
      {review?.meaningfulChanges?.length ? <div className="mt-5 border-t border-border pt-4"><h3 className="text-sm font-black">What changed</h3><ol className="mt-3 grid gap-3">{review.meaningfulChanges.slice(0, 4).map((change, index) => <li key={`${change}-${index}`} className="flex gap-2 text-[11px] leading-5"><span className="grid h-5 w-5 shrink-0 place-items-center rounded-full border border-border text-[9px] font-black">{index + 1}</span>{change}</li>)}</ol></div> : null}
      {fit?.gaps?.length ? <div className="mt-5 border-t border-border pt-4"><h3 className="text-sm font-black">Honest gaps</h3><p className="mt-2 text-[11px] leading-5 text-muted">{fit.gaps[0]}</p></div> : null}
      {visualSummary ? <div className="mt-5 border-t border-border pt-4"><h3 className="text-sm font-black">Visual review</h3><p className="mt-2 text-[11px] leading-5 text-muted">{visualSummary}</p></div> : null}
      {run ? <p className="mt-5 border-t border-border pt-4 text-[9px] leading-4 text-muted"><FileCheck2 className="mr-1 inline h-3 w-3" />Checks are bound to this artifact SHA. Older results never validate a newer revision.</p> : null}
    </aside>
  );
}
