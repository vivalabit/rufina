"use client";

import {
  Check,
  CircleDot,
  FileText,
  Save,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import { InfoStat } from "@/components/info-stat";
import { JobRoleIcon } from "@/components/job-visuals";
import { Button } from "@/components/ui/button";
import { getApplicationDocumentBadge } from "@/features/applications/formatting";
import {
  applicationEventOutcomes,
  applicationEventStatuses,
  applicationEventTypes,
  trackedApplicationStatuses,
} from "@/features/applications/model/constants";
import type { ManualApplicationDraft } from "@/features/applications/model/types";
import {
  formatAiMatchTimestamp,
  formatConfidence,
} from "@/features/jobs/formatting";
import {
  buildAiMatchRawExplanation,
  buildRecommendationPlan,
  formatMatchValue,
  getAiMatchBreakdownItems,
  getAiMatchSourceDisplay,
} from "@/features/jobs/model/ai-match";
import { cn } from "@/lib/utils";
import type {
  ApplicationEventDraft,
  ApplicationEventOutcome,
  ApplicationEventStatus,
  ApplicationEventType,
  ApplicationStatus,
  TrackedApplication,
} from "@/shared/types/application";
import type { CandidateProfile } from "@/shared/types/profile";

type ManualApplicationDialogProps = {
  draft: ManualApplicationDraft;
  profile: CandidateProfile;
  isSaving: boolean;
  error: string;
  onChange: <Field extends keyof ManualApplicationDraft>(
    field: Field,
    value: ManualApplicationDraft[Field],
  ) => void;
  onUseProfileResume: () => void;
  onAttachResume: (file: File | undefined) => void;
  onClose: () => void;
  onSave: () => void;
};

export function ManualApplicationDialog({
  draft,
  profile,
  isSaving,
  error,
  onChange,
  onUseProfileResume,
  onAttachResume,
  onClose,
  onSave,
}: ManualApplicationDialogProps) {
  const canSave = Boolean(
    draft.title.trim() &&
    draft.company.trim() &&
    draft.location.trim() &&
    draft.applyUrl.trim() &&
    draft.overview.trim(),
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="manual-application-dialog-title"
        className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[780px] flex-col overflow-hidden border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] 2xl:p-5"
      >
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2
              id="manual-application-dialog-title"
              className="text-[22px] font-bold leading-tight text-foreground"
            >
              Add application
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              Create a tracked vacancy manually
            </p>
          </div>
          <button
            type="button"
            aria-label="Close manual application"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 grid min-h-0 flex-1 gap-4 overflow-y-auto pr-1 md:grid-cols-2">
          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Role title</span>
            <input
              value={draft.title}
              onChange={(event) => onChange("title", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Senior Product Designer"
            />
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Company</span>
            <input
              value={draft.company}
              onChange={(event) => onChange("company", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Company name"
            />
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Location</span>
            <input
              value={draft.location}
              onChange={(event) => onChange("location", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Zurich, Remote, Europe"
            />
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Status</span>
            <select
              value={draft.status}
              onChange={(event) =>
                onChange("status", event.target.value as ApplicationStatus)
              }
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
            >
              {trackedApplicationStatuses.map((item) => (
                <option key={item.status} value={item.status}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="grid gap-2 md:col-span-2">
            <span className="text-xs font-bold text-[#1d1e1c]">
              Job posting URL
            </span>
            <input
              value={draft.applyUrl}
              onChange={(event) => onChange("applyUrl", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="https://company.com/careers/role"
            />
          </label>

          <section className="grid gap-2 rounded-md border border-border bg-[#fff8f1] p-3 md:col-span-2">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-xs font-bold text-[#1d1e1c]">
                  Resume for this application
                </h3>
                <p className="mt-1 text-xs font-medium text-muted">
                  Choose the profile resume or upload a different one.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  className="h-8 rounded-md border border-border bg-transparent px-3 text-[12px] text-[#1d1e1c] hover:bg-[#fff3e8]"
                  disabled={
                    !profile.resume_file_name || !profile.resume_file_id
                  }
                  onClick={onUseProfileResume}
                >
                  <FileText className="h-3.5 w-3.5" />
                  Use profile resume
                </Button>
                <label className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-md border border-border bg-transparent px-3 text-[12px] font-semibold text-[#1d1e1c] transition hover:bg-[#fff3e8]">
                  <Upload className="h-3.5 w-3.5" />
                  Upload another
                  <input
                    type="file"
                    accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    className="hidden"
                    onChange={(event) => {
                      onAttachResume(event.target.files?.[0]);
                      event.currentTarget.value = "";
                    }}
                  />
                </label>
              </div>
            </div>

            {draft.documents.length > 0 ? (
              <div className="mt-1 flex items-center gap-2.5 rounded-md border border-border bg-[#fff8f1] px-2.5 py-2 text-[12px] font-semibold text-[#1d1e1c]">
                <span className="grid h-5 min-w-8 place-items-center rounded-sm bg-[#fa5d00] px-1 text-[7px] font-black leading-none text-foreground">
                  {getApplicationDocumentBadge(draft.documents[0])}
                </span>
                <span
                  className="min-w-0 flex-1 truncate"
                  title={draft.documents[0].fileName}
                >
                  {draft.documents[0].title}
                  {draft.documents[0].fileSize ? (
                    <span className="font-medium text-muted">
                      {" "}
                      • {draft.documents[0].fileSize}
                    </span>
                  ) : null}
                </span>
                <button
                  type="button"
                  aria-label="Remove selected resume"
                  title="Remove selected resume"
                  onClick={() => onChange("documents", [])}
                  className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted transition hover:bg-[#fa5d00]/12 hover:text-[#fa5d00]"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : (
              <p className="mt-1 rounded-md border border-dashed border-border bg-[#fff8f1] px-2.5 py-2 text-[12px] font-semibold text-muted">
                No resume selected for this application.
              </p>
            )}
          </section>

          <label className="grid gap-2 md:col-span-2">
            <span className="text-xs font-bold text-[#1d1e1c]">
              Vacancy description
            </span>
            <textarea
              value={draft.overview}
              onChange={(event) => onChange("overview", event.target.value)}
              className="min-h-[190px] resize-none rounded-md border border-border bg-[#ffffff] px-3 py-2 text-sm font-semibold leading-5 text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Paste the vacancy description..."
            />
          </label>
        </div>

        <div className="mt-5 flex shrink-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p
            className={cn(
              "text-xs font-semibold",
              error ? "text-[#fa5d00]" : "text-muted",
            )}
            role={error ? "alert" : undefined}
          >
            {error ||
              "Title, company, location, link, and description are required."}
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-5 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              type="button"
              className="h-10 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-5 text-[13px] text-foreground"
              disabled={isSaving || !canSave}
              onClick={onSave}
            >
              <Save className="h-4 w-4" />
              {isSaving ? "Saving application..." : "Save application"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

type ApplicationNotesDialogProps = {
  application: TrackedApplication;
  notes: string;
  onChange: (notes: string) => void;
  onClear: () => void;
  onClose: () => void;
  onSave: () => void;
};

export function ApplicationNotesDialog({
  application,
  notes,
  onChange,
  onClear,
  onClose,
  onSave,
}: ApplicationNotesDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="application-notes-dialog-title"
        className="panel w-full max-w-[540px] border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] 2xl:p-5"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2
              id="application-notes-dialog-title"
              className="text-[22px] font-bold leading-tight text-foreground"
            >
              Edit notes
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              {application.job.company} • {application.job.title}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close notes editor"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <textarea
          value={notes}
          onChange={(event) => onChange(event.target.value)}
          className="mt-5 min-h-[150px] w-full resize-none rounded-md border border-border bg-[#ffffff] px-3 py-2 text-sm font-semibold leading-5 text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
          placeholder="Add notes about this application..."
        />

        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <Button
            type="button"
            variant="ghost"
            className="h-10 rounded-md border border-border bg-transparent px-5 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
            onClick={onClear}
          >
            Clear
          </Button>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-5 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              type="button"
              className="h-10 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-5 text-[13px] text-foreground"
              onClick={onSave}
            >
              <Save className="h-4 w-4" />
              Save notes
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

type ApplicationEventDialogProps = {
  application: TrackedApplication;
  draft: ApplicationEventDraft;
  onChange: <Field extends keyof ApplicationEventDraft>(
    field: Field,
    value: ApplicationEventDraft[Field],
  ) => void;
  onClose: () => void;
  onSave: () => void;
};

export function ApplicationEventDialog({
  application,
  draft,
  onChange,
  onClose,
  onSave,
}: ApplicationEventDialogProps) {
  const isEditing = Boolean(draft.id);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="application-event-dialog-title"
        className="panel w-full max-w-[620px] border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] 2xl:p-5"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2
              id="application-event-dialog-title"
              className="text-[22px] font-bold leading-tight text-foreground"
            >
              {isEditing ? "Edit event" : "Schedule event"}
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              {application.job.company} • {application.job.title}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close schedule event"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="mt-5 grid max-h-[72vh] gap-4 overflow-y-auto pr-1 md:grid-cols-2">
          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Event type</span>
            <select
              value={draft.type}
              onChange={(event) =>
                onChange("type", event.target.value as ApplicationEventType)
              }
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
            >
              {applicationEventTypes.map((item) => (
                <option key={item.type} value={item.type}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Status</span>
            <select
              value={draft.status}
              onChange={(event) =>
                onChange("status", event.target.value as ApplicationEventStatus)
              }
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
            >
              {applicationEventStatuses.map((item) => (
                <option key={item.status} value={item.status}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Title</span>
            <input
              value={draft.title}
              onChange={(event) => onChange("title", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Phone screen with recruiter"
            />
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Outcome</span>
            <select
              value={draft.outcome}
              onChange={(event) =>
                onChange(
                  "outcome",
                  event.target.value as ApplicationEventOutcome | "",
                )
              }
              disabled={draft.status !== "completed"}
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70 disabled:cursor-not-allowed disabled:opacity-45"
            >
              <option value="">No outcome yet</option>
              {applicationEventOutcomes.map((item) => (
                <option key={item.outcome} value={item.outcome}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">
              Date and time
            </span>
            <input
              type="datetime-local"
              value={draft.startsAt}
              onChange={(event) => onChange("startsAt", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
            />
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Duration</span>
            <select
              value={draft.durationMinutes}
              onChange={(event) =>
                onChange("durationMinutes", event.target.value)
              }
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
            >
              <option value="15">15 minutes</option>
              <option value="30">30 minutes</option>
              <option value="45">45 minutes</option>
              <option value="60">1 hour</option>
              <option value="90">1.5 hours</option>
            </select>
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Timezone</span>
            <input
              value={draft.timezone}
              onChange={(event) => onChange("timezone", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Europe/Zurich"
            />
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">
              Location or link
            </span>
            <input
              value={draft.location}
              onChange={(event) => onChange("location", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Zoom, Google Meet, phone, office"
            />
          </label>

          <label className="grid gap-2 md:col-span-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Notes</span>
            <textarea
              value={draft.notes}
              onChange={(event) => onChange("notes", event.target.value)}
              className="min-h-[88px] resize-none rounded-md border border-border bg-[#ffffff] px-3 py-2 text-sm font-semibold leading-5 text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Recruiter name, prep notes, agenda, questions..."
            />
          </label>
        </div>

        <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs font-semibold text-muted">
            Synced to backend with local fallback.
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-5 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              type="button"
              className="h-10 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-5 text-[13px] text-foreground"
              disabled={!draft.title.trim() || !draft.startsAt}
              onClick={onSave}
            >
              <Save className="h-4 w-4" />
              {isEditing ? "Update event" : "Save event"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
export function ApplicationAiInfoDialog({
  application,
  isAnalyzing,
  onClose,
}: {
  application: TrackedApplication;
  isAnalyzing: boolean;
  onClose: () => void;
}) {
  const job = application.job;
  const breakdownItems = getAiMatchBreakdownItems(job);
  const reasons = job.aiMatch?.reasons.length
    ? job.aiMatch.reasons
    : ["No AI match reasons have been calculated yet."];
  const gaps = job.aiMatch?.gaps.length
    ? job.aiMatch.gaps
    : ["No AI match gaps have been calculated yet."];
  const recommendations = buildRecommendationPlan(job).slice(0, 5);
  const sourceDisplay = isAnalyzing
    ? "Analyzing..."
    : getAiMatchSourceDisplay(job);
  const rawExplanation = buildAiMatchRawExplanation(job);
  const signalStats = [
    { label: "Skills", value: job.skills.length.toString() },
    { label: "Requirements", value: job.requirements.length.toString() },
    {
      label: "Responsibilities",
      value: job.responsibilities.length.toString(),
    },
    { label: "Documents", value: application.documents.length.toString() },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[920px] flex-col overflow-hidden border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] 2xl:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <JobRoleIcon job={job} compact />
            <div className="min-w-0">
              <h2 className="text-[22px] font-bold leading-tight text-foreground 2xl:text-[24px]">
                AI application info
              </h2>
              <p className="mt-1 truncate text-sm font-medium text-muted">
                {job.title} at {job.company}
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close AI info"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto pr-1">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 2xl:gap-3">
            <InfoStat
              label="AI match"
              value={isAnalyzing ? "Analyzing..." : formatMatchValue(job)}
            />
            <InfoStat
              label="Source"
              value={sourceDisplay}
              title={job.aiMatch?.providerError}
            />
            <InfoStat
              label="Confidence"
              value={formatConfidence(job.aiMatch?.confidence)}
            />
            <InfoStat
              label="Updated"
              value={formatAiMatchTimestamp(job.aiMatch?.updatedAt)}
            />
          </div>

          {isAnalyzing ? (
            <div className="mt-4 rounded-md border border-accent/35 bg-accent/10 px-3 py-2 text-[13px] font-semibold text-accent 2xl:text-sm">
              AI analysis is running. This panel will update automatically when
              the match result is saved.
            </div>
          ) : null}

          <section className="mt-4 rounded-md border border-border bg-[#fff8f1] p-3 2xl:p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-sm font-bold text-foreground 2xl:text-base">
                Score breakdown
              </h3>
              <span className="rounded-md border border-success/30 bg-success/12 px-2 py-1 text-xs font-bold text-success">
                {isAnalyzing ? "Analyzing..." : formatMatchValue(job)}
              </span>
            </div>
            <div className="mt-3 space-y-2.5">
              {breakdownItems.map((item) => (
                <div
                  key={item.key}
                  className="grid grid-cols-[minmax(92px,0.34fr)_minmax(0,1fr)_54px] items-center gap-3"
                >
                  <span className="text-[12px] font-semibold text-muted 2xl:text-sm">
                    {item.label}
                  </span>
                  <div className="h-2 rounded-full bg-[#fff8f1]">
                    <div
                      className="h-full rounded-full bg-success"
                      style={{ width: `${item.progress}%` }}
                    />
                  </div>
                  <span className="text-right text-[12px] font-bold text-[#1d1e1c] 2xl:text-sm">
                    {item.value}/{item.max}
                  </span>
                </div>
              ))}
            </div>
          </section>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <section className="rounded-md border border-border bg-[#fff8f1] p-3 2xl:p-4">
              <h3 className="text-sm font-bold text-foreground 2xl:text-base">
                Reasons
              </h3>
              <ul className="mt-2.5 space-y-2 text-[13px] leading-5 text-muted 2xl:text-sm">
                {reasons.map((item) => (
                  <li key={item} className="flex gap-2">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                    {item}
                  </li>
                ))}
              </ul>
            </section>

            <section className="rounded-md border border-border bg-[#fff8f1] p-3 2xl:p-4">
              <h3 className="text-sm font-bold text-foreground 2xl:text-base">
                Gaps
              </h3>
              <ul className="mt-2.5 space-y-2 text-[13px] leading-5 text-muted 2xl:text-sm">
                {gaps.map((item) => (
                  <li key={item} className="flex gap-2">
                    <CircleDot className="mt-0.5 h-4 w-4 shrink-0 text-[#fa5d00]" />
                    {item}
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <section className="mt-4 rounded-md border border-border bg-[#fff8f1] p-3 2xl:p-4">
            <h3 className="text-sm font-bold text-foreground 2xl:text-base">
              Extracted vacancy signals
            </h3>
            <div className="mt-3 grid gap-2 sm:grid-cols-4">
              {signalStats.map((item) => (
                <InfoStat
                  key={item.label}
                  label={item.label}
                  value={item.value}
                />
              ))}
            </div>
            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              <div>
                <h4 className="text-[12px] font-bold text-[#1d1e1c] 2xl:text-sm">
                  Skills
                </h4>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {job.skills.map((skill) => (
                    <span
                      key={skill}
                      className="rounded-md border border-border bg-[#fff8f1] px-2 py-1 text-[11px] font-bold text-muted"
                    >
                      {skill}
                    </span>
                  ))}
                </div>
              </div>
              <div>
                <h4 className="text-[12px] font-bold text-[#1d1e1c] 2xl:text-sm">
                  Requirements
                </h4>
                <ul className="mt-2 space-y-1.5 text-[12px] leading-5 text-muted 2xl:text-[13px]">
                  {job.requirements.slice(0, 5).map((item) => (
                    <li key={item} className="flex gap-2">
                      <CircleDot className="mt-1 h-3 w-3 shrink-0 text-accent" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h4 className="text-[12px] font-bold text-[#1d1e1c] 2xl:text-sm">
                  Responsibilities
                </h4>
                <ul className="mt-2 space-y-1.5 text-[12px] leading-5 text-muted 2xl:text-[13px]">
                  {job.responsibilities.slice(0, 5).map((item) => (
                    <li key={item} className="flex gap-2">
                      <CircleDot className="mt-1 h-3 w-3 shrink-0 text-accent" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </section>

          <section className="mt-4 rounded-md border border-border bg-[#fff8f1] p-3 2xl:p-4">
            <h3 className="text-sm font-bold text-foreground 2xl:text-base">
              Evidence-backed recommendations
            </h3>
            <div className="mt-2 divide-y divide-border">
              {recommendations.length ? (
                recommendations.map((recommendation) => (
                  <div
                    key={`${recommendation.text}-${recommendation.gain}`}
                    className="grid gap-1.5 py-2.5 text-[13px] leading-5 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1fr)_auto] sm:items-start 2xl:text-sm"
                  >
                    <div>
                      <p className="font-bold text-[#1d1e1c]">
                        {recommendation.text}
                      </p>
                      <p className="mt-0.5 text-muted">
                        {recommendation.action}
                      </p>
                    </div>
                    <p className="text-muted">{recommendation.why}</p>
                    <p className="font-bold text-success sm:text-right">
                      {recommendation.gain}
                    </p>
                  </div>
                ))
              ) : (
                <p className="py-2.5 text-[13px] leading-5 text-muted 2xl:text-sm">
                  No source-backed recommendations are available.
                </p>
              )}
            </div>
          </section>

          <section className="mt-4 rounded-md border border-border bg-[#fff8f1] p-3 2xl:p-4">
            <h3 className="text-sm font-bold text-foreground 2xl:text-base">
              Explanation
            </h3>
            <p className="mt-2 text-[13px] leading-5 text-muted 2xl:text-sm 2xl:leading-6">
              {rawExplanation}
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
