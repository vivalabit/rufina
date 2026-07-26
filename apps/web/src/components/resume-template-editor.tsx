"use client";

import {
  Copy,
  Download,
  LayoutPanelLeft,
  LoaderCircle,
  Save,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import type {
  ResumeTemplate,
  ResumeTemplateDensity,
  ResumeTemplateDesignTokens,
  ResumeTemplateDraft,
  ResumeTemplateKind,
} from "@/lib/resume-templates";
import { cn } from "@/lib/utils";

export type {
  ResumeTemplate,
  ResumeTemplateDensity,
  ResumeTemplateDesignTokens,
  ResumeTemplateDraft,
  ResumeTemplateKind,
  ResumeTemplatePageMargins,
} from "@/lib/resume-templates";

type ResumeTemplateEditorProps = {
  draft: ResumeTemplateDraft;
  sourceKind: ResumeTemplateKind;
  layout: ResumeTemplate["layout"];
  isDirty: boolean;
  isSaving: boolean;
  isDuplicating: boolean;
  isDeleting: boolean;
  isExporting: boolean;
  onChange: (draft: ResumeTemplateDraft) => void;
  onSave: () => void;
  onDuplicate?: () => void;
  onDelete?: () => void;
  onExport?: () => void;
};

const fontOptions = [
  "Inter",
  "Arial",
  "Georgia",
  "Source Sans 3",
  "Times New Roman",
] as const;

const densityOptions: Array<{
  value: ResumeTemplateDensity;
  label: string;
}> = [
  { value: "compact", label: "Compact" },
  { value: "standard", label: "Standard" },
  { value: "comfortable", label: "Comfortable" },
];

const headingOptions = [
  { value: "plain", label: "Plain" },
  { value: "underlined", label: "Underlined" },
  { value: "accent-rule", label: "Accent rule" },
] as const;

const skillsOptions = [
  { value: "inline", label: "Inline" },
  { value: "list", label: "List" },
  { value: "pills", label: "Pills" },
] as const;

const sidebarSectionOptions = [
  { value: "summary", label: "Summary" },
  { value: "skills", label: "Skills" },
  { value: "education", label: "Education" },
  { value: "projects", label: "Projects" },
  { value: "certifications", label: "Certifications" },
  { value: "languages", label: "Languages" },
  { value: "additional", label: "Additional" },
] as const;

export function ResumeTemplateEditor({
  draft,
  sourceKind,
  layout,
  isDirty,
  isSaving,
  isDuplicating,
  isDeleting,
  isExporting,
  onChange,
  onSave,
  onDuplicate,
  onDelete,
  onExport,
}: ResumeTemplateEditorProps) {
  const isTwoColumn = layout === "two_column";
  const isBusy = isSaving || isDuplicating || isDeleting || isExporting;
  const hasValidAccentColor = /^#[0-9A-Fa-f]{6}$/.test(
    draft.designJson.accentColor,
  );

  function updateDraft(
    update: Partial<Omit<ResumeTemplateDraft, "designJson">> & {
      designJson?: Partial<ResumeTemplateDesignTokens>;
    },
  ) {
    onChange({
      ...draft,
      ...update,
      designJson: {
        ...draft.designJson,
        ...update.designJson,
      },
    });
  }

  function toggleSidebarSection(section: string) {
    const sections = draft.designJson.sidebarSections;
    updateDraft({
      designJson: {
        sidebarSections: sections.includes(section)
          ? sections.filter((item) => item !== section)
          : [...sections, section],
      },
    });
  }

  return (
    <div className="min-w-0">
      <div className="flex flex-col gap-3 border-b border-border px-4 py-4 sm:flex-row sm:items-start sm:justify-between 2xl:px-5">
        <div className="min-w-0 flex-1">
          <label
            htmlFor="resume-template-name"
            className="text-[11px] font-bold uppercase tracking-[0.14em] text-muted"
          >
            Template name
          </label>
          <input
            id="resume-template-name"
            value={draft.name}
            maxLength={240}
            onChange={(event) => updateDraft({ name: event.target.value })}
            className="mt-1.5 h-10 w-full rounded-md border border-border bg-[#0c1118] px-3 text-sm font-semibold text-white outline-none transition focus:border-accent/70 focus:ring-2 focus:ring-accent/20"
          />
          <p className="mt-1.5 text-xs text-muted">
            {sourceKind === "bundled"
              ? "A personal copy will be created when you save."
              : isDirty
                ? "You have unsaved changes."
                : "All changes are saved."}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2 sm:pt-5">
          {sourceKind === "custom" && onExport ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={isBusy}
              onClick={onExport}
              aria-label="Export template"
              className="border border-border bg-white/[0.025]"
            >
              {isExporting ? (
                <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Download className="h-3.5 w-3.5" />
              )}
              Export
            </Button>
          ) : null}
          {sourceKind === "custom" && onDuplicate ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={isBusy}
              onClick={onDuplicate}
              aria-label="Duplicate template"
              className="border border-border bg-white/[0.025]"
            >
              {isDuplicating ? (
                <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
              Duplicate
            </Button>
          ) : null}
          {sourceKind === "custom" && onDelete ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={isBusy}
              onClick={onDelete}
              aria-label="Delete template"
              className="border border-red-400/20 text-red-300 hover:bg-red-400/10 hover:text-red-200"
            >
              {isDeleting ? (
                <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Trash2 className="h-3.5 w-3.5" />
              )}
              Delete
            </Button>
          ) : null}
          <Button
            type="button"
            size="sm"
            disabled={
              isBusy ||
              !draft.name.trim() ||
              !hasValidAccentColor ||
              (sourceKind === "custom" && !isDirty)
            }
            onClick={onSave}
          >
            {isSaving ? (
              <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            {sourceKind === "bundled" ? "Create template" : "Save"}
          </Button>
        </div>
      </div>

      <div className="job-scroll max-h-[680px] space-y-5 overflow-y-auto p-4 2xl:p-5">
        <fieldset>
          <legend className="text-xs font-bold uppercase tracking-[0.12em] text-white">
            Color & typography
          </legend>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="text-xs font-semibold text-muted">
                Accent color
              </span>
              <span className="mt-1.5 flex h-10 items-center gap-2 rounded-md border border-border bg-[#0c1118] px-2">
                <input
                  type="color"
                  aria-label="Accent color"
                  value={draft.designJson.accentColor}
                  onChange={(event) =>
                    updateDraft({
                      designJson: { accentColor: event.target.value },
                    })
                  }
                  className="h-7 w-9 cursor-pointer border-0 bg-transparent p-0"
                />
                <input
                  aria-label="Accent color hex"
                  value={draft.designJson.accentColor}
                  maxLength={7}
                  aria-invalid={!hasValidAccentColor}
                  onChange={(event) =>
                    updateDraft({
                      designJson: { accentColor: event.target.value },
                    })
                  }
                  className="min-w-0 flex-1 bg-transparent font-mono text-xs uppercase text-white outline-none"
                />
              </span>
              {!hasValidAccentColor ? (
                <span className="mt-1 block text-[11px] text-red-300">
                  Use a six-digit hex color, for example #8A1538.
                </span>
              ) : null}
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-muted">
                Font family
              </span>
              <select
                aria-label="Font family"
                value={draft.designJson.fontFamily}
                onChange={(event) =>
                  updateDraft({
                    designJson: { fontFamily: event.target.value },
                  })
                }
                className="mt-1.5 h-10 w-full rounded-md border border-border bg-[#0c1118] px-3 text-sm text-white outline-none focus:border-accent/70"
              >
                {fontOptions.map((font) => (
                  <option key={font} value={font}>
                    {font}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </fieldset>

        <fieldset>
          <legend className="text-xs font-bold uppercase tracking-[0.12em] text-white">
            Density
          </legend>
          <div className="mt-3 grid grid-cols-3 gap-2">
            {densityOptions.map((option) => (
              <OptionButton
                key={option.value}
                active={draft.designJson.density === option.value}
                onClick={() =>
                  updateDraft({ designJson: { density: option.value } })
                }
              >
                {option.label}
              </OptionButton>
            ))}
          </div>
        </fieldset>

        <div className="grid gap-5 sm:grid-cols-2">
          <fieldset>
            <legend className="text-xs font-bold uppercase tracking-[0.12em] text-white">
              Headings
            </legend>
            <div className="mt-3 space-y-2">
              {headingOptions.map((option) => (
                <OptionButton
                  key={option.value}
                  active={draft.designJson.headingStyle === option.value}
                  onClick={() =>
                    updateDraft({
                      designJson: { headingStyle: option.value },
                    })
                  }
                  fullWidth
                >
                  {option.label}
                </OptionButton>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend className="text-xs font-bold uppercase tracking-[0.12em] text-white">
              Skills
            </legend>
            <div className="mt-3 space-y-2">
              {skillsOptions.map((option) => (
                <OptionButton
                  key={option.value}
                  active={draft.designJson.skillsStyle === option.value}
                  onClick={() =>
                    updateDraft({
                      designJson: { skillsStyle: option.value },
                    })
                  }
                  fullWidth
                >
                  {option.label}
                </OptionButton>
              ))}
            </div>
          </fieldset>
        </div>

        <fieldset
          className={cn(
            "rounded-lg border border-border bg-white/[0.015] p-3.5",
            !isTwoColumn && "opacity-60",
          )}
        >
          <legend className="px-1 text-xs font-bold uppercase tracking-[0.12em] text-white">
            <span className="inline-flex items-center gap-2">
              <LayoutPanelLeft className="h-4 w-4 text-accent" />
              Sidebar
            </span>
          </legend>
          <label className="mt-1 block">
            <span className="flex items-center justify-between text-xs font-semibold text-muted">
              Width
              <span className="font-mono text-white">
                {isTwoColumn
                  ? `${Math.round(draft.designJson.sidebarWidth)}%`
                  : "Not applicable"}
              </span>
            </span>
            <input
              type="range"
              aria-label="Sidebar width"
              min={22}
              max={42}
              step={1}
              value={
                isTwoColumn
                  ? Math.max(22, draft.designJson.sidebarWidth)
                  : 22
              }
              disabled={!isTwoColumn}
              onChange={(event) =>
                updateDraft({
                  designJson: {
                    sidebarWidth: Number(event.target.value),
                  },
                })
              }
              className="mt-2 w-full accent-[#ff5a00]"
            />
          </label>
          <div className="mt-3 grid grid-cols-2 gap-2">
            {sidebarSectionOptions.map((section) => {
              const checked =
                draft.designJson.sidebarSections.includes(section.value);
              return (
                <label
                  key={section.value}
                  className={cn(
                    "flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-2 text-xs font-semibold transition",
                    checked
                      ? "border-accent/45 bg-accent/[0.09] text-white"
                      : "border-border bg-[#0c1118] text-muted",
                    !isTwoColumn && "cursor-not-allowed",
                  )}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!isTwoColumn}
                    onChange={() => toggleSidebarSection(section.value)}
                    className="accent-[#ff5a00]"
                  />
                  {section.label}
                </label>
              );
            })}
          </div>
          {!isTwoColumn ? (
            <p className="mt-3 text-xs text-muted">
              Sidebar controls are available for two-column templates.
            </p>
          ) : null}
        </fieldset>
      </div>
    </div>
  );
}

function OptionButton({
  active,
  onClick,
  fullWidth = false,
  children,
}: {
  active: boolean;
  onClick: () => void;
  fullWidth?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "h-9 rounded-md border px-2 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        fullWidth && "w-full text-left",
        active
          ? "border-accent/55 bg-accent/[0.11] text-white"
          : "border-border bg-[#0c1118] text-muted hover:bg-white/[0.045] hover:text-white",
      )}
    >
      {children}
    </button>
  );
}
