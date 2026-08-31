"use client";

import { Check, Search, X } from "lucide-react";

import {
  JobSearchConfiguration,
  type JobSearchConfigurationProps,
} from "@/components/job-search-configuration";
import { Button } from "@/components/ui/button";
import { getSearchSourcesLabel } from "@/features/job-search/formatting";
import type {
  ActiveSearchSource,
  ParserId,
  ParserSearchStatus,
} from "@/features/job-search/model/types";
import { cn } from "@/lib/utils";

const parserSourceOptions = [
  {
    id: "linkedin",
    label: "LinkedIn",
    description: "Extract jobs from LinkedIn",
    mark: "in",
    color: "bg-[#0a66c2]",
  },
  {
    id: "indeed",
    label: "Indeed",
    description: "Extract jobs from Indeed",
    mark: "i",
    color: "bg-[#2557a7]",
  },
  {
    id: "jobs_ch",
    label: "jobs.ch",
    description: "Extract jobs from jobs.ch",
    mark: "j",
    color: "bg-[#e4002b]",
  },
] as const;

export type JobSearchDialogProps = JobSearchConfigurationProps & {
  status: ParserSearchStatus;
  message: string;
  onClose: () => void;
  onActivateSource: (source: ActiveSearchSource) => void;
  onToggleParser: (parser: ParserId) => void;
  onToggleDirectCompanies: () => void;
  onStartSearch: () => void | Promise<void>;
};

export function JobSearchDialog({
  form,
  activeSource,
  sourceConfigs,
  selectedSourceConfigIds,
  selectedParserSearchConfigId,
  directCompanies,
  newLinkedInProfession,
  status,
  message,
  onClose,
  onActivateSource,
  onToggleParser,
  onToggleDirectCompanies,
  onStartSearch,
  onFormChange,
  onReset,
  onSelectSourceConfig,
  onSaveSourceConfig,
  onSelectedDirectCompaniesChange,
  onNewLinkedInProfessionChange,
  onAddLinkedInProfession,
  onRemoveLinkedInProfession,
}: JobSearchDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 p-2 backdrop-blur-sm sm:p-3">
      <div className="panel flex h-[calc(100dvh-16px)] w-full max-w-[1280px] flex-col overflow-hidden border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:h-[calc(100dvh-24px)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-foreground 2xl:text-[24px]">
              Search vacancies
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              Choose one or more sources and configure search settings
            </p>
          </div>
          <button
            type="button"
            aria-label="Close parser settings"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-4 min-h-0 flex-1 overflow-x-hidden overflow-y-auto rounded-md border border-border">
          <div className="grid min-h-0 md:grid-cols-[280px_minmax(0,1fr)] md:items-start xl:grid-cols-[300px_minmax(0,1fr)]">
            <section className="min-w-0 border-b border-border p-4 md:sticky md:top-0 md:self-start md:border-b-0 2xl:p-5">
              <h3 className="text-sm font-bold text-foreground">
                1. Choose sources
              </h3>
              <div className="mt-4 grid gap-3">
                {parserSourceOptions.map((parserOption) => {
                  const isSelected = form.parsers.includes(parserOption.id);
                  const isActive = activeSource === parserOption.id;
                  return (
                    <div
                      key={parserOption.id}
                      className={cn(
                        "flex w-full min-w-0 items-center rounded-md border bg-[#fff8f1] p-2 transition",
                        isActive
                          ? "border-accent shadow-[0_0_0_1px_rgba(255,90,0,0.18)]"
                          : "border-border hover:border-[#c0bbb6] hover:bg-[#fff3e8]",
                      )}
                    >
                      <button
                        type="button"
                        aria-label={`Configure ${parserOption.label}`}
                        aria-current={isActive ? "true" : undefined}
                        onClick={() => onActivateSource(parserOption.id)}
                        className="flex min-w-0 flex-1 items-center gap-3 rounded p-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
                      >
                        <div
                          className={cn(
                            "grid h-9 w-9 shrink-0 place-items-center rounded-md text-lg font-black text-foreground",
                            parserOption.color,
                          )}
                        >
                          {parserOption.mark}
                        </div>
                        <div className="min-w-0 flex-1">
                          <h4 className="text-sm font-bold text-foreground">
                            {parserOption.label}
                          </h4>
                          <p className="mt-1 text-xs font-medium text-muted">
                            {parserOption.description}
                          </p>
                        </div>
                      </button>
                      <button
                        type="button"
                        aria-label={`Include ${parserOption.label} in search`}
                        aria-pressed={isSelected}
                        onClick={() => onToggleParser(parserOption.id)}
                        className={cn(
                          "grid h-8 w-8 shrink-0 place-items-center rounded outline-none transition focus-visible:ring-2 focus-visible:ring-accent/70",
                          isSelected
                            ? "bg-accent/10"
                            : "hover:bg-[#fff3e8]",
                        )}
                      >
                        <span
                          className={cn(
                            "grid h-5 w-5 place-items-center rounded border-2",
                            isSelected
                              ? "border-accent bg-accent"
                              : "border-border",
                          )}
                        >
                          {isSelected ? (
                            <Check className="h-3.5 w-3.5 text-foreground" />
                          ) : null}
                        </span>
                      </button>
                    </div>
                  );
                })}
                <div
                  className={cn(
                    "flex w-full min-w-0 items-center rounded-md border bg-[#fff8f1] p-2 transition",
                    activeSource === "direct_companies"
                      ? "border-[#fa5d00] shadow-[0_0_0_1px_rgba(139,92,246,0.20)]"
                      : "border-border hover:border-[#c0bbb6] hover:bg-[#fff3e8]",
                  )}
                >
                  <button
                    type="button"
                    aria-label="Configure Direct Companies"
                    aria-current={
                      activeSource === "direct_companies" ? "true" : undefined
                    }
                    onClick={() => onActivateSource("direct_companies")}
                    className="flex min-w-0 flex-1 items-center gap-3 rounded p-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-[#fa5d00]/70"
                  >
                    <div className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-[#fa5d00] text-[11px] font-black uppercase tracking-tight text-foreground">
                      dc
                    </div>
                    <div className="min-w-0 flex-1">
                      <h4 className="text-sm font-bold text-foreground">
                        Direct Companies
                      </h4>
                      <p className="mt-1 text-xs font-medium text-muted">
                        Track jobs on company career pages
                      </p>
                    </div>
                  </button>
                  <button
                    type="button"
                    aria-label="Include Direct Companies in search"
                    aria-pressed={form.directCompaniesEnabled}
                    onClick={onToggleDirectCompanies}
                    className={cn(
                      "grid h-8 w-8 shrink-0 place-items-center rounded outline-none transition focus-visible:ring-2 focus-visible:ring-[#fa5d00]/70",
                      form.directCompaniesEnabled
                        ? "bg-[#fa5d00]/10"
                        : "hover:bg-[#fff3e8]",
                    )}
                  >
                    <span
                      className={cn(
                        "grid h-5 w-5 place-items-center rounded border-2",
                        form.directCompaniesEnabled
                          ? "border-[#fa5d00] bg-[#fa5d00]"
                          : "border-border",
                      )}
                    >
                      {form.directCompaniesEnabled ? (
                        <Check className="h-3.5 w-3.5 text-foreground" />
                      ) : null}
                    </span>
                  </button>
                </div>
              </div>
            </section>

            <JobSearchConfiguration
              form={form}
              activeSource={activeSource}
              sourceConfigs={sourceConfigs}
              selectedSourceConfigIds={selectedSourceConfigIds}
              selectedParserSearchConfigId={selectedParserSearchConfigId}
              directCompanies={directCompanies}
              newLinkedInProfession={newLinkedInProfession}
              onFormChange={onFormChange}
              onReset={onReset}
              onSelectSourceConfig={onSelectSourceConfig}
              onSaveSourceConfig={onSaveSourceConfig}
              onSelectedDirectCompaniesChange={
                onSelectedDirectCompaniesChange
              }
              onNewLinkedInProfessionChange={
                onNewLinkedInProfessionChange
              }
              onAddLinkedInProfession={onAddLinkedInProfession}
              onRemoveLinkedInProfession={onRemoveLinkedInProfession}
            />
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p aria-live="polite" className="text-sm font-semibold text-muted">
            Sources:{" "}
            <span className="text-foreground">
              {getSearchSourcesLabel(form)}
            </span>
            {message ? (
              <span
                className={cn(
                  "ml-2",
                  status === "error" ? "text-[#fa5d00]" : "text-accent",
                )}
              >
                {message}
              </span>
            ) : null}
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
              onClick={() => void onStartSearch()}
            >
              <Search className="h-4 w-4" />
              {status === "loading" ? "Searching..." : "Start search"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
