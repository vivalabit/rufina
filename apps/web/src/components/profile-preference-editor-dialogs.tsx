"use client";

import { Plus, Save, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  preferenceListLabels,
  preferenceOptions,
  preferenceSuggestions,
  suggestedDealbreakers,
} from "@/features/profile/model/defaults";
import { suggestedSkills } from "@/features/profile/model/suggested-skills";
import type {
  JobPreferences,
  PreferenceAnyField,
  PreferenceInputs,
  PreferenceListField,
  PreferenceToggleField,
} from "@/shared/types/profile";
import { cn } from "@/lib/utils";

export function SkillsEditorDialog({
  skills,
  skillInput,
  status,
  message,
  onSkillInputChange,
  onAddSkill,
  onRemoveSkill,
  onClose,
  onSave,
}: {
  skills: string[];
  skillInput: string;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  onSkillInputChange: (value: string) => void;
  onAddSkill: (skill: string) => void;
  onRemoveSkill: (skill: string) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const normalizedQuery = skillInput.trim().toLowerCase();
  const availableSuggestions = suggestedSkills.filter(
    (suggestion) =>
      !skills.some(
        (skill) => skill.toLowerCase() === suggestion.toLowerCase(),
      ) &&
      (!normalizedQuery || suggestion.toLowerCase().includes(normalizedQuery)),
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[720px] flex-col overflow-hidden border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-foreground 2xl:text-[24px]">
              Edit Skills
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              Add skills one at a time, similar to LinkedIn.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close skills editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <form
            className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]"
            onSubmit={(event) => {
              event.preventDefault();
              onAddSkill(skillInput);
            }}
          >
            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">Skill</span>
              <input
                value={skillInput}
                onChange={(event) => onSkillInputChange(event.target.value)}
                placeholder="e.g. Python, FastAPI, Docker"
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
              <span className="text-xs font-medium text-muted">
                Type to search suggestions, then click a chip or press Add.
              </span>
            </label>
            <Button
              type="submit"
              variant="ghost"
              className="mt-6 h-10 rounded-md border border-border bg-[#fff8f1] px-4 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
            >
              <Plus className="h-4 w-4" />
              Add
            </Button>
          </form>

          <div className="mt-5">
            <h3 className="text-sm font-bold text-foreground">
              Selected skills
            </h3>
            {skills.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {skills.map((skill) => (
                  <span
                    key={skill}
                    className="inline-flex min-h-8 items-center gap-2 rounded-md border border-border bg-[#fff8f1] px-2.5 text-xs font-semibold text-[#1d1e1c]"
                  >
                    {skill}
                    <button
                      type="button"
                      aria-label={`Remove ${skill}`}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
                      onClick={() => onRemoveSkill(skill)}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </span>
                ))}
              </div>
            ) : (
              <p className="mt-3 rounded-md border border-dashed border-border bg-[#fff8f1] p-3 text-sm text-muted">
                No skills selected yet.
              </p>
            )}
          </div>

          <div className="mt-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-bold text-foreground">
                Suggested skills
              </h3>
              <p className="text-xs font-medium text-muted">
                {normalizedQuery
                  ? `${availableSuggestions.length} matches`
                  : `${availableSuggestions.length} available`}
              </p>
            </div>
            {availableSuggestions.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {availableSuggestions.map((skill) => (
                  <button
                    key={skill}
                    type="button"
                    className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-border bg-[#fff8f1] px-2.5 text-xs font-semibold text-[#1d1e1c] transition hover:border-accent/60 hover:bg-accent/10 hover:text-foreground"
                    onClick={() => onAddSkill(skill)}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    {skill}
                  </button>
                ))}
              </div>
            ) : (
              <p className="mt-3 rounded-md border border-dashed border-border bg-[#fff8f1] p-3 text-sm text-muted">
                No suggestions match this search. Press Add to save it as a
                custom skill.
              </p>
            )}
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p
            className={cn(
              "text-sm font-semibold",
              status === "error" ? "text-[#fa5d00]" : "text-muted",
            )}
          >
            {message || `${skills.length} skills selected`}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-7 text-[13px] text-foreground shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#e95300] hover:to-[#e95300]"
              disabled={status === "loading"}
              onClick={onSave}
            >
              <Save className="h-4 w-4" />
              {status === "loading" ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function DealbreakersEditorDialog({
  dealbreakers,
  dealbreakerInput,
  status,
  message,
  onDealbreakerInputChange,
  onAddDealbreaker,
  onRemoveDealbreaker,
  onClearDealbreakers,
  onClose,
  onSave,
}: {
  dealbreakers: string[];
  dealbreakerInput: string;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  onDealbreakerInputChange: (value: string) => void;
  onAddDealbreaker: (dealbreaker: string) => void;
  onRemoveDealbreaker: (dealbreaker: string) => void;
  onClearDealbreakers: () => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const normalizedQuery = dealbreakerInput.trim().toLowerCase();
  const availableSuggestions = suggestedDealbreakers.filter(
    (suggestion) =>
      !dealbreakers.some(
        (dealbreaker) => dealbreaker.toLowerCase() === suggestion.toLowerCase(),
      ) &&
      (!normalizedQuery || suggestion.toLowerCase().includes(normalizedQuery)),
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[720px] flex-col overflow-hidden border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-foreground 2xl:text-[24px]">
              Edit Dealbreakers
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              Hard limits that should rule out a job match.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close dealbreakers editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <form
            className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]"
            onSubmit={(event) => {
              event.preventDefault();
              onAddDealbreaker(dealbreakerInput);
            }}
          >
            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Dealbreaker
              </span>
              <input
                value={dealbreakerInput}
                onChange={(event) =>
                  onDealbreakerInputChange(event.target.value)
                }
                placeholder="e.g. No onsite-only roles"
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
              <span className="text-xs font-medium text-muted">
                Leave the list empty when you have no hard limits.
              </span>
            </label>
            <Button
              type="submit"
              variant="ghost"
              className="mt-6 h-10 rounded-md border border-border bg-[#fff8f1] px-4 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
            >
              <Plus className="h-4 w-4" />
              Add
            </Button>
          </form>

          <div className="mt-5 rounded-md border border-border bg-[#fff8f1] p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-bold text-foreground">
                Current hard limits
              </h3>
              <button
                type="button"
                className="inline-flex min-h-7 items-center rounded-md border border-border bg-[#fff8f1] px-2.5 text-[11px] font-bold text-muted transition hover:border-accent/45 hover:bg-accent/10 hover:text-[#1d1e1c]"
                onClick={onClearDealbreakers}
              >
                No dealbreakers
              </button>
            </div>
            {dealbreakers.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {dealbreakers.map((dealbreaker) => (
                  <span
                    key={dealbreaker}
                    className="inline-flex min-h-8 items-center gap-2 rounded-md border border-border bg-[#fff8f1] px-2.5 text-xs font-semibold text-[#1d1e1c]"
                  >
                    {dealbreaker}
                    <button
                      type="button"
                      aria-label={`Remove ${dealbreaker}`}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
                      onClick={() => onRemoveDealbreaker(dealbreaker)}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </span>
                ))}
              </div>
            ) : (
              <p className="mt-3 rounded-md border border-dashed border-border bg-[#fff8f1] p-3 text-sm text-muted">
                No hard limits are set. Save this empty list if every condition
                is flexible.
              </p>
            )}
          </div>

          <div className="mt-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-bold text-foreground">
                Suggested dealbreakers
              </h3>
              <p className="text-xs font-medium text-muted">
                {normalizedQuery
                  ? `${availableSuggestions.length} matches`
                  : `${availableSuggestions.length} available`}
              </p>
            </div>
            {availableSuggestions.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {availableSuggestions.map((dealbreaker) => (
                  <button
                    key={dealbreaker}
                    type="button"
                    className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-border bg-[#fff8f1] px-2.5 text-xs font-semibold text-[#1d1e1c] transition hover:border-accent/60 hover:bg-accent/10 hover:text-foreground"
                    onClick={() => onAddDealbreaker(dealbreaker)}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    {dealbreaker}
                  </button>
                ))}
              </div>
            ) : (
              <p className="mt-3 rounded-md border border-dashed border-border bg-[#fff8f1] p-3 text-sm text-muted">
                No suggestions match this search. Press Add to save it as a
                custom hard limit.
              </p>
            )}
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p
            className={cn(
              "text-sm font-semibold",
              status === "error" ? "text-[#fa5d00]" : "text-muted",
            )}
          >
            {message ||
              (dealbreakers.length === 0
                ? "No dealbreakers set"
                : `${dealbreakers.length} dealbreakers selected`)}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-7 text-[13px] text-foreground shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#e95300] hover:to-[#e95300]"
              disabled={status === "loading"}
              onClick={onSave}
            >
              <Save className="h-4 w-4" />
              {status === "loading" ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function AdditionalNotesEditorDialog({
  notes,
  status,
  message,
  onChange,
  onClear,
  onClose,
  onSave,
}: {
  notes: string;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  onChange: (value: string) => void;
  onClear: () => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[720px] flex-col overflow-hidden border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-foreground 2xl:text-[24px]">
              Edit Additional Notes
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              Extra context for matching, applications, or future automation.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close notes editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#1d1e1c]">Notes</span>
            <textarea
              value={notes}
              onChange={(event) => onChange(event.target.value)}
              placeholder="Availability, motivation, personal positioning, application context, or anything that does not fit elsewhere..."
              rows={8}
              className="min-h-[220px] resize-none rounded-md border border-border bg-[#ffffff] px-3 py-2.5 text-sm font-semibold leading-5 text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
            />
            <span className="text-xs font-medium text-muted">
              Leave empty if there is no extra context to add.
            </span>
          </label>
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              className="inline-flex min-h-8 items-center rounded-md border border-border bg-[#fff8f1] px-3 text-xs font-bold text-muted transition hover:border-accent/45 hover:bg-accent/10 hover:text-[#1d1e1c]"
              onClick={onClear}
            >
              Clear notes
            </button>
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p
            className={cn(
              "text-sm font-semibold",
              status === "error" ? "text-[#fa5d00]" : "text-muted",
            )}
          >
            {message || (notes.trim() ? "Notes ready to save" : "No notes set")}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-7 text-[13px] text-foreground shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#e95300] hover:to-[#e95300]"
              disabled={status === "loading"}
              onClick={onSave}
            >
              <Save className="h-4 w-4" />
              {status === "loading" ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function PreferencesEditorDialog({
  preferences,
  inputs,
  status,
  message,
  onChange,
  onInputChange,
  onAddListItem,
  onRemoveListItem,
  onToggleOption,
  onSetAny,
  onClose,
  onSave,
}: {
  preferences: JobPreferences;
  inputs: PreferenceInputs;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  onChange: <Field extends keyof JobPreferences>(
    field: Field,
    value: JobPreferences[Field],
  ) => void;
  onInputChange: (field: PreferenceListField, value: string) => void;
  onAddListItem: (field: PreferenceListField) => void;
  onRemoveListItem: (field: PreferenceListField, value: string) => void;
  onToggleOption: (field: PreferenceToggleField, value: string) => void;
  onSetAny: (field: PreferenceAnyField) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[880px] flex-col overflow-hidden border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-foreground 2xl:text-[24px]">
              Edit Job Preferences
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              Define the roles and conditions that should guide search,
              matching, and recommendations.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close preferences editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <div className="grid gap-4">
            {(Object.keys(preferenceListLabels) as PreferenceListField[]).map(
              (field) => (
                <PreferenceListEditor
                  key={field}
                  field={field}
                  values={preferences[field]}
                  inputValue={inputs[field]}
                  isAny={preferences.no_preference.includes(field)}
                  onInputChange={onInputChange}
                  onAdd={onAddListItem}
                  onRemove={onRemoveListItem}
                  onSetAny={onSetAny}
                />
              ),
            )}

            <PreferenceToggleGroup
              title="Seniority"
              field="seniority"
              options={preferenceOptions.seniority}
              selectedValues={preferences.seniority}
              isAny={preferences.no_preference.includes("seniority")}
              onToggle={onToggleOption}
              onSetAny={onSetAny}
            />
            <PreferenceToggleGroup
              title="Work format"
              field="work_formats"
              options={preferenceOptions.work_formats}
              selectedValues={preferences.work_formats}
              isAny={preferences.no_preference.includes("work_formats")}
              onToggle={onToggleOption}
              onSetAny={onSetAny}
            />
            <PreferenceToggleGroup
              title="Employment type"
              field="employment_types"
              options={preferenceOptions.employment_types}
              selectedValues={preferences.employment_types}
              isAny={preferences.no_preference.includes("employment_types")}
              onToggle={onToggleOption}
              onSetAny={onSetAny}
            />
            <PreferenceToggleGroup
              title="Company size"
              field="company_sizes"
              options={preferenceOptions.company_sizes}
              selectedValues={preferences.company_sizes}
              isAny={preferences.no_preference.includes("company_sizes")}
              onToggle={onToggleOption}
              onSetAny={onSetAny}
            />
            <PreferenceToggleGroup
              title="Search priority"
              field="priorities"
              options={preferenceOptions.priorities}
              selectedValues={preferences.priorities}
              isAny={preferences.no_preference.includes("priorities")}
              onToggle={onToggleOption}
              onSetAny={onSetAny}
            />

            <div className="grid gap-4 rounded-md border border-border bg-[#fff8f1] p-3 sm:grid-cols-[130px_minmax(0,1fr)]">
              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#1d1e1c]">
                  Currency
                </span>
                <select
                  value={preferences.salary_currency}
                  onChange={(event) =>
                    onChange("salary_currency", event.target.value)
                  }
                  className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                >
                  {["CHF", "EUR", "USD", "GBP"].map((currency) => (
                    <option key={currency}>{currency}</option>
                  ))}
                </select>
              </label>
              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#1d1e1c]">
                  Minimum salary
                </span>
                <input
                  inputMode="numeric"
                  value={preferences.salary_min}
                  disabled={preferences.no_preference.includes("salary")}
                  onChange={(event) =>
                    onChange(
                      "salary_min",
                      event.target.value.replace(/[^\d\s.,']/g, ""),
                    )
                  }
                  placeholder="90000"
                  className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 disabled:opacity-45 focus:border-accent/70"
                />
              </label>
              <button
                type="button"
                className={cn(
                  "inline-flex min-h-9 items-center justify-center rounded-md border px-3 text-xs font-bold transition sm:col-span-2",
                  preferences.no_preference.includes("salary")
                    ? "border-accent/65 bg-accent/14 text-foreground"
                    : "border-border bg-[#fff8f1] text-[#1d1e1c] hover:border-accent/45 hover:bg-accent/10",
                )}
                onClick={() => onSetAny("salary")}
              >
                No salary preference
              </button>
            </div>

            <div className="grid gap-3 rounded-md border border-border bg-[#fff8f1] p-3">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Work authorization
              </span>
              <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_180px]">
                <select
                  value={preferences.work_authorization}
                  disabled={preferences.no_preference.includes(
                    "work_authorization",
                  )}
                  onChange={(event) =>
                    onChange("work_authorization", event.target.value)
                  }
                  className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none disabled:opacity-45 focus:border-accent/70"
                >
                  <option value="">Not specified</option>
                  {preferenceOptions.work_authorization.map((item) => (
                    <option key={item}>{item}</option>
                  ))}
                </select>
                <button
                  type="button"
                  className={cn(
                    "inline-flex min-h-10 items-center justify-center rounded-md border px-3 text-xs font-bold transition",
                    preferences.no_preference.includes("work_authorization")
                      ? "border-accent/65 bg-accent/14 text-foreground"
                      : "border-border bg-[#fff8f1] text-[#1d1e1c] hover:border-accent/45 hover:bg-accent/10",
                  )}
                  onClick={() => onSetAny("work_authorization")}
                >
                  No preference
                </button>
              </div>
              {preferences.work_authorization === "Swiss permit" &&
              !preferences.no_preference.includes("work_authorization") ? (
                <label className="grid gap-2">
                  <span className="text-xs font-bold text-[#1d1e1c]">
                    Swiss permit status
                  </span>
                  <select
                    value={preferences.swiss_permit_status}
                    onChange={(event) =>
                      onChange("swiss_permit_status", event.target.value)
                    }
                    className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                  >
                    <option value="">Select permit status</option>
                    {preferenceOptions.swiss_permit_status.map((item) => (
                      <option key={item}>{item}</option>
                    ))}
                  </select>
                </label>
              ) : null}
            </div>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">Notes</span>
              <textarea
                value={preferences.notes}
                onChange={(event) => onChange("notes", event.target.value)}
                placeholder="Availability, preferred tech stack, relocation timing, or other matching context..."
                rows={4}
                className="min-h-[112px] resize-none rounded-md border border-border bg-[#ffffff] px-3 py-2.5 text-sm font-semibold leading-5 text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p
            className={cn(
              "text-sm font-semibold",
              status === "error" ? "text-[#fa5d00]" : "text-muted",
            )}
          >
            {message || "Empty preferences stay hidden"}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-7 text-[13px] text-foreground shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#e95300] hover:to-[#e95300]"
              disabled={status === "loading"}
              onClick={onSave}
            >
              <Save className="h-4 w-4" />
              {status === "loading" ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PreferenceListEditor({
  field,
  values,
  inputValue,
  isAny,
  onInputChange,
  onAdd,
  onRemove,
  onSetAny,
}: {
  field: PreferenceListField;
  values: string[];
  inputValue: string;
  isAny: boolean;
  onInputChange: (field: PreferenceListField, value: string) => void;
  onAdd: (field: PreferenceListField) => void;
  onRemove: (field: PreferenceListField, value: string) => void;
  onSetAny: (field: PreferenceAnyField) => void;
}) {
  const config = preferenceListLabels[field];
  const suggestionListId = `${field}-suggestions`;

  return (
    <div className="rounded-md border border-border bg-[#fff8f1] p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-bold text-[#1d1e1c]">{config.label}</p>
        <button
          type="button"
          className={cn(
            "inline-flex min-h-7 items-center rounded-md border px-2.5 text-[11px] font-bold transition",
            isAny
              ? "border-accent/65 bg-accent/14 text-foreground"
              : "border-border bg-[#fff8f1] text-muted hover:border-accent/45 hover:bg-accent/10 hover:text-[#1d1e1c]",
          )}
          onClick={() => onSetAny(field)}
        >
          No preference
        </button>
      </div>
      <div className="mt-2 flex gap-2">
        <input
          value={inputValue}
          disabled={isAny}
          list={suggestionListId}
          onChange={(event) => onInputChange(field, event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              onAdd(field);
            }
          }}
          placeholder={config.placeholder}
          className="h-9 min-w-0 flex-1 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 disabled:opacity-45 focus:border-accent/70"
        />
        <datalist id={suggestionListId}>
          {preferenceSuggestions[field].map((suggestion) => (
            <option key={suggestion} value={suggestion} />
          ))}
        </datalist>
        <button
          type="button"
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border text-[#1d1e1c] transition hover:bg-[#fff3e8] disabled:cursor-not-allowed disabled:opacity-45"
          onClick={() => onAdd(field)}
          disabled={isAny}
          aria-label={`Add ${config.label.toLowerCase()}`}
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
      {isAny && (
        <p className="mt-3 rounded-md border border-accent/25 bg-accent/10 px-3 py-2 text-xs font-semibold text-accent">
          Any {config.label.toLowerCase()} is acceptable.
        </p>
      )}
      {values.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {values.map((value) => (
            <button
              key={value}
              type="button"
              className="inline-flex min-h-7 items-center gap-1.5 rounded-md border border-border bg-[#fff8f1] px-2.5 text-xs font-semibold text-[#1d1e1c] transition hover:border-[#fa5d00]/50 hover:text-foreground"
              onClick={() => onRemove(field, value)}
            >
              {value}
              <X className="h-3.5 w-3.5 text-muted" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function PreferenceToggleGroup({
  title,
  field,
  options,
  selectedValues,
  isAny,
  onToggle,
  onSetAny,
  className,
}: {
  title: string;
  field: PreferenceToggleField;
  options: string[];
  selectedValues: string[];
  onToggle: (field: PreferenceToggleField, value: string) => void;
  isAny: boolean;
  onSetAny: (field: PreferenceAnyField) => void;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-md border border-border bg-[#fff8f1] p-3",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-bold text-[#1d1e1c]">{title}</p>
        <button
          type="button"
          className={cn(
            "inline-flex min-h-7 items-center rounded-md border px-2.5 text-[11px] font-bold transition",
            isAny
              ? "border-accent/65 bg-accent/14 text-foreground"
              : "border-border bg-[#fff8f1] text-muted hover:border-accent/45 hover:bg-accent/10 hover:text-[#1d1e1c]",
          )}
          onClick={() => onSetAny(field)}
        >
          No preference
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {options.map((option) => {
          const isSelected = selectedValues.includes(option) && !isAny;
          return (
            <button
              key={option}
              type="button"
              className={cn(
                "inline-flex min-h-8 items-center rounded-md border px-2.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-45",
                isSelected
                  ? "border-accent/65 bg-accent/14 text-foreground"
                  : "border-border bg-[#fff8f1] text-[#1d1e1c] hover:border-accent/45 hover:bg-accent/10",
              )}
              disabled={isAny}
              onClick={() => onToggle(field, option)}
            >
              {option}
            </button>
          );
        })}
      </div>
      {isAny && (
        <p className="mt-3 rounded-md border border-accent/25 bg-accent/10 px-3 py-2 text-xs font-semibold text-accent">
          Any {title.toLowerCase()} is acceptable.
        </p>
      )}
    </div>
  );
}
