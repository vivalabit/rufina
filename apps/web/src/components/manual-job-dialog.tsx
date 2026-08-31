"use client";

import { Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ManualJobDraft } from "@/features/jobs/model/types";

type ManualJobDialogProps = {
  draft: ManualJobDraft;
  onChange: <Field extends keyof ManualJobDraft>(
    field: Field,
    value: ManualJobDraft[Field],
  ) => void;
  onClose: () => void;
  onSave: () => void;
};

export function ManualJobDialog({
  draft,
  onChange,
  onClose,
  onSave,
}: ManualJobDialogProps) {
  const canSave = Boolean(
    draft.title.trim() && draft.company.trim() && draft.overview.trim(),
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="manual-job-dialog-title"
        className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[780px] flex-col overflow-hidden border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] 2xl:p-5"
      >
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 id="manual-job-dialog-title" className="text-[22px] font-bold leading-tight text-foreground">
              Add vacancy
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              Paste a vacancy to save it in Jobs and analyze it against your profile.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close manual vacancy"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 grid min-h-0 flex-1 gap-4 overflow-y-auto pr-1 md:grid-cols-2">
          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Role title *</span>
            <input
              autoFocus
              value={draft.title}
              onChange={(event) => onChange("title", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Senior Product Designer"
            />
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Company *</span>
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
            <span className="text-xs font-bold text-[#1d1e1c]">Job posting URL</span>
            <input
              type="url"
              value={draft.applyUrl}
              onChange={(event) => onChange("applyUrl", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="https://company.com/careers/role"
            />
          </label>

          <label className="grid gap-2 md:col-span-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Vacancy description *</span>
            <textarea
              value={draft.overview}
              onChange={(event) => onChange("overview", event.target.value)}
              className="min-h-[260px] resize-y rounded-md border border-border bg-[#ffffff] px-3 py-2 text-sm font-semibold leading-5 text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Paste the full vacancy description, including responsibilities and requirements..."
            />
          </label>
        </div>

        <div className="mt-5 flex shrink-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs font-semibold text-muted">
            Role, company, and description are required. Analysis starts automatically.
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
              disabled={!canSave}
              onClick={onSave}
            >
              <Sparkles className="h-4 w-4" />
              Add and analyze
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
