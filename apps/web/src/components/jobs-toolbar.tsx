"use client";

import { useLayoutEffect, useRef, useState } from "react";
import {
  Archive,
  Bookmark,
  ChevronDown,
  Plus,
  Search,
  Settings,
  ShieldCheck,
} from "lucide-react";

import { AutoSearchDialog } from "@/components/auto-search-dialog";
import { Button } from "@/components/ui/button";
import { VacancyFilterDialog } from "@/components/vacancy-filter-dialog";
import { cn } from "@/lib/utils";
import type { BulkAnalysisScope } from "@/features/jobs/model/types";

type JobsToolbarProps = {
  className?: string;
  searchQuery: string;
  savedJobsCount: number;
  archivedJobsCount: number;
  showSavedJobs: boolean;
  showArchivedJobs: boolean;
  isAnalysisMenuOpen: boolean;
  bulkAnalysisScope: BulkAnalysisScope | null;
  recentAnalysisCount: number;
  missingAnalysisCount: number;
  onSearchQueryChange: (value: string) => void;
  onAddVacancy: () => void;
  onSearchVacancies: () => void;
  onToggleSavedJobs: () => void;
  onToggleArchivedJobs: () => void;
  onAnalysisMenuOpenChange: (isOpen: boolean) => void;
  onRunAnalysis: (scope: BulkAnalysisScope) => void;
  onVacanciesChanged: () => void | Promise<void>;
};

const secondaryButtonClass =
  "h-10 shrink-0 rounded-lg border border-border bg-white px-4 text-[13px] font-bold text-[#1d1e1c] shadow-[0_4px_14px_rgba(227,214,197,0.45)] hover:border-[#c0bbb6] hover:bg-[#fff8f1] 2xl:h-12 2xl:px-5 2xl:text-sm";

export function JobsToolbar({
  className,
  searchQuery,
  savedJobsCount,
  archivedJobsCount,
  showSavedJobs,
  showArchivedJobs,
  isAnalysisMenuOpen,
  bulkAnalysisScope,
  recentAnalysisCount,
  missingAnalysisCount,
  onSearchQueryChange,
  onAddVacancy,
  onSearchVacancies,
  onToggleSavedJobs,
  onToggleArchivedJobs,
  onAnalysisMenuOpenChange,
  onRunAnalysis,
  onVacanciesChanged,
}: JobsToolbarProps) {
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isVacancyFilterOpen, setIsVacancyFilterOpen] = useState(false);
  const [analysisMenuLeft, setAnalysisMenuLeft] = useState(0);
  const [analysisMenuTop, setAnalysisMenuTop] = useState(0);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const analysisButtonRef = useRef<HTMLButtonElement>(null);

  useLayoutEffect(() => {
    if (!isAnalysisMenuOpen) return;

    const updateMenuPosition = () => {
      const toolbar = toolbarRef.current;
      const button = analysisButtonRef.current;
      if (!toolbar || !button) return;

      const toolbarRect = toolbar.getBoundingClientRect();
      const buttonRect = button.getBoundingClientRect();
      const menuWidth = Math.min(300, Math.max(0, window.innerWidth - 32));
      const desiredLeft = buttonRect.right - toolbarRect.left - menuWidth;
      const maximumLeft = Math.max(0, toolbarRect.width - menuWidth);
      setAnalysisMenuLeft(Math.max(0, Math.min(desiredLeft, maximumLeft)));
      setAnalysisMenuTop(buttonRect.bottom - toolbarRect.top + 8);
    };

    updateMenuPosition();
    window.addEventListener("resize", updateMenuPosition);
    window.addEventListener("scroll", updateMenuPosition, true);
    return () => {
      window.removeEventListener("resize", updateMenuPosition);
      window.removeEventListener("scroll", updateMenuPosition, true);
    };
  }, [isAnalysisMenuOpen]);

  return (
    <>
      <div
        ref={toolbarRef}
        className={cn("relative min-w-0", className)}
        onKeyDown={(event) => {
          if (event.key === "Escape") onAnalysisMenuOpenChange(false);
        }}
      >
        <div
          aria-label="Jobs actions"
          className="flex min-w-0 flex-col gap-2 pb-1 xl:flex-row xl:items-center xl:justify-between"
        >
        <div aria-label="Primary jobs actions" className="flex shrink-0 items-center gap-2">
        <Button
          className="h-10 shrink-0 rounded-lg border border-[#fa5d00] bg-[linear-gradient(135deg,#fa5d00_0%,#e95300_100%)] px-4 text-[13px] font-bold text-foreground shadow-[0_10px_28px_rgba(255,90,0,0.24),inset_0_1px_0_rgba(255,255,255,0.18)] hover:bg-[linear-gradient(135deg,#fa5d00_0%,#e95300_100%)] 2xl:h-12 2xl:px-5 2xl:text-sm"
          onClick={onSearchVacancies}
        >
          <Search className="h-[18px] w-[18px] stroke-[2.3] 2xl:h-5 2xl:w-5" />
          Search vacancies
        </Button>

        <Button
          variant="ghost"
          className="h-10 shrink-0 rounded-lg border border-[#fa5d00] bg-transparent px-4 text-[13px] font-bold text-accent shadow-none hover:border-[#e95300] hover:bg-[#fa5d00]/10 hover:text-accent 2xl:h-12 2xl:px-5 2xl:text-sm"
          onClick={onAddVacancy}
        >
          <Plus className="h-[18px] w-[18px] stroke-[2.3] text-accent 2xl:h-5 2xl:w-5" />
          Add vacancy
        </Button>
        </div>

        <label className="flex h-10 min-w-[220px] flex-1 items-center gap-2.5 rounded-lg border border-border bg-white px-3 shadow-[0_4px_14px_rgba(227,214,197,0.3)] focus-within:border-accent/70 focus-within:ring-2 focus-within:ring-accent/15 2xl:h-12 2xl:px-4">
          <Search className="h-[18px] w-[18px] shrink-0 text-muted 2xl:h-5 2xl:w-5" />
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => onSearchQueryChange(event.target.value)}
            aria-label="Search jobs"
            placeholder="Search jobs..."
            className="h-full min-w-0 flex-1 !border-transparent !bg-transparent text-[13px] font-medium text-foreground outline-none placeholder:text-muted focus-visible:!outline-none 2xl:text-sm"
          />
        </label>

        <div
          aria-label="Secondary jobs actions"
          className="flex min-w-0 flex-nowrap items-center gap-2 overflow-x-auto xl:ml-auto xl:justify-end [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >

        <Button
          variant="ghost"
          aria-pressed={showSavedJobs}
          className={cn(
            secondaryButtonClass,
            showSavedJobs && "border-[#fa5d00]/80 bg-[#ffffff] text-foreground",
          )}
          onClick={onToggleSavedJobs}
        >
          <Bookmark className="h-[18px] w-[18px] 2xl:h-5 2xl:w-5" />
          Saved Jobs {savedJobsCount > 0 ? `(${savedJobsCount})` : ""}
        </Button>

        <Button
          variant="ghost"
          aria-pressed={showArchivedJobs}
          className={cn(
            secondaryButtonClass,
            showArchivedJobs && "border-[#fa5d00]/80 bg-[#ffffff] text-foreground",
          )}
          onClick={onToggleArchivedJobs}
        >
          <Archive className="h-[18px] w-[18px] 2xl:h-5 2xl:w-5" />
          Archived {archivedJobsCount > 0 ? `(${archivedJobsCount})` : ""}
        </Button>

        <Button
          variant="ghost"
          aria-label="Auto Search"
          aria-haspopup="dialog"
          className={cn(
            secondaryButtonClass,
            isSettingsOpen && "border-[#fa5d00]/80 bg-[#ffffff] text-foreground",
          )}
          onClick={() => setIsSettingsOpen(true)}
        >
          <Settings className="h-[18px] w-[18px] 2xl:h-5 2xl:w-5" />
          Auto Search
        </Button>

        <Button
          variant="ghost"
          aria-label="Vacancy Filter"
          aria-haspopup="dialog"
          className={cn(
            secondaryButtonClass,
            isVacancyFilterOpen &&
              "border-[#fa5d00]/80 bg-[#ffffff] text-foreground",
          )}
          onClick={() => setIsVacancyFilterOpen(true)}
        >
          <ShieldCheck className="h-[18px] w-[18px] 2xl:h-5 2xl:w-5" />
          Vacancy Filter
        </Button>

        <div>
          <Button
            ref={analysisButtonRef}
            variant="ghost"
            aria-haspopup="menu"
            aria-expanded={isAnalysisMenuOpen}
            className={cn(
              secondaryButtonClass,
              "gap-2.5",
              (isAnalysisMenuOpen || bulkAnalysisScope) &&
                "border-[#fa5d00]/80 bg-[#ffffff] text-foreground",
            )}
            disabled={bulkAnalysisScope !== null}
            onClick={() => onAnalysisMenuOpenChange(!isAnalysisMenuOpen)}
          >
            {bulkAnalysisScope ? "Analyzing..." : "Analysis"}
            {!bulkAnalysisScope ? (
              <ChevronDown className="h-3.5 w-3.5 text-[#615f5c]" />
            ) : null}
          </Button>
        </div>
        </div>
        </div>

        {isAnalysisMenuOpen ? (
          <div
            role="menu"
            aria-label="Bulk AI analysis"
            style={{ left: analysisMenuLeft, top: analysisMenuTop }}
            className="absolute z-40 grid w-[min(300px,calc(100vw-2rem))] gap-1 rounded-lg border border-border bg-[#ffffff] p-2 shadow-[0_18px_40px_rgba(0,0,0,0.48)]"
          >
            <p className="px-2 pb-1 pt-0.5 text-[10px] font-bold uppercase tracking-[0.08em] text-muted">
              Run AI analysis
            </p>
            <button
              type="button"
              role="menuitem"
              disabled={recentAnalysisCount === 0}
              onClick={() => onRunAnalysis("recent")}
              className="rounded-md px-2.5 py-2 text-left transition hover:bg-[#fff3e8] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent"
            >
              <span className="block text-xs font-bold text-[#1d1e1c]">
                Vacancies added in the last 24 hours
              </span>
              <span className="mt-1 block text-[11px] leading-4 text-muted">
                Re-run analysis for {recentAnalysisCount} active vacancies.
              </span>
            </button>
            <button
              type="button"
              role="menuitem"
              disabled={missingAnalysisCount === 0}
              onClick={() => onRunAnalysis("missing")}
              className="rounded-md px-2.5 py-2 text-left transition hover:bg-[#fff3e8] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent"
            >
              <span className="block text-xs font-bold text-[#1d1e1c]">
                Vacancies without current analysis
              </span>
              <span className="mt-1 block text-[11px] leading-4 text-muted">
                Analyze {missingAnalysisCount} vacancies with missing or outdated results.
              </span>
            </button>
          </div>
        ) : null}
      </div>

      <AutoSearchDialog
        open={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        onVacanciesChanged={onVacanciesChanged}
      />
      <VacancyFilterDialog
        open={isVacancyFilterOpen}
        onClose={() => setIsVacancyFilterOpen(false)}
      />
    </>
  );
}
