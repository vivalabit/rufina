"use client";

import { useState } from "react";
import {
  Archive,
  Bookmark,
  ChevronDown,
  Plus,
  Search,
  Settings,
} from "lucide-react";

import { AutoSearchDialog } from "@/components/auto-search-dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type BulkAnalysisScope = "recent" | "missing";

type JobsToolbarProps = {
  className?: string;
  savedJobsCount: number;
  archivedJobsCount: number;
  showSavedJobs: boolean;
  showArchivedJobs: boolean;
  isAnalysisMenuOpen: boolean;
  bulkAnalysisScope: BulkAnalysisScope | null;
  recentAnalysisCount: number;
  missingAnalysisCount: number;
  onAddVacancy: () => void;
  onSearchVacancies: () => void;
  onToggleSavedJobs: () => void;
  onToggleArchivedJobs: () => void;
  onAnalysisMenuOpenChange: (isOpen: boolean) => void;
  onRunAnalysis: (scope: BulkAnalysisScope) => void;
  onVacanciesChanged: () => void | Promise<void>;
};

const secondaryButtonClass =
  "h-10 shrink-0 rounded-lg border border-white/[0.13] bg-[#121923] px-4 text-[13px] font-bold text-[#e9edf4] shadow-[inset_0_1px_0_rgba(255,255,255,0.035)] hover:border-white/20 hover:bg-[#18212d] 2xl:h-12 2xl:px-5 2xl:text-sm";

export function JobsToolbar({
  className,
  savedJobsCount,
  archivedJobsCount,
  showSavedJobs,
  showArchivedJobs,
  isAnalysisMenuOpen,
  bulkAnalysisScope,
  recentAnalysisCount,
  missingAnalysisCount,
  onAddVacancy,
  onSearchVacancies,
  onToggleSavedJobs,
  onToggleArchivedJobs,
  onAnalysisMenuOpenChange,
  onRunAnalysis,
  onVacanciesChanged,
}: JobsToolbarProps) {
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  return (
    <>
      <div
        className={cn(
          "relative min-w-0",
          className,
        )}
        onKeyDown={(event) => {
          if (event.key === "Escape") onAnalysisMenuOpenChange(false);
        }}
      >
        <div
          aria-label="Jobs actions"
          className="flex min-w-0 flex-nowrap items-center gap-2 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
        <Button
          className="h-10 shrink-0 rounded-lg border border-[#ff7524] bg-[linear-gradient(135deg,#ff7a16_0%,#ff5708_100%)] px-4 text-[13px] font-bold text-white shadow-[0_10px_28px_rgba(255,90,0,0.24),inset_0_1px_0_rgba(255,255,255,0.22)] hover:bg-[linear-gradient(135deg,#ff852b_0%,#ff6415_100%)] 2xl:h-12 2xl:px-5 2xl:text-sm"
          onClick={onAddVacancy}
        >
          <Plus className="h-[18px] w-[18px] stroke-[2.3] 2xl:h-5 2xl:w-5" />
          Add vacancy
        </Button>

        <Button
          className="h-10 shrink-0 rounded-lg border border-[#9868ff] bg-[linear-gradient(135deg,#8547ee_0%,#6d28d9_100%)] px-4 text-[13px] font-bold text-white shadow-[0_10px_28px_rgba(124,58,237,0.30),inset_0_1px_0_rgba(255,255,255,0.18)] hover:bg-[linear-gradient(135deg,#945cf2_0%,#7c3aed_100%)] 2xl:h-12 2xl:px-5 2xl:text-sm"
          onClick={onSearchVacancies}
        >
          <Search className="h-[18px] w-[18px] stroke-[2.3] 2xl:h-5 2xl:w-5" />
          Search vacancies
        </Button>

        <Button
          variant="ghost"
          aria-pressed={showSavedJobs}
          className={cn(
            secondaryButtonClass,
            showSavedJobs && "border-[#8b5cf6]/80 bg-[#231a37] text-white",
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
            showArchivedJobs && "border-[#8b5cf6]/80 bg-[#231a37] text-white",
          )}
          onClick={onToggleArchivedJobs}
        >
          <Archive className="h-[18px] w-[18px] 2xl:h-5 2xl:w-5" />
          Archived {archivedJobsCount > 0 ? `(${archivedJobsCount})` : ""}
        </Button>

        <Button
          variant="ghost"
          size="icon"
          aria-label="Jobs settings"
          aria-haspopup="dialog"
          className={cn(
            secondaryButtonClass,
            "w-10 px-0 2xl:w-12 2xl:px-0",
            isSettingsOpen && "border-[#8b5cf6]/80 bg-[#231a37] text-white",
          )}
          onClick={() => setIsSettingsOpen(true)}
        >
          <Settings className="h-[18px] w-[18px] 2xl:h-5 2xl:w-5" />
        </Button>

        <div>
          <Button
            variant="ghost"
            aria-haspopup="menu"
            aria-expanded={isAnalysisMenuOpen}
            className={cn(
              secondaryButtonClass,
              "gap-2.5",
              (isAnalysisMenuOpen || bulkAnalysisScope) &&
                "border-[#8b5cf6]/80 bg-[#231a37] text-white",
            )}
            disabled={bulkAnalysisScope !== null}
            onClick={() => onAnalysisMenuOpenChange(!isAnalysisMenuOpen)}
          >
            {bulkAnalysisScope ? "Analyzing..." : "Analysis"}
            {!bulkAnalysisScope ? (
              <ChevronDown className="h-3.5 w-3.5 text-[#8f99a8]" />
            ) : null}
          </Button>
        </div>
        </div>

        {isAnalysisMenuOpen ? (
          <div
            role="menu"
            aria-label="Bulk AI analysis"
            className="absolute right-0 top-12 z-40 grid w-[min(300px,calc(100vw-2rem))] gap-1 rounded-lg border border-border bg-[#101720] p-2 shadow-[0_18px_40px_rgba(0,0,0,0.48)] 2xl:top-14"
          >
            <p className="px-2 pb-1 pt-0.5 text-[10px] font-bold uppercase tracking-[0.08em] text-muted">
              Run AI analysis
            </p>
            <button
              type="button"
              role="menuitem"
              disabled={recentAnalysisCount === 0}
              onClick={() => onRunAnalysis("recent")}
              className="rounded-md px-2.5 py-2 text-left transition hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent"
            >
              <span className="block text-xs font-bold text-[#e6ebf3]">
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
              className="rounded-md px-2.5 py-2 text-left transition hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent"
            >
              <span className="block text-xs font-bold text-[#e6ebf3]">
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
    </>
  );
}
