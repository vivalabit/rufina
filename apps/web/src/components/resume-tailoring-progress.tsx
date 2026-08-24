"use client";

import {
  AlertTriangle,
  Check,
  CircleDot,
  LoaderCircle,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { ResumeGenerationMode } from "@/lib/resume-generation";

export const resumeTailoringAiStages = [
  { id: "recruiter_analysis", label: "Recruiter analysis" },
  { id: "experience_rewrite", label: "Experience rewrite" },
  { id: "ats_final_review", label: "ATS final review" },
] as const;

export const resumeTailoringPdfStages = [
  { id: "rendering_pdf", label: "Rendering PDF" },
  { id: "validating_pdf", label: "Validating PDF" },
] as const;

export const resumeImaginatorStages = [
  { id: "imaginator_generation", label: "Imaginator generation" },
  { id: "immutable_validation", label: "Protected facts audit" },
] as const;

export type ResumeTailoringStageId =
  | (typeof resumeTailoringAiStages)[number]["id"]
  | (typeof resumeImaginatorStages)[number]["id"]
  | (typeof resumeTailoringPdfStages)[number]["id"];

export type ResumeTailoringProgressStatus =
  | "active"
  | "retrying"
  | "completed"
  | "failed";

export type ResumeTailoringProgress = {
  mode?: ResumeGenerationMode;
  stage: ResumeTailoringStageId;
  status: ResumeTailoringProgressStatus;
  message: string;
  attempt: number;
};

type DisplayStatus =
  | ResumeTailoringProgressStatus
  | "pending";

export function ResumeTailoringProgressPanel({
  progress,
}: {
  progress: ResumeTailoringProgress;
}) {
  const mode = progress.mode ?? "recruiter_xyz_ats";
  const generationStages = mode === "imaginator"
    ? resumeImaginatorStages
    : resumeTailoringAiStages;
  const generationGroupLabel = mode === "imaginator"
    ? "Imaginator stages"
    : "AI tailoring stages";
  const stageBadge = mode === "imaginator"
    ? "AI + audit"
    : "3 AI stages";
  return (
    <section
      role="group"
      aria-label="Resume tailoring progress"
      aria-live="polite"
      className={cn(
        "mb-4 overflow-hidden rounded-xl border",
        progress.status === "failed"
          ? "border-accent/25 bg-accent/10"
          : "border-border bg-black/15",
      )}
    >
      <div className="flex flex-col gap-2 border-b border-border px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[10px] font-black uppercase tracking-[0.12em] text-foreground">
              Resume tailoring
            </p>
            <span className="rounded-full border border-[#fa5d00]/25 bg-[#fa5d00]/10 px-2 py-0.5 text-[8px] font-black uppercase tracking-wide text-accent">
              {stageBadge}
            </span>
          </div>
          <p
            className={cn(
              "mt-1 text-[10px] leading-4",
              progress.status === "failed"
                ? "text-accent"
                : "text-muted",
            )}
          >
            {progress.message}
          </p>
        </div>
        {progress.attempt > 1 ? (
          <span className="shrink-0 rounded border border-accent/25 bg-accent/10 px-2 py-1 font-mono text-[9px] font-bold text-accent">
            attempt {progress.attempt}
          </span>
        ) : null}
      </div>

      <div className="grid gap-3 p-3 lg:grid-cols-[minmax(0,3fr)_minmax(230px,2fr)]">
        <ProgressStageGroup
          label={generationGroupLabel}
          stages={generationStages}
          progress={progress}
          numbered
        />
        <ProgressStageGroup
          label="PDF processing stages"
          stages={resumeTailoringPdfStages}
          progress={progress}
        />
      </div>
    </section>
  );
}

function ProgressStageGroup({
  label,
  stages,
  progress,
  numbered = false,
}: {
  label: string;
  stages: ReadonlyArray<{
    id: ResumeTailoringStageId;
    label: string;
  }>;
  progress: ResumeTailoringProgress;
  numbered?: boolean;
}) {
  return (
    <div
      role="list"
      aria-label={label}
      className={cn(
        "grid gap-2",
        numbered && stages.length === 3
          ? "sm:grid-cols-3"
          : "sm:grid-cols-2",
      )}
    >
      {stages.map((stage, index) => {
        const status = displayStatus(stage.id, progress);
        return (
          <div
            key={stage.id}
            role="listitem"
            aria-label={`${stage.label}: ${statusLabel(status)}`}
            className={cn(
              "rounded-lg border px-2.5 py-2.5",
              stageClassName(status),
            )}
          >
            <div className="flex items-center gap-2">
              <StageIcon status={status} />
              <span
                className={cn(
                  "text-[9px] font-black uppercase tracking-wide",
                  stageTextClassName(status),
                )}
              >
                {numbered ? `${index + 1}. ` : ""}
                {stage.label}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function stagesForProgress(progress: ResumeTailoringProgress) {
  return [
    ...(progress.mode === "imaginator"
      ? resumeImaginatorStages
      : resumeTailoringAiStages),
    ...resumeTailoringPdfStages,
  ] as ReadonlyArray<{ id: ResumeTailoringStageId; label: string }>;
}

function displayStatus(
  stageId: ResumeTailoringStageId,
  progress: ResumeTailoringProgress,
): DisplayStatus {
  const allStages = stagesForProgress(progress);
  const currentIndex = allStages.findIndex(
    (stage) => stage.id === progress.stage,
  );
  const stageIndex = allStages.findIndex((stage) => stage.id === stageId);
  if (stageIndex < currentIndex) return "completed";
  if (stageIndex > currentIndex) return "pending";
  return progress.status;
}

function statusLabel(status: DisplayStatus): string {
  if (status === "retrying") return "retrying";
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  if (status === "active") return "in progress";
  return "pending";
}

function stageClassName(status: DisplayStatus): string {
  if (status === "completed") {
    return "border-success/20 bg-success/[0.05]";
  }
  if (status === "failed") {
    return "border-accent/25 bg-accent/10";
  }
  if (status === "active" || status === "retrying") {
    return "border-accent/30 bg-accent/[0.07]";
  }
  return "border-border bg-[#fff8f1]";
}

function stageTextClassName(status: DisplayStatus): string {
  if (status === "completed") return "text-success";
  if (status === "failed") return "text-accent";
  if (status === "active" || status === "retrying") return "text-foreground";
  return "text-muted";
}

function StageIcon({ status }: { status: DisplayStatus }) {
  if (status === "completed") {
    return <Check className="h-3.5 w-3.5 shrink-0 text-success" />;
  }
  if (status === "failed") {
    return (
      <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-accent" />
    );
  }
  if (status === "active" || status === "retrying") {
    return (
      <LoaderCircle className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" />
    );
  }
  return <CircleDot className="h-3.5 w-3.5 shrink-0 text-muted" />;
}

export function completedResumeTailoringProgress(
  message = "PDF rendered and validated",
  attempt = 1,
  mode: ResumeGenerationMode = "recruiter_xyz_ats",
): ResumeTailoringProgress {
  return {
    mode,
    stage: "validating_pdf",
    status: "completed",
    message,
    attempt,
  };
}
