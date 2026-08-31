"use client";

import {
  ChevronDown,
  Info,
  Plus,
  RotateCcw,
  Save,
  X,
} from "lucide-react";

import { DirectCompaniesSource } from "@/components/direct-companies-source";
import { Button } from "@/components/ui/button";
import type { JobSourceConfigPayload } from "@/features/job-search/api/dto";
import { getParserLabel } from "@/features/job-search/formatting";
import { directCompanyDirections } from "@/features/job-search/model/constants";
import { isLinkedInProfessionQuery } from "@/features/job-search/model/form-mappers";
import { getSourceSearchConfigLabel } from "@/features/job-search/model/selectors";
import type {
  ActiveSearchSource,
  DirectCompanyDirection,
  ParserId,
  ParserSearchForm,
} from "@/features/job-search/model/types";
import type { DirectCompanyDefinition } from "@/lib/direct-company-catalog";
import { cn } from "@/lib/utils";

export type ParserSearchFormChange = <Field extends keyof ParserSearchForm>(
  field: Field,
  value: ParserSearchForm[Field],
) => void;

export type JobSearchConfigurationProps = {
  form: ParserSearchForm;
  activeSource: ActiveSearchSource;
  sourceConfigs: readonly JobSourceConfigPayload[];
  selectedSourceConfigIds: Partial<Record<ParserId, string>>;
  selectedParserSearchConfigId: string;
  directCompanies: readonly DirectCompanyDefinition[];
  newLinkedInProfession: string;
  onFormChange: ParserSearchFormChange;
  onReset: () => void;
  onSelectSourceConfig: (source: ParserId, configId: string) => void;
  onSaveSourceConfig: (source: ParserId) => void | Promise<void>;
  onSelectedDirectCompaniesChange: (companyIds: string[]) => void;
  onNewLinkedInProfessionChange: (value: string) => void;
  onAddLinkedInProfession: () => void;
  onRemoveLinkedInProfession: (queryIndex: number) => void;
};

export function JobSearchConfiguration({
  form,
  activeSource,
  sourceConfigs,
  selectedSourceConfigIds,
  selectedParserSearchConfigId,
  directCompanies,
  newLinkedInProfession,
  onFormChange,
  onReset,
  onSelectSourceConfig,
  onSaveSourceConfig,
  onSelectedDirectCompaniesChange,
  onNewLinkedInProfessionChange,
  onAddLinkedInProfession,
  onRemoveLinkedInProfession,
}: JobSearchConfigurationProps) {
  const availableConfigs =
    activeSource === "direct_companies"
      ? []
      : sourceConfigs.filter((config) => config.source === activeSource);
  const selectedSourceConfigId =
    activeSource === "direct_companies"
      ? ""
      : selectedSourceConfigIds[activeSource] ?? "";
  const professionQueries = form.linkedinQueries
    .map((query, index) => ({ query, index }))
    .filter(({ query }) => isLinkedInProfessionQuery(query));
  const supportingQueryCount =
    form.linkedinQueries.length - professionQueries.length;

  return (
    <section className="min-w-0 p-4 md:border-l md:border-border 2xl:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-bold text-foreground">
            2. Configure{" "}
            {activeSource === "direct_companies"
              ? "Direct Companies"
              : getParserLabel(activeSource)}
          </h3>
          <p className="mt-1 text-xs font-medium text-muted">
            {activeSource === "direct_companies"
              ? "Choose career pages and one broad direction. The Vacancy Filter handles the remaining criteria."
              : `These query fields belong only to ${getParserLabel(activeSource)}.`}
          </p>
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-2 text-xs font-bold text-muted transition hover:text-foreground"
          onClick={onReset}
        >
          <RotateCcw className="h-4 w-4" />
          Reset to defaults
        </button>
      </div>

      <div className="mt-4 grid gap-4">
        {activeSource !== "direct_companies" ? (
          <div className="grid gap-3 rounded-md border border-accent/25 bg-accent/[0.025] p-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Query config
              </span>
              <select
                aria-label={`${getParserLabel(activeSource)} query config`}
                value={selectedSourceConfigId}
                onChange={(event) =>
                  onSelectSourceConfig(activeSource, event.target.value)
                }
                className="h-9 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
              >
                <option value="">
                  {availableConfigs.length > 0
                    ? "Select query config"
                    : "No query configs available"}
                </option>
                {availableConfigs.map((config) => (
                  <option key={config.id} value={config.id}>
                    {getSourceSearchConfigLabel(config)}
                  </option>
                ))}
              </select>
            </label>
            {selectedParserSearchConfigId ? (
              <Button
                type="button"
                variant="ghost"
                aria-label={`Save ${getParserLabel(activeSource)} query config`}
                className="h-9 rounded-md border border-border bg-transparent px-3 text-xs text-[#1d1e1c] hover:bg-[#fff3e8]"
                onClick={() => void onSaveSourceConfig(activeSource)}
              >
                <Save className="h-4 w-4" />
                {selectedSourceConfigId ? "Save changes" : "Save as config"}
              </Button>
            ) : null}
          </div>
        ) : null}

        {activeSource === "direct_companies" ? (
          <>
            <DirectCompaniesSource
              companies={directCompanies}
              selectedCompanyIds={form.directCompanyIds}
              onSelectedCompanyIdsChange={onSelectedDirectCompaniesChange}
            />
            <section className="rounded-md border border-border bg-[#fff8f1] p-3">
              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#1d1e1c]">
                  Direction
                </span>
                <select
                  aria-label="Direct company direction"
                  value={form.directCompanyDirection}
                  onChange={(event) =>
                    onFormChange(
                      "directCompanyDirection",
                      event.target.value as DirectCompanyDirection,
                    )
                  }
                  className="h-9 rounded-md border border-border bg-white px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                >
                  {directCompanyDirections.map((direction) => (
                    <option key={direction.id} value={direction.id}>
                      {direction.label}
                    </option>
                  ))}
                </select>
              </label>
              <p className="mt-2 text-xs font-medium leading-5 text-muted">
                Every vacancy is collected from the selected company pages
                first. Direction is applied afterwards; seniority, posting
                date, and technologies come from the global Vacancy Filter.
              </p>
            </section>
          </>
        ) : null}

        {activeSource !== "direct_companies" ? (
          <>
            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Job title or keywords
              </span>
              <input
                value={form.keywords}
                onChange={(event) =>
                  onFormChange("keywords", event.target.value)
                }
                placeholder="e.g. Product Designer, UX Designer, Design System"
                className="h-9 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
              <span className="text-xs font-medium text-muted">
                Use keywords to find relevant vacancies
              </span>
            </label>

            {activeSource === "linkedin" ? (
              <section
                aria-labelledby="linkedin-professions-heading"
                className="rounded-md border border-border bg-[#fff8f1] p-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <h4
                      id="linkedin-professions-heading"
                      className="text-sm font-bold text-foreground"
                    >
                      Professions
                    </h4>
                    <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-bold text-accent">
                      {professionQueries.length}
                    </span>
                  </div>
                  <span className="text-[11px] font-semibold text-muted">
                    Entry level · Internship
                  </span>
                </div>
                <p className="mt-1 text-xs font-medium text-muted">
                  Each profession is searched separately across the two levels
                  above.
                  {supportingQueryCount > 0
                    ? ` ${supportingQueryCount} supporting entry-level search ${supportingQueryCount === 1 ? "term stays" : "terms stay"} active automatically.`
                    : ""}
                </p>

                {professionQueries.length > 0 ? (
                  <div className="mt-3 flex max-h-36 flex-wrap content-start gap-2 overflow-y-auto pr-1">
                    {professionQueries.map(({ query, index }) => (
                      <div
                        key={`${query.keyword}-${index}`}
                        className="inline-flex h-8 max-w-full items-center gap-1 rounded-md border border-border bg-white pl-2.5 pr-1 text-xs font-semibold text-foreground"
                      >
                        <span className="truncate">{query.keyword}</span>
                        <button
                          type="button"
                          aria-label={`Remove profession ${query.keyword}`}
                          title={`Remove ${query.keyword}`}
                          onClick={() => onRemoveLinkedInProfession(index)}
                          className="grid h-6 w-6 shrink-0 place-items-center rounded text-muted transition hover:bg-[#fff3e8] hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-3 rounded-md border border-dashed border-border bg-white/60 px-3 py-2 text-xs font-medium text-muted">
                    {supportingQueryCount > 0
                      ? "No dedicated professions configured. Supporting entry-level terms will still run."
                      : "No professions configured. Add one below, or the fallback keywords above will be used."}
                  </p>
                )}

                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                  <input
                    aria-label="New LinkedIn profession"
                    value={newLinkedInProfession}
                    onChange={(event) =>
                      onNewLinkedInProfessionChange(event.target.value)
                    }
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        onAddLinkedInProfession();
                      }
                    }}
                    placeholder="e.g. Security Analyst"
                    className="h-9 min-w-0 flex-1 rounded-md border border-border bg-white px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    aria-label="Add LinkedIn profession"
                    disabled={!newLinkedInProfession.trim()}
                    onClick={onAddLinkedInProfession}
                    className="h-9 rounded-md border border-border bg-white px-3 text-xs text-[#1d1e1c] hover:bg-[#fff3e8] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Plus className="h-4 w-4" />
                    Add profession
                  </Button>
                </div>
              </section>
            ) : null}

            <div className="grid gap-4 lg:grid-cols-2">
              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#1d1e1c]">
                  Location
                </span>
                <input
                  value={form.location}
                  onChange={(event) =>
                    onFormChange("location", event.target.value)
                  }
                  placeholder="e.g. Remote, United States, Europe"
                  className="h-9 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
                />
                <span className="text-xs font-medium text-muted">
                  Leave empty to search worldwide
                </span>
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#1d1e1c]">
                  Remote
                </span>
                <select
                  value={form.remote}
                  onChange={(event) =>
                    onFormChange("remote", event.target.value)
                  }
                  className="h-9 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                >
                  <option>Any</option>
                  <option>Remote only</option>
                  <option>Hybrid</option>
                  <option>On-site</option>
                </select>
                <span className="text-xs font-medium text-muted">
                  Filter by remote work options
                </span>
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#1d1e1c]">
                  Experience level
                </span>
                <select
                  value={form.experienceLevel}
                  onChange={(event) =>
                    onFormChange("experienceLevel", event.target.value)
                  }
                  className="h-9 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                >
                  <option>Any</option>
                  <option>Entry level</option>
                  <option>Associate</option>
                  <option>Mid-Senior level</option>
                  <option>Director</option>
                </select>
                <span className="text-xs font-medium text-muted">
                  Filter by experience level
                </span>
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#1d1e1c]">
                  Job type
                </span>
                <select
                  value={form.jobType}
                  onChange={(event) =>
                    onFormChange("jobType", event.target.value)
                  }
                  className="h-9 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                >
                  <option>Any</option>
                  <option>Full-time</option>
                  <option>Part-time</option>
                  <option>Contract</option>
                  <option>Internship</option>
                </select>
                <span className="text-xs font-medium text-muted">
                  Full-time, Part-time, Contract, etc.
                </span>
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#1d1e1c]">
                  Date posted
                </span>
                <select
                  value={form.datePosted}
                  onChange={(event) =>
                    onFormChange("datePosted", event.target.value)
                  }
                  className="h-9 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                >
                  <option>Any time</option>
                  <option>Past 24 hours</option>
                  <option>Past week</option>
                  <option>Past month</option>
                </select>
                <span className="text-xs font-medium text-muted">
                  Filter by job posting date
                </span>
              </label>
            </div>

            <div className="rounded-md border border-border bg-[#fff8f1] p-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold text-foreground">
                  Additional settings
                </h4>
                <ChevronDown className="h-4 w-4 rotate-180 text-muted" />
              </div>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <label className="grid gap-2">
                  <span className="text-xs font-bold text-[#1d1e1c]">
                    Results limit
                  </span>
                  <input
                    type="number"
                    min="1"
                    max="1000"
                    value={form.resultsLimit}
                    onChange={(event) =>
                      onFormChange("resultsLimit", event.target.value)
                    }
                    className="h-9 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                  />
                  <span className="text-xs font-medium text-muted">
                    Maximum number of vacancies to fetch (max 1000)
                  </span>
                </label>

                <label className="grid gap-2">
                  <span className="text-xs font-bold text-[#1d1e1c]">
                    Country
                  </span>
                  <select
                    value={form.country}
                    onChange={(event) =>
                      onFormChange("country", event.target.value)
                    }
                    className="h-9 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                  >
                    <option>Any</option>
                    <option>United States</option>
                    <option>United Kingdom</option>
                    <option>Germany</option>
                    <option>Switzerland</option>
                  </select>
                  <span className="text-xs font-medium text-muted">
                    Filter by country
                  </span>
                </label>
              </div>

              <div className="mt-4 flex items-start gap-3">
                <button
                  type="button"
                  aria-label="Deduplicate results"
                  onClick={() => onFormChange("deduplicate", !form.deduplicate)}
                  className={cn(
                    "relative mt-0.5 h-5 w-9 rounded-full transition",
                    form.deduplicate
                      ? "bg-accent shadow-[0_0_14px_rgba(255,90,0,0.22)]"
                      : "bg-[#fff8f1]",
                  )}
                >
                  <span
                    className={cn(
                      "absolute top-0.5 h-4 w-4 rounded-full bg-white transition",
                      form.deduplicate ? "right-0.5" : "left-0.5",
                    )}
                  />
                </button>
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-bold text-foreground">
                      Deduplicate results
                    </p>
                    <Info className="h-3.5 w-3.5 text-muted" />
                  </div>
                  <p className="mt-1 text-xs font-medium text-muted">
                    Remove duplicate vacancies
                  </p>
                </div>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </section>
  );
}
