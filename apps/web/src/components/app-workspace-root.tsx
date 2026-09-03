"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  BarChart3,
  Bookmark,
  BriefcaseBusiness,
  ChartNoAxesColumnIncreasing,
  Check,
  ChevronDown,
  ChevronRight,
  DollarSign,
  ExternalLink,
  FileText,
  MapPin,
  Monitor,
  Info,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  AssistantView,
  type AssistantAppliedAction,
  type AssistantDocumentAttachment,
  type AssistantLaunch,
} from "@/components/assistant-view";
import { ApplicationWorkspace } from "@/components/application-workspace";
import { ApplicationsView } from "@/components/applications-view";
import { CalendarView } from "@/components/calendar-view";
import { DashboardView } from "@/components/dashboard-view";
import { JobsToolbar } from "@/components/jobs-toolbar";
import { JobMainPanel } from "@/components/job-main-panel";
import { JobSearchDialog } from "@/components/job-search-dialog";
import {
  JobDetails,
  MatchPanel,
  RecommendationsPanel,
  SalaryInsights,
} from "@/components/job-summary-panels";
import {
  getJobSourceLabel,
  JobMatchRing,
  JobRoleIcon,
} from "@/components/job-visuals";
import { LogsView } from "@/components/logs-view";
import { ManualJobDialog } from "@/components/manual-job-dialog";
import { ProfileEditorDialog } from "@/components/profile-editor-dialog";
import {
  DocumentEditorDialog,
  EducationEditorDialog,
  ExperienceEditorDialog,
} from "@/components/profile-entry-editor-dialogs";
import {
  AdditionalNotesEditorDialog,
  DealbreakersEditorDialog,
  PreferencesEditorDialog,
  SkillsEditorDialog,
} from "@/components/profile-preference-editor-dialogs";
import { ProfileView } from "@/components/profile-view";
import { SettingsView } from "@/components/settings-view";
import { findWorkspaceApplication, type AppRoute, type View } from "@/lib/app-route";
import {
  directCompanyCatalog,
} from "@/lib/direct-company-catalog";
import { formatParserFailure } from "@/lib/parser-errors";
import {
  getJobSearchProgress,
  type JobSearchProgressPhase,
} from "@/lib/job-search-progress";
import { createClientId } from "@/lib/client-id";
import { ApiResponseError } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { useActivityFeed } from "@/features/activity/hooks/use-activity-feed";
import { useApplicationEvents } from "@/features/applications/hooks/use-application-events";
import { useApplications } from "@/features/applications/hooks/use-applications";
import { useProfile } from "@/features/profile/hooks/use-profile";
import { useAppSettings } from "@/features/settings/hooks/use-app-settings";
import { useUiSettings } from "@/features/settings/components/ui-settings-provider";
import { screenshotSessionStorageKey } from "@/features/app-shell/browser-storage/keys";
import { assistantPrompts } from "@/features/app-shell/model/assistant-prompts";
import {
  normalizeStoredApplicationEvents,
  normalizeStoredApplications,
} from "@/features/applications/browser-storage/normalizers";
import {
  sortApplicationEvents,
} from "@/features/applications/model/selectors";
import type { ManualApplicationDraft } from "@/features/applications/model/types";
import type {
  JobSearchRunPayload,
} from "@/features/job-search/api/dto";
import { getParserLabel } from "@/features/job-search/formatting";
import { useJobSearch } from "@/features/job-search/hooks/use-job-search";
import {
  defaultLinkedInProfessionExperienceLevels,
  defaultParserSearchForm,
  directCompanyDirections,
} from "@/features/job-search/model/constants";
import {
  directCompanySearchFiltersFromForm,
  normalizeDirectCompanyIds,
  parserSearchFiltersFromForm,
  parserSearchSourceIds,
  sourceSearchDraftFromFilters,
  sourceSearchDraftFromForm,
  sourceSearchFiltersFromForm,
} from "@/features/job-search/model/form-mappers";
import { getDefaultLinkedInSearchSelection } from "@/features/job-search/model/selectors";
import type {
  ActiveSearchSource,
  ParserId,
  ParserSearchForm,
  ParserSearchStatus,
  SourceSearchDraft,
} from "@/features/job-search/model/types";
import type { AiMatchJobStatus } from "@/features/jobs/api/dto";
import { useJobs } from "@/features/jobs/hooks/use-jobs";
import {
  normalizeStoredJobs,
} from "@/features/jobs/browser-storage/normalizers";
import {
  formatJobLocationCompact,
  formatJobPostedCompact,
  getJobApplyUrl,
} from "@/features/jobs/formatting";
import {
  formatMatchValue,
  hasDisplayableMatch,
} from "@/features/jobs/model/ai-match";
import {
  defaultJobFilters,
  defaultManualJobDraft,
  experienceFilterOptions,
  jobSortOptions,
  matchFilterOptions,
  remoteFilterOptions,
  salaryFilterOptions,
} from "@/features/jobs/model/constants";
import { createManualJobFromDraft } from "@/features/jobs/model/manual-analysis";
import {
  countArchivedJobs,
  countSavedJobs,
  getBulkAnalysisCandidates,
  hasActiveJobFilters,
  keepStoredUserJobs,
  mergeJobs,
  selectAvailableJobs,
  selectFilteredJobs,
  selectJobFilterOptions,
} from "@/features/jobs/model/selectors";
import {
  isUserManagedJob,
} from "@/features/jobs/model/sources";
import type {
  BulkAnalysisScope,
  JobFilterKey,
  JobFilters,
  JobSortBy,
  ManualJobDraft,
} from "@/features/jobs/model/types";
import type {
  AppSettingsUpdate,
} from "@/features/settings/model/types";
import { resolveApiUrl } from "@/shared/api/config";
import { readApiErrorMessage } from "@/shared/api/error";
import {
  browserStorageNamespacePrefix,
} from "@/shared/browser-storage/constants";
import { formatFileSize } from "@/shared/formatting/files";
import {
  defaultCandidateProfile,
  defaultDocumentDraft,
  defaultEducationDraft,
  defaultExperienceDraft,
  defaultJobPreferences,
  defaultPreferenceInputs,
} from "@/features/profile/model/defaults";
import {
  inferDocumentLanguage as inferDocumentLanguageModel,
  mergeEducationEntries,
  mergeExperienceEntries,
  mergeSkillLists as mergeSkillListsModel,
  normalizeDocumentEntry as normalizeDocumentEntryModel,
  normalizeEducationEntry as normalizeEducationEntryModel,
  normalizeExperienceEntry as normalizeExperienceEntryModel,
  parseEducationEntries as parseEducationEntriesModel,
  parseExperienceEntries as parseExperienceEntriesModel,
  parseProfileLines as parseProfileLinesModel,
  serializeEducationEntries as serializeEducationEntriesModel,
  serializeExperienceEntries as serializeExperienceEntriesModel,
} from "@/features/profile/model/entries";
import { normalizeCandidateProfile, hasProfileValue } from "@/features/profile/model/normalizers";
import {
  normalizeJobPreferences as normalizeJobPreferencesModel,
  parseJobPreferences as parseJobPreferencesModel,
  serializeJobPreferences as serializeJobPreferencesModel,
} from "@/features/profile/model/preferences";
import type {
  ApplicationDocument,
  ApplicationEvent,
  ApplicationStatus,
  TrackedApplication,
} from "@/shared/types/application";
import type { Job } from "@/shared/types/job";
import type {
  CandidateProfile,
  DocumentEntry,
  EducationEntry,
  ExperienceEntry,
  JobPreferences,
  PreferenceAnyField,
  PreferenceInputs,
  PreferenceListField,
} from "@/shared/types/profile";

const tabs = ["Overview", "AI Match"];

const aiMatchStatusPollDelayMs = 2500;
const aiMatchStatusPollMaxAttempts = 720;
const screenshotSessionId =
  process.env.NEXT_PUBLIC_SCREENSHOT_SESSION_ID?.trim() ?? "";

const jobFilterWidths: Record<JobFilterKey, string> = {
  location: "w-[126px] 2xl:w-[154px]",
  remote: "w-[112px] 2xl:w-[146px]",
  salary: "w-[108px] 2xl:w-[138px]",
  experience: "w-[142px] 2xl:w-[164px]",
  type: "w-[132px] 2xl:w-[154px]",
  match: "w-[132px] 2xl:w-[154px]",
};

type JobFilterDropdownProps = {
  filterKey: JobFilterKey;
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  icon: LucideIcon;
  className?: string;
  onChange: (value: string) => void;
};

function JobFilterDropdown({
  filterKey,
  label,
  value,
  options,
  icon: Icon,
  className,
  onChange,
}: JobFilterDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const normalizedSearch = searchQuery.trim().toLowerCase();
  const visibleOptions = options.filter((option) =>
    option.label.toLowerCase().includes(normalizedSearch),
  );
  const selectedLabel =
    value === "Any"
      ? label
      : options.find((option) => option.value === value)?.label ?? value;
  const menuId = `jobs-${filterKey}-filter-menu`;

  useEffect(() => {
    if (!isOpen) return;

    const focusTimer = window.setTimeout(() => searchRef.current?.focus(), 0);

    function closeOnOutsideClick(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
        setSearchQuery("");
      }
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setIsOpen(false);
      setSearchQuery("");
      triggerRef.current?.focus();
    }

    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);

    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [isOpen]);

  function selectValue(nextValue: string) {
    onChange(nextValue);
    setIsOpen(false);
    setSearchQuery("");
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  }

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <button
        ref={triggerRef}
        type="button"
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-controls={isOpen ? menuId : undefined}
        onClick={() => {
          setIsOpen((current) => !current);
          if (isOpen) setSearchQuery("");
        }}
        onKeyDown={(event) => {
          if (event.key !== "ArrowDown") return;
          event.preventDefault();
          setIsOpen(true);
        }}
        className={cn(
          "inline-flex h-8 w-full items-center gap-2 rounded-md border border-border/80 bg-[#fff8f1] px-2.5 text-left text-xs font-semibold text-[#1d1e1c] shadow-[0_3px_10px_rgba(227,214,197,0.24)] transition hover:border-[#c0bbb6] hover:bg-[#fff3e8] focus-visible:!outline-none focus-visible:border-accent/70 focus-visible:ring-2 focus-visible:ring-accent/20 2xl:h-10 2xl:gap-2.5 2xl:px-4 2xl:text-sm",
          value !== "Any" && "border-accent/70 bg-accent/15 text-foreground",
        )}
      >
        <Icon className="h-4 w-4 shrink-0 text-[#686762] 2xl:h-[18px] 2xl:w-[18px]" strokeWidth={1.9} />
        <span className="min-w-0 flex-1 truncate">{selectedLabel}</span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted transition-transform 2xl:h-4 2xl:w-4",
            isOpen && "rotate-180",
          )}
        />
      </button>

      {isOpen ? (
        <div
          id={menuId}
          role="dialog"
          aria-label={`${label} filter`}
          className="absolute left-0 top-[calc(100%+8px)] z-50 w-[min(340px,calc(100vw-32px))] overflow-hidden rounded-xl border border-border bg-white shadow-[0_18px_48px_rgba(74,61,48,0.18)]"
        >
          <div className="border-b border-border/70 bg-[#fffaf6] p-2.5">
            <label className="flex h-9 items-center gap-2 rounded-lg border border-border bg-white px-3 focus-within:border-accent/70 focus-within:ring-2 focus-within:ring-accent/15">
              <Search className="h-4 w-4 shrink-0 text-muted" />
              <input
                ref={searchRef}
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder={`Search ${label.toLowerCase()}...`}
                aria-label={`Search ${label} options`}
                className="h-full min-w-0 flex-1 !border-transparent !bg-transparent text-sm font-medium outline-none placeholder:text-muted focus-visible:!outline-none"
              />
              {searchQuery ? (
                <button
                  type="button"
                  aria-label={`Clear ${label} search`}
                  onClick={() => {
                    setSearchQuery("");
                    searchRef.current?.focus();
                  }}
                  className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground focus-visible:!outline-none focus-visible:ring-2 focus-visible:ring-accent/25"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </label>
          </div>

          <div id={`${menuId}-options`} role="listbox" aria-label={`${label} options`} className="job-scroll max-h-64 overflow-y-auto p-1.5">
            {!normalizedSearch ? (
              <button
                type="button"
                role="option"
                aria-selected={value === "Any"}
                onClick={() => selectValue("Any")}
                className={cn(
                  "flex min-h-10 w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-semibold text-[#4a4a47] transition hover:bg-[#fff3e8] focus-visible:!outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/25",
                  value === "Any" && "bg-accent/10 text-foreground",
                )}
              >
                <span className="min-w-0 flex-1">All {label.toLowerCase()}</span>
                {value === "Any" ? <Check className="h-4 w-4 shrink-0 text-accent" /> : null}
              </button>
            ) : null}

            {visibleOptions.map((option) => {
              const isSelected = value === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  title={option.label}
                  onClick={() => selectValue(option.value)}
                  className={cn(
                    "flex min-h-10 w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-medium text-[#4a4a47] transition hover:bg-[#fff3e8] focus-visible:!outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/25",
                    isSelected && "bg-accent/10 font-semibold text-foreground",
                  )}
                >
                  <span className="min-w-0 flex-1 truncate">{option.label}</span>
                  {isSelected ? <Check className="h-4 w-4 shrink-0 text-accent" /> : null}
                </button>
              );
            })}

            {visibleOptions.length === 0 ? (
              <div className="px-3 py-8 text-center">
                <Search className="mx-auto h-5 w-5 text-muted/70" />
                <p className="mt-2 text-sm font-semibold text-muted">No options found</p>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function parseProfileLines(value: string) {
  return parseProfileLinesModel(value);
}

function normalizeExperienceEntry(entry: Partial<ExperienceEntry>): ExperienceEntry {
  return normalizeExperienceEntryModel(entry, createClientId);
}

function parseExperienceEntries(value: string): ExperienceEntry[] {
  return parseExperienceEntriesModel(value, createClientId);
}

function serializeExperienceEntries(entries: ExperienceEntry[]) {
  return serializeExperienceEntriesModel(entries, createClientId);
}

function normalizeEducationEntry(entry: Partial<EducationEntry>): EducationEntry {
  return normalizeEducationEntryModel(entry, createClientId);
}

function parseEducationEntries(value: string): EducationEntry[] {
  return parseEducationEntriesModel(value, createClientId);
}

function serializeEducationEntries(entries: EducationEntry[]) {
  return serializeEducationEntriesModel(entries, createClientId);
}

function normalizeDocumentEntry(
  entry: Partial<DocumentEntry>,
  fallbackId = "",
): DocumentEntry {
  return normalizeDocumentEntryModel(entry, fallbackId, createClientId);
}

function inferDocumentLanguage(fileName: string, title = "") {
  return inferDocumentLanguageModel(fileName, title);
}

function normalizeJobPreferences(value: Partial<JobPreferences>): JobPreferences {
  return normalizeJobPreferencesModel(value);
}

function parseJobPreferences(value: string): JobPreferences {
  return parseJobPreferencesModel(value);
}

function serializeJobPreferences(preferences: JobPreferences) {
  return serializeJobPreferencesModel(preferences);
}

function wait(ms: number) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function createApplicationFromJob(job: Job, status: ApplicationStatus = "applied"): TrackedApplication {
  const appliedAt = new Date().toISOString();

  return {
    id: `application-${job.id}`,
    job,
    status,
    appliedAt,
    nextStep: "",
    notes: "",
    documents: [],
  };
}

function createApplicationFromManualDraft(draft: ManualApplicationDraft): TrackedApplication {
  const generatedJob = createManualJobFromDraft(draft, {
    createId: createClientId,
    now: () => new Date().toISOString(),
  });
  const job = draft.jobId ? { ...generatedJob, id: draft.jobId } : generatedJob;

  return {
    id: draft.id || `application-${job.id}`,
    job,
    status: draft.status,
    appliedAt: new Date().toISOString(),
    nextStep: "",
    notes: "",
    documents: draft.documents,
  };
}

function mergeSkillLists(currentSkills: string[], importedSkills: string[]) {
  return mergeSkillListsModel(currentSkills, importedSkills);
}

type AppWorkspaceRootProps = {
  route: AppRoute;
  demoMode: boolean;
  jobsState: ReturnType<typeof useJobs>;
  jobSearchState: ReturnType<typeof useJobSearch>;
  applicationState: ReturnType<typeof useApplications>;
  applicationEventState: ReturnType<typeof useApplicationEvents>;
  profileState: ReturnType<typeof useProfile>;
  appSettingsState: ReturnType<typeof useAppSettings>;
  activityFeed: ReturnType<typeof useActivityFeed>;
  assistantLaunch: AssistantLaunch | null;
  onAssistantLaunchHandled: () => void;
  onNavigate: (view: View, selectedEntityId?: string) => void;
  onOpenAssistant: (
    prompt?: string,
    contextKind?: AssistantLaunch["contextKind"],
    contextId?: string,
    autoSubmit?: boolean,
  ) => void;
};

export function AppWorkspaceRoot({
  route,
  demoMode,
  jobsState,
  jobSearchState,
  applicationState,
  applicationEventState,
  profileState,
  appSettingsState,
  activityFeed,
  assistantLaunch,
  onAssistantLaunchHandled,
  onNavigate,
  onOpenAssistant,
}: AppWorkspaceRootProps) {
  const activeView = route.view;
  const jobList = jobsState.jobs;
  const setJobList = jobsState.updateCached;
  const selectedJobId = route.jobId ?? "";
  const [query, setQuery] = useState("");
  const [activeTab, setActiveTab] = useState(tabs[0]);
  const [pendingAiMatchFocus, setPendingAiMatchFocus] = useState<"analysis" | "recommendations" | null>(null);
  const aiMatchAnalysisRef = useRef<HTMLElement | null>(null);
  const aiMatchRecommendationsRef = useRef<HTMLElement | null>(null);
  const savedJobs = jobsState.savedJobIds;
  const areSavedJobsLoaded = !jobsState.isLoading;
  const archivedJobIds = jobsState.archivedJobIds;
  const deletedJobIds = jobsState.deletedJobIds;
  const [showSavedJobs, setShowSavedJobs] = useState(false);
  const [showArchivedJobs, setShowArchivedJobs] = useState(false);
  const applications = applicationState.applications;
  const setApplications = applicationState.updateCached;
  const selectedApplicationId = route.applicationId ?? "";
  const workspaceApplicationId = route.applicationId ?? null;
  const areApplicationsLoaded = !applicationState.isLoading;
  const [matchingApplicationIds, setMatchingApplicationIds] = useState<string[]>([]);
  const applicationEvents = applicationEventState.events;
  const areApplicationEventsLoaded = !applicationEventState.isLoading;
  const [jobFilters, setJobFilters] = useState<JobFilters>(defaultJobFilters);
  const [sortBy, setSortBy] = useState<JobSortBy>("AI Match");
  const [isAnalysisMenuOpen, setIsAnalysisMenuOpen] = useState(false);
  const [bulkAnalysisScope, setBulkAnalysisScope] = useState<BulkAnalysisScope | null>(null);
  const [isManualJobDialogOpen, setIsManualJobDialogOpen] = useState(false);
  const [manualJobDraft, setManualJobDraft] = useState<ManualJobDraft>(defaultManualJobDraft);
  const [isParserDialogOpen, setIsParserDialogOpen] = useState(false);
  const [parserSearchStatus, setParserSearchStatus] = useState<ParserSearchStatus>("idle");
  const [parserSearchMessage, setParserSearchMessage] = useState("");
  const [newLinkedInProfession, setNewLinkedInProfession] = useState("");
  const [forceMatchingJobId, setForceMatchingJobId] = useState("");
  const [aiMatchErrorMessage, setAiMatchErrorMessage] = useState("");
  const [parserSearchForm, setParserSearchForm] = useState<ParserSearchForm>(defaultParserSearchForm);
  const hasParserSearchInteractionRef = useRef(false);
  const [activeSearchSource, setActiveSearchSource] = useState<ActiveSearchSource>("linkedin");
  const [sourceSearchDrafts, setSourceSearchDrafts] = useState<Partial<Record<ParserId, SourceSearchDraft>>>({});
  const parserSearchConfigs = jobSearchState.configs;
  const [selectedParserSearchConfigId, setSelectedParserSearchConfigId] = useState("");
  const sourceSearchConfigs = jobSearchState.sourceConfigs;
  const [selectedSourceConfigIds, setSelectedSourceConfigIds] = useState<Partial<Record<ParserId, string>>>({});
  const profile = profileState.profile;
  const setProfile = profileState.updateCachedProfile;
  const [profileDraft, setProfileDraft] = useState<CandidateProfile>(defaultCandidateProfile);
  const [profileAvatarDraftFile, setProfileAvatarDraftFile] = useState<File | null>(null);
  const [profileAvatarUseDefault, setProfileAvatarUseDefault] = useState(false);
  const isProfileLoaded = !profileState.isLoading;
  const [isProfileDialogOpen, setIsProfileDialogOpen] = useState(false);
  const [isExperienceDialogOpen, setIsExperienceDialogOpen] = useState(false);
  const [isExperienceEditMode, setIsExperienceEditMode] = useState(false);
  const [experienceDraft, setExperienceDraft] = useState<ExperienceEntry>(defaultExperienceDraft);
  const [isExperienceImporting, setIsExperienceImporting] = useState(false);
  const [experienceImportMessage, setExperienceImportMessage] = useState("");
  const [isEducationDialogOpen, setIsEducationDialogOpen] = useState(false);
  const [isEducationEditMode, setIsEducationEditMode] = useState(false);
  const [educationDraft, setEducationDraft] = useState<EducationEntry>(defaultEducationDraft);
  const [isEducationImporting, setIsEducationImporting] = useState(false);
  const [educationImportMessage, setEducationImportMessage] = useState("");
  const [isDocumentDialogOpen, setIsDocumentDialogOpen] = useState(false);
  const [isDocumentEditMode, setIsDocumentEditMode] = useState(false);
  const [documentDraft, setDocumentDraft] = useState<DocumentEntry>(defaultDocumentDraft);
  const [isPreferencesDialogOpen, setIsPreferencesDialogOpen] = useState(false);
  const [preferencesDraft, setPreferencesDraft] = useState<JobPreferences>(defaultJobPreferences);
  const [preferenceInputs, setPreferenceInputs] = useState<PreferenceInputs>(defaultPreferenceInputs);
  const [isSkillsDialogOpen, setIsSkillsDialogOpen] = useState(false);
  const [skillsDraft, setSkillsDraft] = useState<string[]>([]);
  const [skillInput, setSkillInput] = useState("");
  const [isSkillsImporting, setIsSkillsImporting] = useState(false);
  const [skillsImportMessage, setSkillsImportMessage] = useState("");
  const [isDealbreakersDialogOpen, setIsDealbreakersDialogOpen] = useState(false);
  const [dealbreakersDraft, setDealbreakersDraft] = useState<string[]>([]);
  const [dealbreakerInput, setDealbreakerInput] = useState("");
  const [isAdditionalNotesDialogOpen, setIsAdditionalNotesDialogOpen] = useState(false);
  const [additionalNotesDraft, setAdditionalNotesDraft] = useState("");
  const [profileSaveStatus, setProfileSaveStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [profileSaveMessage, setProfileSaveMessage] = useState("");
  const {
    settings: appSettings,
    connection: settingsConnection,
    ai: aiSettings,
  } = appSettingsState;
  const { settings: uiSettings, updateSettings: updateUiSettings } = useUiSettings();
  const {
    entries: appLogs,
    append: appendAppLog,
    clear: clearAppLogs,
  } = activityFeed;
  const loggedProfileWarningsRef = useRef(new Set<string>());
  const loggedApplicationWarningsRef = useRef(new Set<string>());

  useEffect(() => {
    for (const warning of profileState.warnings) {
      if (loggedProfileWarningsRef.current.has(warning)) continue;
      loggedProfileWarningsRef.current.add(warning);
      appendAppLog({ level: "warning", area: "Profile", message: warning });
    }
  }, [appendAppLog, profileState.warnings]);

  useEffect(() => {
    for (const warning of applicationState.warnings) {
      if (loggedApplicationWarningsRef.current.has(warning)) continue;
      loggedApplicationWarningsRef.current.add(warning);
      appendAppLog({ level: "warning", area: "Applications", message: warning });
    }
  }, [appendAppLog, applicationState.warnings]);
  const availableJobs = useMemo(
    () => selectAvailableJobs(jobList, archivedJobIds, deletedJobIds),
    [archivedJobIds, deletedJobIds, jobList],
  );

  const archivedJobsCount = useMemo(
    () => countArchivedJobs(availableJobs),
    [availableJobs],
  );
  const savedJobsCount = useMemo(
    () => countSavedJobs(availableJobs, savedJobs),
    [availableJobs, savedJobs],
  );
  const recentAnalysisJobs = getBulkAnalysisCandidates(
    availableJobs,
    "recent",
    Date.now(),
  );
  const missingAnalysisJobs = getBulkAnalysisCandidates(
    availableJobs,
    "missing",
    Date.now(),
  );

  const locationFilterOptions = useMemo(
    () => selectJobFilterOptions(availableJobs, "location"),
    [availableJobs],
  );

  const typeFilterOptions = useMemo(
    () => selectJobFilterOptions(availableJobs, "type"),
    [availableJobs],
  );

  const jobFilterControls: Array<{
    key: JobFilterKey;
    label: string;
    icon: LucideIcon;
    options: Array<{ value: string; label: string }>;
  }> = [
    { key: "location", label: "Location", icon: MapPin, options: locationFilterOptions },
    { key: "remote", label: "Remote", icon: Monitor, options: remoteFilterOptions },
    { key: "salary", label: "Salary", icon: DollarSign, options: salaryFilterOptions },
    { key: "experience", label: "Experience", icon: ChartNoAxesColumnIncreasing, options: experienceFilterOptions },
    { key: "type", label: "Job Type", icon: BriefcaseBusiness, options: typeFilterOptions },
    { key: "match", label: "AI Match", icon: Sparkles, options: matchFilterOptions },
  ];

  const filteredJobs = useMemo(
    () =>
      selectFilteredJobs({
        jobs: availableJobs,
        filters: jobFilters,
        query,
        savedJobIds: savedJobs,
        showArchivedJobs,
        showSavedJobs,
        sortBy,
        nowMs: Date.now(),
      }),
    [availableJobs, jobFilters, query, savedJobs, showArchivedJobs, showSavedJobs, sortBy],
  );

  const selectedJob = filteredJobs.find((job) => job.id === selectedJobId) ?? filteredJobs[0] ?? null;
  const selectedJobPostingUrl = selectedJob ? getJobApplyUrl(selectedJob) : "";
  const isSelectedSaved = selectedJob ? savedJobs.includes(selectedJob.id) : false;
  const selectedJobPreparation = selectedJob
    ? applications.find((application) => application.job.id === selectedJob.id)
    : undefined;
  const selectedJobApplication = selectedJobPreparation?.status === "draft" ? undefined : selectedJobPreparation;
  const trackedApplications = useMemo(
    () => applications.filter((application) => application.status !== "draft"),
    [applications],
  );
  const trackedApplicationIds = useMemo(
    () => new Set(trackedApplications.map((application) => application.id)),
    [trackedApplications],
  );
  const trackedApplicationEvents = useMemo(
    () => applicationEvents.filter((event) => trackedApplicationIds.has(event.applicationId)),
    [applicationEvents, trackedApplicationIds],
  );
  const selectedApplication = trackedApplications.find((application) => application.id === selectedApplicationId) ?? trackedApplications[0] ?? null;
  const workspaceApplication = findWorkspaceApplication(applications, workspaceApplicationId);

  useEffect(() => {
    if (activeView !== "Jobs" || jobsState.isLoading) return;
    if (!selectedJob) {
      if (route.jobId) onNavigate("Jobs");
      return;
    }
    if (route.jobId === selectedJob.id) return;
    onNavigate("Jobs", selectedJob.id);
  }, [activeView, jobsState.isLoading, onNavigate, route.jobId, selectedJob]);

  useEffect(() => {
    if (activeView !== "Applications" || applicationState.isLoading) return;
    if (!selectedApplication) {
      if (route.applicationId) onNavigate("Applications");
      return;
    }
    if (route.applicationId === selectedApplication.id) return;
    onNavigate("Applications", selectedApplication.id);
  }, [
    activeView,
    applicationState.isLoading,
    onNavigate,
    route.applicationId,
    selectedApplication,
  ]);

  function openAiMatchSection(section: "analysis" | "recommendations") {
    setActiveTab("AI Match");
    setPendingAiMatchFocus(section);
  }

  async function refreshStoredJobsFromServer(signal?: AbortSignal) {
    if (signal?.aborted) return [];
    const result = await jobsState.refetch();
    return keepStoredUserJobs(result.data?.jobs ?? []);
  }

  useEffect(() => {
    if (!screenshotSessionId) return;
    if (
      window.localStorage.getItem(screenshotSessionStorageKey) ===
      screenshotSessionId
    ) {
      return;
    }

    for (const key of Object.keys(window.localStorage)) {
      if (key.startsWith(browserStorageNamespacePrefix)) {
        window.localStorage.removeItem(key);
      }
    }
    window.localStorage.setItem(screenshotSessionStorageKey, screenshotSessionId);
  }, []);

  useEffect(() => {
    if (activeTab !== "AI Match" || !pendingAiMatchFocus) return;

    const frame = window.requestAnimationFrame(() => {
      const target = pendingAiMatchFocus === "recommendations" ? aiMatchRecommendationsRef.current : aiMatchAnalysisRef.current;
      target?.scrollIntoView({ behavior: "smooth", block: "start" });
      target?.focus({ preventScroll: true });
      setPendingAiMatchFocus(null);
    });

    return () => window.cancelAnimationFrame(frame);
  }, [activeTab, pendingAiMatchFocus, selectedJob?.id]);

  useEffect(() => {
    const defaultSelection = getDefaultLinkedInSearchSelection(
      parserSearchConfigs,
      sourceSearchConfigs,
    );
    if (!defaultSelection || hasParserSearchInteractionRef.current) return;
    setParserSearchForm(defaultSelection.form);
    setSelectedParserSearchConfigId(defaultSelection.commonConfigId);
    setSelectedSourceConfigIds({ linkedin: defaultSelection.sourceConfigId });
    setSourceSearchDrafts({ linkedin: defaultSelection.draft });
  }, [parserSearchConfigs, sourceSearchConfigs]);

  useEffect(() => {
    if (!jobSearchState.error) return;
    setParserSearchStatus("error");
    setParserSearchMessage(jobSearchState.error.message);
  }, [jobSearchState.error]);

  function changeView(view: View, selectedEntityId?: string) {
    onNavigate(view, selectedEntityId);
  }

  function setSelectedJobId(
    value: string | ((currentId: string) => string),
  ) {
    const nextId = typeof value === "function" ? value(selectedJobId) : value;
    onNavigate("Jobs", nextId || undefined);
  }

  function setSelectedApplicationId(
    value: string | ((currentId: string) => string),
  ) {
    const nextId = typeof value === "function"
      ? value(selectedApplicationId)
      : value;
    onNavigate("Applications", nextId || undefined);
  }

  function openJobFromDashboard(jobId: string) {
    setQuery("");
    setJobFilters(defaultJobFilters);
    setShowSavedJobs(false);
    setShowArchivedJobs(false);
    setActiveTab("Overview");
    changeView("Jobs", jobId);
  }

  function startJobSearchFromDashboard() {
    setIsParserDialogOpen(true);
    changeView("Jobs");
  }

  function openApplicationFromDashboard(applicationId?: string) {
    changeView("Applications", applicationId);
  }

  const openAssistant = onOpenAssistant;

  function updateShowLogs(showLogs: boolean) {
    updateUiSettings({ showLogs });
    appendAppLog({
      level: "info",
      area: "Settings",
      message: showLogs ? "Logs view enabled" : "Logs view disabled",
    });

    if (!showLogs && activeView === "Logs") {
      changeView("Settings");
    }
  }

  function markJobApplied(job: Job) {
    const application = createApplicationFromJob(job);
    const existingApplication = applications.find((item) => item.job.id === job.id);
    const nextApplication = existingApplication
      ? { ...existingApplication, job, status: "applied" as const, appliedAt: new Date().toISOString() }
      : application;
    void applicationState.upsert(nextApplication).catch((error) => appendAppLog({
      level: "error",
      area: "Applications",
      message: error instanceof Error ? error.message : "Application could not be saved",
    }));
    changeView("Applications", nextApplication.id);
  }

  function prepareJobApplication(job: Job) {
    const existingApplication = applications.find((item) => item.job.id === job.id);
    if (existingApplication) {
      updateApplicationJob(existingApplication.id, job);
      changeView("ApplicationWorkspace", existingApplication.id);
    } else {
      const application = createApplicationFromJob(job, "draft");
      void applicationState.upsert(application).catch((error) => appendAppLog({
        level: "error",
        area: "Applications",
        message: error instanceof Error ? error.message : "Application could not be prepared",
      }));
      changeView("ApplicationWorkspace", application.id);
    }
  }

  function openApplicationWorkspace(applicationId: string) {
    changeView("ApplicationWorkspace", applicationId);
  }

  async function addManualApplication(draft: ManualApplicationDraft) {
    const application = { ...createApplicationFromManualDraft(draft), documents: [] };
    try {
      await applicationState.upsert(application);
      const uploadedDocuments: ApplicationDocument[] = [];
      for (const document of draft.documents) {
        let body: Blob | null = document.pendingFile ?? null;
        if (!body && document.downloadUrl) {
          const sourceResponse = await fetch(document.downloadUrl, { cache: "no-store" });
          if (!sourceResponse.ok) {
            throw new Error(await readApiErrorMessage(sourceResponse, "Selected resume could not be loaded"));
          }
          body = await sourceResponse.blob();
        }
        if (!body) throw new Error("Selected resume could not be loaded");
        uploadedDocuments.push(await applicationState.uploadAttachment(application.id, body, {
          fileName: document.fileName,
          title: document.title,
        }));
      }
      if (uploadedDocuments.length > 0) {
        setApplications((currentApplications) => currentApplications.map((item) => (
          item.id === application.id ? { ...item, documents: uploadedDocuments } : item
        )));
      }
    } catch (error) {
      appendAppLog({
        level: "error",
        area: "Applications",
        message: error instanceof Error ? error.message : "Application document could not be uploaded",
      });
      throw error instanceof Error
        ? error
        : new Error("Application document could not be uploaded");
    }
    void analyzeApplicationWithAi(application);
    changeView("Applications", application.id);
  }

  function openManualJobDialog() {
    setManualJobDraft(defaultManualJobDraft);
    setIsManualJobDialogOpen(true);
  }

  function updateManualJobDraft<Field extends keyof ManualJobDraft>(
    field: Field,
    value: ManualJobDraft[Field],
  ) {
    setManualJobDraft((currentDraft) => ({ ...currentDraft, [field]: value }));
  }

  async function addManualJob() {
    if (!manualJobDraft.title.trim() || !manualJobDraft.company.trim() || !manualJobDraft.overview.trim()) {
      return;
    }

    const job = createManualJobFromDraft(manualJobDraft, {
      createId: createClientId,
      now: () => new Date().toISOString(),
    });
    setAiMatchErrorMessage("");
    setQuery("");
    setJobFilters(defaultJobFilters);
    setShowSavedJobs(false);
    setShowArchivedJobs(false);
    setSelectedJobId(job.id);
    setActiveTab("AI Match");
    setJobList((currentJobs) => {
      const nextJobs = mergeJobs([job], currentJobs);
      void persistUserJobs(nextJobs.filter(isUserManagedJob));
      return nextJobs;
    });
    setIsManualJobDialogOpen(false);
    setManualJobDraft(defaultManualJobDraft);
    setForceMatchingJobId(job.id);
    appendAppLog({
      level: "info",
      area: "AI Match",
      message: `Manual vacancy added; analysis started for ${job.title} at ${job.company}`,
    });

    try {
      const completed = await refreshAiMatch(job, true);
      if (completed) {
        appendAppLog({
          level: "success",
          area: "AI Match",
          message: `AI analysis completed for ${job.title} at ${job.company}`,
        });
      }
    } finally {
      setForceMatchingJobId((currentId) => (currentId === job.id ? "" : currentId));
    }
  }

  function updateApplicationJob(applicationId: string, job: Job) {
    const application = applications.find((item) => item.id === applicationId);
    if (!application) return;
    void applicationState.upsert({ ...application, job }).catch((error) => appendAppLog({
      level: "error",
      area: "Applications",
      message: error instanceof Error ? error.message : "Application could not be saved",
    }));
  }

  async function analyzeApplicationWithAi(application: TrackedApplication) {
    setMatchingApplicationIds((currentIds) => Array.from(new Set([...currentIds, application.id])));
    appendAppLog({
      level: "info",
      area: "AI Match",
      message: `AI analysis started for ${application.job.title} at ${application.job.company}`,
    });

    try {
      const payload = await jobsState.matchNow([application.job], true);
      const matchedJob = normalizeStoredJobs(payload.map((item) => item.data)).find((job) => job.id === application.job.id);

      if (!matchedJob) {
        appendAppLog({
          level: "warning",
          area: "AI Match",
          message: "AI analysis completed without a matching job payload",
          details: `${application.job.title} at ${application.job.company}`,
        });
        return;
      }

      const authoritativeApplication = await applicationState.refreshAnalysis(application.id);
      appendAppLog({
        level: "success",
        area: "AI Match",
        message: `AI analysis completed for ${application.job.title} at ${application.job.company}`,
        details: `Score: ${formatMatchValue(authoritativeApplication.job)}`,
      });
    } catch (error) {
      appendAppLog({
        level: "error",
        area: "AI Match",
        message: error instanceof Error ? error.message : "AI analysis failed",
        details: `${application.job.title} at ${application.job.company}`,
      });
    } finally {
      setMatchingApplicationIds((currentIds) => currentIds.filter((id) => id !== application.id));
    }
  }

  function refreshApplicationAnalysis(applicationId: string) {
    const application = applications.find((item) => item.id === applicationId);
    if (!application) return;

    void analyzeApplicationWithAi(application);
  }

  function updateApplicationStatus(applicationId: string, status: ApplicationStatus) {
    const application = applications.find((item) => item.id === applicationId);
    if (!application) return;
    void applicationState.upsert({
      ...application,
      status,
      appliedAt:
        status === "applied" && application.status === "draft"
          ? new Date().toISOString()
          : application.appliedAt,
    }).catch((error) => appendAppLog({
      level: "error",
      area: "Applications",
      message: error instanceof Error ? error.message : "Application status could not be saved",
    }));
  }

  function updateApplicationNotes(applicationId: string, notes: string) {
    const application = applications.find((item) => item.id === applicationId);
    if (!application) return;
    void applicationState.upsert({ ...application, notes }).catch((error) => appendAppLog({
      level: "error",
      area: "Applications",
      message: error instanceof Error ? error.message : "Application notes could not be saved",
    }));
  }

  function updateApplicationDocuments(applicationId: string, documents: ApplicationDocument[]) {
    setApplications((currentApplications) =>
      currentApplications.map((application) =>
        application.id === applicationId
          ? {
              ...application,
              documents,
            }
          : application,
      ),
    );
  }

  function applyProfileResumeUpload(file: {
    id: string;
    fileName: string;
    sizeBytes: number;
    updatedAt: string;
    downloadUrl: string;
  }) {
    const apply = (current: CandidateProfile): CandidateProfile => normalizeCandidateProfile({
      ...current,
      resume_file_id: file.id,
      resume_file_name: file.fileName,
      resume_file_size: formatFileSize(file.sizeBytes),
      resume_updated_at: file.updatedAt,
      resume_download_url: resolveApiUrl(file.downloadUrl),
    });
    setProfile(apply);
    setProfileDraft(apply);
  }

  function attachGeneratedDocumentToApplication(
    applicationId: string,
    document: AssistantDocumentAttachment,
  ) {
    setApplications((currentApplications) =>
      currentApplications.map((application) => {
        if (application.id !== applicationId) return application;
        const generatedDocument: ApplicationDocument = {
          id: `artifact-${document.artifactId}`,
          artifactId: document.artifactId,
          kind: "generated",
          title: document.title,
          fileName: document.fileName,
          fileSize: "",
          fileType: document.fileType,
          uploadedAt: document.uploadedAt,
          downloadUrl: document.downloadUrl,
        };
        const existingIndex = application.documents.findIndex(
          (item) => item.artifactId === document.artifactId,
        );
        const nextDocuments = existingIndex >= 0
          ? application.documents.map((item, index) => (
              index === existingIndex ? generatedDocument : item
            ))
          : [...application.documents, generatedDocument];
        return { ...application, documents: nextDocuments };
      }),
    );
  }

  function syncAssistantAppliedAction(result: AssistantAppliedAction) {
    if (result.resourceKind === "application") {
      const updatedApplication = normalizeStoredApplications([result.resource])[0];
      if (!updatedApplication) return;
      setApplications((currentApplications) => currentApplications.map((application) =>
        application.id === updatedApplication.id
          ? { ...updatedApplication, documents: application.documents }
          : application,
      ));
      return;
    }

    if (result.resourceKind === "event") {
      const createdEvent = normalizeStoredApplicationEvents([result.resource])[0];
      if (!createdEvent) return;
      applicationEventState.updateCached((currentEvents) => sortApplicationEvents([
        createdEvent,
        ...currentEvents.filter((event) => event.id !== createdEvent.id),
      ]));
      return;
    }

    if (result.resourceKind === "profile") {
      const updatedProfile = normalizeCandidateProfile(result.resource as Partial<CandidateProfile>);
      setProfile(updatedProfile);
      setProfileDraft(updatedProfile);
    }
  }

  function deleteApplication(applicationId: string) {
    const deletedEvents = applicationEvents.filter(
      (event) => event.applicationId === applicationId,
    );
    const nextApplicationId = applications.find((application) => application.id !== applicationId)?.id ?? "";
    setSelectedApplicationId((currentId) => currentId === applicationId ? nextApplicationId : currentId);
    applicationEventState.removeForApplication(applicationId);

    void applicationState.remove(applicationId).then(
      () => undefined,
      (error) => {
        setSelectedApplicationId((currentId) => currentId || applicationId);
        if (deletedEvents.length > 0) {
          applicationEventState.updateCached((currentEvents) =>
            sortApplicationEvents([
              ...deletedEvents,
              ...currentEvents.filter(
                (event) => event.applicationId !== applicationId,
              ),
            ]),
          );
        }

        const message =
          error instanceof Error
            ? error.message
            : "Application could not be deleted";
        appendAppLog({
          level: "error",
          area: "Applications",
          message,
        });
        window.alert(message);
      },
    );
  }

  function saveApplicationEvent(event: ApplicationEvent) {
    if (event.outcome === "negative") {
      updateApplicationStatus(event.applicationId, "rejected");
    }

    void applicationEventState.upsert(event).catch((error) => {
      appendAppLog({
        level: "error",
        area: "Applications",
        message:
          error instanceof Error
            ? error.message
            : "Application event could not be saved",
      });
    });
  }

  function deleteApplicationEvent(eventId: string) {
    void applicationEventState.remove(eventId).catch((error) => {
      appendAppLog({
        level: "error",
        area: "Applications",
        message:
          error instanceof Error
            ? error.message
            : "Application event could not be deleted",
      });
    });
  }

  function toggleSaved(jobId: string) {
    void jobsState.patchState(jobId, { saved: !savedJobs.includes(jobId) }).catch(() => undefined);
  }

  function updateJobArchiveState(job: Job, archived: boolean) {
    const archivedAt = archived ? new Date().toISOString() : undefined;
    setJobList((currentJobs) => {
      return currentJobs.map((item) =>
        item.id === job.id
          ? {
              ...item,
              archived,
              archivedAt,
            }
          : item,
      );
    });
    void jobsState.patchState(job.id, { archived }).catch(() => undefined);

    setSelectedJobId("");
  }

  function deleteJob(job: Job) {
    const existingApplication = applications.find((application) => application.job.id === job.id);
    const shouldDelete = window.confirm(
      existingApplication
        ? `Delete ${job.title} at ${job.company} from Jobs? The application record will stay in Applications.`
        : `Delete ${job.title} at ${job.company}?`,
    );

    if (!shouldDelete) return;

    setSelectedJobId("");
    void jobsState.remove(job.id).catch(() => undefined);
  }

  function updateJobFilter(filter: JobFilterKey, value: string) {
    setJobFilters((current) => ({ ...current, [filter]: value }));
    setSelectedJobId("");
    setActiveTab("Overview");
  }

  function clearAllJobFilters() {
    setQuery("");
    setJobFilters(defaultJobFilters);
    setSortBy("AI Match");
    setShowSavedJobs(false);
    setShowArchivedJobs(false);
    setSelectedJobId("");
    setActiveTab("Overview");
  }

  function updateParserSearchForm<Field extends keyof typeof parserSearchForm>(
    field: Field,
    value: (typeof parserSearchForm)[Field],
  ) {
    hasParserSearchInteractionRef.current = true;
    setParserSearchForm((current) => {
      const next = { ...current, [field]: value };
      if (
        activeSearchSource !== "direct_companies" &&
        field !== "parsers" &&
        field !== "directCompaniesEnabled" &&
        field !== "directCompanyIds" &&
        field !== "searchName" &&
        field !== "folder"
      ) {
        setSourceSearchDrafts((drafts) => ({
          ...drafts,
          [activeSearchSource]: sourceSearchDraftFromForm(next),
        }));
      }
      return next;
    });
    setParserSearchStatus("idle");
    setParserSearchMessage("");
  }

  function addLinkedInProfession() {
    const keyword = newLinkedInProfession.trim();
    if (!keyword) return;

    const normalizedKeyword = keyword.toLocaleLowerCase();
    if (
      parserSearchForm.linkedinQueries.some(
        (query) =>
          query.keyword.trim().toLocaleLowerCase() === normalizedKeyword,
      )
    ) {
      setParserSearchStatus("error");
      setParserSearchMessage(`“${keyword}” is already in this LinkedIn config`);
      return;
    }

    updateParserSearchForm("linkedinQueries", [
      ...parserSearchForm.linkedinQueries,
      {
        keyword,
        experienceLevels: [...defaultLinkedInProfessionExperienceLevels],
        jobType: null,
        selectiveSearch: true,
      },
    ]);
    setNewLinkedInProfession("");
  }

  function removeLinkedInProfession(queryIndex: number) {
    updateParserSearchForm(
      "linkedinQueries",
      parserSearchForm.linkedinQueries.filter(
        (_, index) => index !== queryIndex,
      ),
    );
  }

  function toggleParser(parser: ParserId) {
    hasParserSearchInteractionRef.current = true;
    setParserSearchForm((current) => {
      const isSelected = current.parsers.includes(parser);
      return {
        ...current,
        parsers: isSelected
          ? current.parsers.filter((selectedParser) => selectedParser !== parser)
          : [...current.parsers, parser],
      };
    });
    setParserSearchStatus("idle");
    setParserSearchMessage("");
  }

  function sourceDraftFor(source: ParserId): SourceSearchDraft {
    const existingDraft = sourceSearchDrafts[source];
    if (existingDraft) return existingDraft;

    const selectedConfigId = selectedSourceConfigIds[source];
    const selectedConfig = sourceSearchConfigs.find(
      (config) => config.id === selectedConfigId && config.source === source,
    );
    const commonConfig = parserSearchConfigs.find(
      (config) =>
        config.id ===
        (selectedConfig?.configId ?? selectedParserSearchConfigId),
    );
    return selectedConfig
      ? sourceSearchDraftFromFilters(
          selectedConfig.filters,
          commonConfig?.form ?? defaultParserSearchForm,
        )
      : sourceSearchDraftFromForm(defaultParserSearchForm);
  }

  function activateSearchSource(source: ActiveSearchSource) {
    hasParserSearchInteractionRef.current = true;
    setActiveSearchSource(source);
    if (source !== "direct_companies") {
      const draft = sourceDraftFor(source);
      setSourceSearchDrafts((current) => ({ ...current, [source]: draft }));
      setParserSearchForm((current) => ({ ...current, ...draft }));
    }
    setParserSearchStatus("idle");
    setParserSearchMessage("");
  }

  function toggleDirectCompanies() {
    hasParserSearchInteractionRef.current = true;
    setParserSearchForm((current) => {
      const directCompaniesEnabled = !current.directCompaniesEnabled;
      return {
        ...current,
        directCompaniesEnabled,
        parsers:
          !directCompaniesEnabled && current.parsers.length === 0
            ? [...defaultParserSearchForm.parsers]
            : current.parsers,
      };
    });
    setParserSearchStatus("idle");
    setParserSearchMessage("");
  }

  function updateSelectedDirectCompanies(companyIds: string[]) {
    hasParserSearchInteractionRef.current = true;
    setParserSearchForm((current) => ({
      ...current,
      directCompanyIds: normalizeDirectCompanyIds(companyIds),
    }));
    setParserSearchStatus("idle");
    setParserSearchMessage("");
  }

  function resetParserSearch() {
    hasParserSearchInteractionRef.current = true;
    const defaultSelection = getDefaultLinkedInSearchSelection(
      parserSearchConfigs,
      sourceSearchConfigs,
    );
    setParserSearchForm(
      defaultSelection?.form ?? { ...defaultParserSearchForm },
    );
    setActiveSearchSource("linkedin");
    setSourceSearchDrafts(
      defaultSelection ? { linkedin: defaultSelection.draft } : {},
    );
    setSelectedParserSearchConfigId(
      defaultSelection?.commonConfigId ?? "",
    );
    setSelectedSourceConfigIds(
      defaultSelection
        ? { linkedin: defaultSelection.sourceConfigId }
        : {},
    );
    setParserSearchStatus("idle");
    setParserSearchMessage("");
  }

  function selectSourceSearchConfig(source: ParserId, configId: string) {
    hasParserSearchInteractionRef.current = true;
    const selectedConfig = sourceSearchConfigs.find(
      (config) => config.id === configId && config.source === source,
    );
    setSelectedSourceConfigIds((current) => {
      const next = { ...current };
      if (!selectedConfig) {
        delete next[source];
        return next;
      }
      next[source] = selectedConfig.id;
      return next;
    });
    if (selectedConfig) {
      setSelectedParserSearchConfigId(selectedConfig.configId);
    }
    const commonConfig = parserSearchConfigs.find(
      (config) =>
        config.id ===
        (selectedConfig?.configId ?? selectedParserSearchConfigId),
    );
    const draft = selectedConfig
      ? sourceSearchDraftFromFilters(
          selectedConfig.filters,
          commonConfig?.form ?? defaultParserSearchForm,
        )
      : sourceSearchDraftFromForm(defaultParserSearchForm);
    setSourceSearchDrafts((current) => ({ ...current, [source]: draft }));
    if (activeSearchSource === source) {
      setParserSearchForm((current) => ({
        ...current,
        ...draft,
        ...(commonConfig
          ? {
              searchName: commonConfig.name,
              folder: commonConfig.form.folder,
            }
          : {}),
      }));
    }
    setParserSearchStatus("idle");
    setParserSearchMessage("");
  }

  async function saveSourceSearchConfig(source: ParserId) {
    if (!selectedParserSearchConfigId) {
      setParserSearchStatus("error");
      setParserSearchMessage("Save or select the common profile first");
      return;
    }
    const existingId = selectedSourceConfigIds[source];
    const commonConfig = parserSearchConfigs.find(
      (config) => config.id === selectedParserSearchConfigId,
    );
    const sourceLabel = getParserLabel(source);
    const sourceForm = {
      ...parserSearchForm,
      ...(sourceSearchDrafts[source] ?? sourceSearchDraftFromForm(parserSearchForm)),
    };
    setParserSearchStatus("loading");
    setParserSearchMessage(
      `${existingId ? "Updating" : "Creating"} ${sourceLabel} query config...`,
    );
    try {
      const saved = await jobSearchState.saveSourceConfig({
        id: existingId || undefined,
        data: {
            name: `${commonConfig?.name ?? (parserSearchForm.searchName || "Search")} · ${sourceLabel}`,
            ...(!existingId
              ? {
                  configId: selectedParserSearchConfigId,
                  source,
                }
              : {}),
            filters: sourceSearchFiltersFromForm(sourceForm),
        },
      });
      setSelectedSourceConfigIds((current) => ({ ...current, [source]: saved.id }));
      setParserSearchStatus("ready");
      setParserSearchMessage(`Saved ${sourceLabel} query config`);
    } catch (error) {
      setParserSearchStatus("error");
      setParserSearchMessage(
        error instanceof Error ? error.message : `${sourceLabel} config save failed`,
      );
    }
  }

  async function saveAppSettings(apiKey: string) {
    await settingsConnection.save({ brightdata_api_key: apiKey });
  }

  async function saveAiSettings(update: AppSettingsUpdate) {
    try {
      await aiSettings.save(update);
    } catch {}
  }

  function openProfileEditor() {
    setProfileDraft(profile);
    setProfileAvatarDraftFile(null);
    setProfileAvatarUseDefault(false);
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsProfileDialogOpen(true);
  }

  function closeProfileEditor() {
    setProfileAvatarDraftFile(null);
    setProfileAvatarUseDefault(false);
    setIsProfileDialogOpen(false);
  }

  function openExperienceEditor(experience?: ExperienceEntry) {
    setExperienceDraft(experience ? normalizeExperienceEntry(experience) : { ...defaultExperienceDraft, id: createClientId("experience") });
    setIsExperienceEditMode(Boolean(experience));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsExperienceDialogOpen(true);
  }

  function openEducationEditor(education?: EducationEntry) {
    setEducationDraft(education ? normalizeEducationEntry(education) : { ...defaultEducationDraft, id: createClientId("education") });
    setIsEducationEditMode(Boolean(education));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsEducationDialogOpen(true);
  }

  function openDocumentEditor(document?: DocumentEntry) {
    setDocumentDraft(document ? normalizeDocumentEntry(document) : { ...defaultDocumentDraft, id: createClientId("document") });
    setIsDocumentEditMode(Boolean(document));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsDocumentDialogOpen(true);
  }

  function openPreferencesEditor() {
    setPreferencesDraft(parseJobPreferences(profile.job_preferences));
    setPreferenceInputs(defaultPreferenceInputs);
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsPreferencesDialogOpen(true);
  }

  function openSkillsEditor() {
    setSkillsDraft(parseProfileLines(profile.skills));
    setSkillInput("");
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsSkillsDialogOpen(true);
  }

  function openDealbreakersEditor() {
    setDealbreakersDraft(parseProfileLines(profile.dealbreakers));
    setDealbreakerInput("");
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsDealbreakersDialogOpen(true);
  }

  function openAdditionalNotesEditor() {
    setAdditionalNotesDraft(profile.additional_notes);
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsAdditionalNotesDialogOpen(true);
  }

  function addSkillToDraft(skill: string) {
    const normalizedSkill = skill.trim();
    if (!normalizedSkill) return;

    setSkillsDraft((currentSkills) => {
      const existingSkills = new Set(currentSkills.map((item) => item.toLowerCase()));
      if (existingSkills.has(normalizedSkill.toLowerCase())) {
        return currentSkills;
      }

      return [...currentSkills, normalizedSkill];
    });
    setSkillInput("");
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function removeSkillFromDraft(skill: string) {
    setSkillsDraft((currentSkills) => currentSkills.filter((item) => item !== skill));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function addDealbreakerToDraft(dealbreaker: string) {
    const normalizedDealbreaker = dealbreaker.trim();
    if (!normalizedDealbreaker) return;

    setDealbreakersDraft((currentDealbreakers) => {
      const existingDealbreakers = new Set(currentDealbreakers.map((item) => item.toLowerCase()));
      if (existingDealbreakers.has(normalizedDealbreaker.toLowerCase())) {
        return currentDealbreakers;
      }

      return [...currentDealbreakers, normalizedDealbreaker];
    });
    setDealbreakerInput("");
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function removeDealbreakerFromDraft(dealbreaker: string) {
    setDealbreakersDraft((currentDealbreakers) => currentDealbreakers.filter((item) => item !== dealbreaker));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function clearDealbreakersDraft() {
    setDealbreakersDraft([]);
    setDealbreakerInput("");
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function updateProfileDraft<Field extends keyof CandidateProfile>(
    field: Field,
    value: CandidateProfile[Field],
  ) {
    setProfileDraft((current) => ({ ...current, [field]: value }));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function updatePreferencesDraft<Field extends keyof JobPreferences>(
    field: Field,
    value: JobPreferences[Field],
  ) {
    setPreferencesDraft((current) => {
      const noPreferenceField =
        field === "salary_min"
          ? "salary"
          : field === "work_authorization" || field === "swiss_permit_status"
            ? "work_authorization"
            : (["desired_roles", "seniority", "locations", "work_formats", "employment_types", "industries", "languages", "company_sizes", "priorities"] as string[]).includes(field)
              ? (field as PreferenceAnyField)
              : "";

      return normalizeJobPreferences({
        ...current,
        [field]: value,
        no_preference: noPreferenceField
          ? current.no_preference.filter((item) => item !== noPreferenceField)
          : current.no_preference,
      });
    });
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function updatePreferenceInput(field: PreferenceListField, value: string) {
    setPreferenceInputs((current) => ({ ...current, [field]: value }));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function addPreferenceListItem(field: PreferenceListField) {
    const values = preferenceInputs[field]
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (values.length === 0) return;

    setPreferencesDraft((current) =>
      normalizeJobPreferences({
        ...current,
        [field]: [...current[field], ...values],
        no_preference: current.no_preference.filter((item) => item !== field),
      }),
    );
    setPreferenceInputs((current) => ({ ...current, [field]: "" }));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function removePreferenceListItem(field: PreferenceListField, value: string) {
    setPreferencesDraft((current) =>
      normalizeJobPreferences({
        ...current,
        [field]: current[field].filter((item) => item !== value),
      }),
    );
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function togglePreferenceOption<Field extends "seniority" | "work_formats" | "employment_types" | "company_sizes" | "priorities">(
    field: Field,
    value: string,
  ) {
    setPreferencesDraft((current) => {
      const existingValues = current[field];
      return normalizeJobPreferences({
        ...current,
        [field]: existingValues.includes(value)
          ? existingValues.filter((item) => item !== value)
          : [...existingValues, value],
        no_preference: current.no_preference.filter((item) => item !== field),
      });
    });
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function setPreferenceAny(field: PreferenceAnyField) {
    setPreferencesDraft((current) => {
      const nextPreferences = normalizeJobPreferences({
        ...current,
        no_preference: current.no_preference.includes(field)
          ? current.no_preference.filter((item) => item !== field)
          : [...current.no_preference, field],
      });

      if (!nextPreferences.no_preference.includes(field)) {
        return nextPreferences;
      }

      if (field === "salary") {
        nextPreferences.salary_min = "";
      } else if (field === "work_authorization") {
        nextPreferences.work_authorization = "";
        nextPreferences.swiss_permit_status = "";
      } else {
        nextPreferences[field] = [];
      }

      return nextPreferences;
    });
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  async function saveProfile() {
    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const profileToSave = profileAvatarUseDefault
        ? { ...profileDraft, avatar_url: defaultCandidateProfile.avatar_url }
        : profileDraft;
      const saved = await profileState.save(profileToSave);
      let normalizedProfile = saved.profile;
      if (profileAvatarDraftFile) {
        await profileState.uploadFile(profileAvatarDraftFile, {
          kind: "avatar",
          fileName: profileAvatarDraftFile.name,
          title: "Profile avatar",
          category: "Avatar",
        });
        normalizedProfile = await profileState.refetch();
      } else if (profileAvatarUseDefault) {
        if (profile.avatar_file_id) {
          await profileState.removeFile(profile.avatar_file_id);
        }
        normalizedProfile = await profileState.refetch();
      }

      setProfileDraft(normalizedProfile);
      setProfileAvatarDraftFile(null);
      setProfileAvatarUseDefault(false);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("Saved to database");
      setIsProfileDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Profile save failed");
    }
  }

  async function saveExperience() {
    const normalizedExperience = normalizeExperienceEntry(experienceDraft);

    if (!normalizedExperience.title || !normalizedExperience.company) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Enter role title and company");
      return;
    }

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    const experienceEntries = parseExperienceEntries(profile.experience);
    const existingExperience = experienceEntries.some((entry) => entry.id === normalizedExperience.id);
    const nextExperienceEntries = existingExperience
      ? experienceEntries.map((entry) => (entry.id === normalizedExperience.id ? normalizedExperience : entry))
      : [...experienceEntries, normalizedExperience];
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      experience: serializeExperienceEntries(nextExperienceEntries),
    });

    try {
      const saved = await profileState.save(nextProfile);
      setProfileDraft(saved.profile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsExperienceDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Experience save failed");
    }
  }

  async function saveEducation() {
    const normalizedEducation = normalizeEducationEntry(educationDraft);

    if (!normalizedEducation.institution || !normalizedEducation.credential) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Enter institution and credential");
      return;
    }

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    const educationEntries = parseEducationEntries(profile.education);
    const existingEducation = educationEntries.some((entry) => entry.id === normalizedEducation.id);
    const nextEducationEntries = existingEducation
      ? educationEntries.map((entry) => (entry.id === normalizedEducation.id ? normalizedEducation : entry))
      : [...educationEntries, normalizedEducation];
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      education: serializeEducationEntries(nextEducationEntries),
    });

    try {
      const saved = await profileState.save(nextProfile);
      setProfileDraft(saved.profile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsEducationDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Education save failed");
    }
  }

  async function saveDocument() {
    const normalizedDocument = normalizeDocumentEntry(documentDraft);

    if (!normalizedDocument.title) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Enter document title");
      return;
    }

    if ((!normalizedDocument.pending_file && !normalizedDocument.download_url) || !normalizedDocument.file_name) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Attach a file");
      return;
    }

    if (normalizedDocument.category === "Cover Letter") {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Cover letters use the built-in template and cannot be added here");
      return;
    }

    if (normalizedDocument.category === "CV / Resume" && !normalizedDocument.file_name.toLowerCase().endsWith(".docx")) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("CV sources must be DOCX files");
      return;
    }

    if (normalizedDocument.category === "CV / Resume" && !normalizedDocument.language) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Select the document language");
      return;
    }

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      if (normalizedDocument.pending_file) {
        const uploaded = await profileState.uploadFile(normalizedDocument.pending_file, {
          kind: "supporting_document",
          fileName: normalizedDocument.file_name,
          title: normalizedDocument.title,
          category: normalizedDocument.category,
          language: normalizedDocument.language,
          issuer: normalizedDocument.issuer,
          notes: normalizedDocument.notes,
        });
        if (isDocumentEditMode && normalizedDocument.id !== uploaded.id) {
          await profileState.removeFile(normalizedDocument.id);
        }
      } else {
        await profileState.updateFile(normalizedDocument.id, {
          title: normalizedDocument.title,
          category: normalizedDocument.category,
          language: normalizedDocument.language,
          issuer: normalizedDocument.issuer,
          notes: normalizedDocument.notes,
        });
      }

      const normalizedProfile = await profileState.refetch();
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsDocumentDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Document save failed");
    }
  }

  async function savePreferences() {
    const normalizedPreferences = normalizeJobPreferences(preferencesDraft);
    if (
      normalizedPreferences.work_authorization === "Swiss permit" &&
      !hasProfileValue(normalizedPreferences.swiss_permit_status) &&
      !normalizedPreferences.no_preference.includes("work_authorization")
    ) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Select Swiss permit status");
      return;
    }

    const nextProfile = normalizeCandidateProfile({
      ...profile,
      job_preferences: serializeJobPreferences(normalizedPreferences),
    });

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const saved = await profileState.save(nextProfile);
      setProfileDraft(saved.profile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsPreferencesDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Preferences save failed");
    }
  }

  async function saveSkills() {
    const normalizedSkills = mergeSkillLists([], skillsDraft);
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      skills: normalizedSkills.join("\n"),
    });

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const saved = await profileState.save(nextProfile);
      setProfileDraft(saved.profile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsSkillsDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Skills save failed");
    }
  }

  async function saveDealbreakers() {
    const normalizedDealbreakers = mergeSkillLists([], dealbreakersDraft);
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      dealbreakers: normalizedDealbreakers.join("\n"),
    });

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const saved = await profileState.save(nextProfile);
      setProfileDraft(saved.profile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsDealbreakersDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Dealbreakers save failed");
    }
  }

  async function saveAdditionalNotes() {
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      additional_notes: additionalNotesDraft.trim(),
    });

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const saved = await profileState.save(nextProfile);
      setProfileDraft(saved.profile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsAdditionalNotesDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Notes save failed");
    }
  }

  async function deleteExperience(experienceId: string) {
    if (!window.confirm("Delete this experience entry?")) return;

    const nextExperienceEntries = parseExperienceEntries(profile.experience).filter((entry) => entry.id !== experienceId);
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      experience: serializeExperienceEntries(nextExperienceEntries),
    });

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const saved = await profileState.save(nextProfile);
      setProfileDraft(saved.profile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Experience delete failed");
      window.alert(error instanceof Error ? error.message : "Experience delete failed");
    }
  }

  async function deleteEducation(educationId: string) {
    if (!window.confirm("Delete this education entry?")) return;

    const nextEducationEntries = parseEducationEntries(profile.education).filter((entry) => entry.id !== educationId);
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      education: serializeEducationEntries(nextEducationEntries),
    });

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const saved = await profileState.save(nextProfile);
      setProfileDraft(saved.profile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Education delete failed");
      window.alert(error instanceof Error ? error.message : "Education delete failed");
    }
  }

  async function deleteDocument(documentId: string) {
    if (!window.confirm("Delete this supporting document?")) return;

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      await profileState.removeFile(documentId);
      const normalizedProfile = await profileState.refetch();
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Document delete failed");
      window.alert(error instanceof Error ? error.message : "Document delete failed");
    }
  }

  async function importExperienceFromCv() {
    if (!profile.resume_file_id || !profile.resume_file_name) {
      setExperienceImportMessage("Attach a resume first");
      window.alert("Attach a resume before importing experience.");
      return;
    }

    setIsExperienceImporting(true);
    setExperienceImportMessage("");
    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const importResult = await profileState.importExperience(profile.resume_file_id);

      const importedEntries = (importResult.experience ?? []).map((entry) =>
        normalizeExperienceEntry({
          ...entry,
          id: entry.id || createClientId("cv-experience"),
        }),
      );

      if (importedEntries.length === 0) {
        setProfileSaveStatus("ready");
        setExperienceImportMessage("AI found no experience entries in the attached CV");
        return;
      }

      const currentEntries = parseExperienceEntries(profile.experience);
      const mergedEntries = mergeExperienceEntries(currentEntries, importedEntries);
      const addedCount = mergedEntries.length - currentEntries.length;

      if (addedCount === 0) {
        setProfileSaveStatus("ready");
        setExperienceImportMessage("No new experience entries found in the attached CV");
        return;
      }

      const nextProfile = normalizeCandidateProfile({
        ...profile,
        experience: serializeExperienceEntries(mergedEntries),
      });
      const saved = await profileState.save(nextProfile);
      setProfileDraft(saved.profile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setExperienceImportMessage(`AI imported ${addedCount} experience entr${addedCount === 1 ? "y" : "ies"} from CV`);
    } catch {
      const message = "AI could not import experience from CV. Please try again.";
      setProfileSaveStatus("error");
      setProfileSaveMessage(message);
      setExperienceImportMessage(message);
    } finally {
      setIsExperienceImporting(false);
    }
  }

  async function importEducationFromCv() {
    if (!profile.resume_file_id || !profile.resume_file_name) {
      setEducationImportMessage("Attach a resume first");
      window.alert("Attach a resume before importing education.");
      return;
    }

    setIsEducationImporting(true);
    setEducationImportMessage("");
    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const importResult = await profileState.importEducation(profile.resume_file_id);

      const importedEntries = (importResult.education ?? []).map((entry) =>
        normalizeEducationEntry({
          ...entry,
          id: entry.id || createClientId("cv-education"),
        }),
      );

      if (importedEntries.length === 0) {
        setProfileSaveStatus("ready");
        setEducationImportMessage("AI found no education entries in the attached CV");
        return;
      }

      const currentEntries = parseEducationEntries(profile.education);
      const mergedEntries = mergeEducationEntries(currentEntries, importedEntries);
      const addedCount = mergedEntries.length - currentEntries.length;

      if (addedCount === 0) {
        setProfileSaveStatus("ready");
        setEducationImportMessage("No new education entries found in the attached CV");
        return;
      }

      const nextProfile = normalizeCandidateProfile({
        ...profile,
        education: serializeEducationEntries(mergedEntries),
      });
      const saved = await profileState.save(nextProfile);
      setProfileDraft(saved.profile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setEducationImportMessage(`AI imported ${addedCount} education entr${addedCount === 1 ? "y" : "ies"} from CV`);
    } catch {
      const message = "AI could not import education from CV. Please try again.";
      setProfileSaveStatus("error");
      setProfileSaveMessage(message);
      setEducationImportMessage(message);
    } finally {
      setIsEducationImporting(false);
    }
  }

  async function importSkillsFromCv() {
    if (!profile.resume_file_id || !profile.resume_file_name) {
      setSkillsImportMessage("Attach a resume first");
      window.alert("Attach a resume before importing skills.");
      return;
    }

    setIsSkillsImporting(true);
    setSkillsImportMessage("");
    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const importResult = await profileState.importSkills(profile.resume_file_id);

      const importedSkills = importResult.skills ?? [];
      if (importedSkills.length === 0) {
        setProfileSaveStatus("ready");
        setSkillsImportMessage("AI found no skills in the attached CV");
        return;
      }

      const currentSkills = parseProfileLines(profile.skills);
      const mergedSkills = mergeSkillLists(currentSkills, importedSkills);
      const addedCount = mergedSkills.length - currentSkills.length;

      if (addedCount === 0) {
        setProfileSaveStatus("ready");
        setSkillsImportMessage("No new skills found in the attached CV");
        return;
      }

      const nextProfile = normalizeCandidateProfile({
        ...profile,
        skills: mergedSkills.join("\n"),
      });
      const saved = await profileState.save(nextProfile);
      setProfileDraft(saved.profile);
      setSkillsDraft(parseProfileLines(saved.profile.skills));
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setSkillsImportMessage(`AI added ${addedCount} new skill${addedCount === 1 ? "" : "s"} from CV`);
    } catch {
      const message = "AI could not import skills from CV. Please try again.";
      setProfileSaveStatus("error");
      setProfileSaveMessage(message);
      setSkillsImportMessage(message);
    } finally {
      setIsSkillsImporting(false);
    }
  }

  function attachDocumentFile(file: File) {
    const isGeneratedDocumentSource = documentDraft.category === "CV / Resume";
    if (isGeneratedDocumentSource && !file.name.toLowerCase().endsWith(".docx")) {
      window.alert("CV sources must be DOCX files so their design can be preserved.");
      return;
    }
    const allowedTypes = new Set([
      "application/pdf",
      "application/msword",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "image/png",
      "image/jpeg",
      "image/webp",
    ]);
    const allowedExtensions = [".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".webp"];
    const lowerFileName = file.name.toLowerCase();
    const hasAllowedExtension = allowedExtensions.some((extension) => lowerFileName.endsWith(extension));

    if (!allowedTypes.has(file.type) && !hasAllowedExtension) {
      window.alert("Upload a PDF, DOC, DOCX, PNG, JPG, or WebP file.");
      return;
    }

    if (file.size > 5_000_000) {
      window.alert("Document file must be under 5MB.");
      return;
    }

    const titleFromFile = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
    setDocumentDraft((current) =>
      normalizeDocumentEntry({
        ...current,
        title: current.title || titleFromFile,
        language: current.language || inferDocumentLanguage(file.name, titleFromFile),
        file_name: file.name,
        file_size: formatFileSize(file.size),
        file_type: file.type || "application/octet-stream",
        uploaded_at: new Date().toISOString(),
        download_url: "",
        pending_file: file,
      }),
    );
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  async function persistUserJobs(userJobs: Job[]) {
    const storedUserJobs = keepStoredUserJobs(userJobs);
    try {
      await jobsState.saveJobs([
        ...storedUserJobs,
        ...jobList.filter((job) => !isUserManagedJob(job)),
      ]);
    } catch {
      // localStorage keeps imported and manually added jobs available when the API is offline.
    }
  }

  function applyAiMatchStatus(status: AiMatchJobStatus) {
    const matchedJobs = normalizeStoredJobs(status.updatedJobs.map((job) => job.data));
    if (matchedJobs.length === 0) return;

    const matchedJobsById = new Map(matchedJobs.map((job) => [job.id, job]));
    setApplications((currentApplications) => currentApplications.map((application) => {
      const matchedJob = matchedJobsById.get(application.job.id);
      return matchedJob ? { ...application, job: matchedJob } : application;
    }));

    setJobList((currentJobs) => {
      return mergeJobs(matchedJobs, currentJobs);
    });
  }

  function reportAiMatchError(message: string, details?: string) {
    setAiMatchErrorMessage(message);
    appendAppLog({
      level: "error",
      area: "AI Match",
      message,
      details,
    });
  }

  async function refreshAiMatches(jobsToMatch: Job[], force = false, conflictRetry = false): Promise<boolean> {
    if (jobsToMatch.length === 0) return true;
    setAiMatchErrorMessage("");

    try {
      let startedStatus: AiMatchJobStatus;
      try {
        startedStatus = await jobsState.startAiMatch(jobsToMatch, force);
      } catch (error) {
        if (error instanceof ApiResponseError && error.status === 409) {
          const previousRunStatus = await pollAiMatchStatus();
          if (!previousRunStatus || conflictRetry) return false;
          return refreshAiMatches(jobsToMatch, force, true);
        }
        throw error;
      }

      if (!startedStatus) {
        const previousRunStatus = await pollAiMatchStatus();
        if (!previousRunStatus || conflictRetry) return false;
        return refreshAiMatches(jobsToMatch, force, true);
      }
      applyAiMatchStatus(startedStatus);
      if (startedStatus.status === "completed") return true;

      const completedStatus = await pollAiMatchStatus();
      return Boolean(completedStatus && (completedStatus.failedJobs?.length ?? 0) === 0);
    } catch (error) {
      const message = error instanceof Error ? error.message : "AI match request failed";
      reportAiMatchError(message);
      return false;
    }
  }

  function refreshAiMatch(job: Job, force = false, conflictRetry = false) {
    return refreshAiMatches([job], force, conflictRetry);
  }

  async function runBulkAiAnalysis(scope: BulkAnalysisScope) {
    const jobsToAnalyze = getBulkAnalysisCandidates(
      availableJobs,
      scope,
      Date.now(),
    );
    if (jobsToAnalyze.length === 0 || bulkAnalysisScope) return;

    setIsAnalysisMenuOpen(false);
    setBulkAnalysisScope(scope);
    appendAppLog({
      level: "info",
      area: "AI Match",
      message: `Bulk AI analysis started for ${jobsToAnalyze.length} vacancies`,
      details: scope === "recent" ? "Vacancies added in the last 24 hours" : "Vacancies without current AI analysis",
    });

    try {
      const completed = await refreshAiMatches(jobsToAnalyze, true);
      if (completed) {
        appendAppLog({
          level: "success",
          area: "AI Match",
          message: `Bulk AI analysis completed for ${jobsToAnalyze.length} vacancies`,
        });
      }
    } finally {
      setBulkAnalysisScope(null);
    }
  }

  async function rerunAiMatch(job: Job) {
    setForceMatchingJobId(job.id);
    try {
      await refreshAiMatch(job, true);
    } finally {
      setForceMatchingJobId((currentId) => (currentId === job.id ? "" : currentId));
    }
  }

  async function pollAiMatchStatus(): Promise<AiMatchJobStatus | null> {
    for (let attempt = 0; attempt < aiMatchStatusPollMaxAttempts; attempt += 1) {
      await wait(aiMatchStatusPollDelayMs);

      let status: AiMatchJobStatus;
      try {
        status = await jobsState.fetchAiMatchStatus();
      } catch (error) {
        reportAiMatchError(error instanceof Error ? error.message : "AI match status check failed");
        return null;
      }
      applyAiMatchStatus(status);

      if (status.status === "completed") {
        const failedJobs = status.failedJobs ?? [];
        if (failedJobs.length > 0) {
          const successfulJobs = Math.max(0, status.processed - failedJobs.length);
          reportAiMatchError(
            `AI analysis completed: ${successfulJobs} succeeded, ${failedJobs.length} failed`,
            failedJobs.map((job) => `${job.id}: ${job.error}`).join("\n"),
          );
        } else {
          setAiMatchErrorMessage("");
        }
        return status;
      }
      if (status.status === "failed") {
        reportAiMatchError(status.error || "AI match run failed");
        return null;
      }
      if (status.status === "idle") {
        reportAiMatchError("AI match run stopped before completing");
        return null;
      }
    }

    reportAiMatchError("AI match status timed out before completing");
    return null;
  }

  async function runParsers() {
    hasParserSearchInteractionRef.current = true;
    const sources = parserSearchSourceIds(parserSearchForm);
    if (sources.length === 0) {
      const message = "Select at least one parser or direct company.";
      setParserSearchStatus("ready");
      setParserSearchMessage(message);
      appendAppLog({
        level: "info",
        area: "Vacancy search",
        message,
      });
      return;
    }
    if (selectedParserSearchConfigId) {
      const missingSourceConfig = parserSearchForm.parsers.find(
        (source) => !selectedSourceConfigIds[source],
      );
      if (missingSourceConfig) {
        activateSearchSource(missingSourceConfig);
        const message = `Select a query config for ${getParserLabel(missingSourceConfig)}`;
        setParserSearchStatus("error");
        setParserSearchMessage(message);
        appendAppLog({
          level: "warning",
          area: "Vacancy search",
          message,
        });
        return;
      }
    }
    const parsersLabel = sources.map(getParserLabel).join(" + ");
    const selectedParserSources = new Set<string>(parserSearchForm.parsers);
    const directSources = sources.filter(
      (source) => !selectedParserSources.has(source),
    );
    const runGroups = new Map<
      string,
      {
        configId: string | null;
        filters?: Record<string, unknown>;
        sources: string[];
        sourceConfigIds: Record<string, string>;
      }
    >();
    const addRunGroup = (
      configId: string,
      groupSources: string[],
      sourceConfigIds: Record<string, string> = {},
    ) => {
      const existing = runGroups.get(configId);
      if (existing) {
        existing.sources.push(...groupSources);
        Object.assign(existing.sourceConfigIds, sourceConfigIds);
        return;
      }
      runGroups.set(configId, {
        configId,
        sources: [...groupSources],
        sourceConfigIds: { ...sourceConfigIds },
      });
    };

    if (selectedParserSearchConfigId && parserSearchForm.parsers.length > 0) {
      for (const source of parserSearchForm.parsers) {
        const sourceConfigId = selectedSourceConfigIds[source];
        const sourceConfig = sourceSearchConfigs.find(
          (config) => config.id === sourceConfigId && config.source === source,
        );
        if (!sourceConfig || !sourceConfigId) {
          activateSearchSource(source);
          const message = `Selected query config for ${getParserLabel(source)} is no longer available`;
          setParserSearchStatus("error");
          setParserSearchMessage(message);
          return;
        }
        addRunGroup(sourceConfig.configId, [source], {
          [source]: sourceConfigId,
        });
      }
    } else if (parserSearchForm.parsers.length > 0) {
      runGroups.set("parsers:inline", {
        configId: null,
        filters: parserSearchFiltersFromForm(parserSearchForm),
        sources: [...parserSearchForm.parsers],
        sourceConfigIds: {},
      });
    }
    if (directSources.length > 0) {
      runGroups.set("direct-companies:inline", {
        configId: null,
        filters: directCompanySearchFiltersFromForm(parserSearchForm),
        sources: directSources,
        sourceConfigIds: {},
      });
    }
    const groupedRuns = [...runGroups.values()];
    setParserSearchStatus("loading");
    setParserSearchMessage(`Searching ${parsersLabel}...`);
    appendAppLog({
      level: "info",
      area: "Vacancy search",
      message: `${parsersLabel} vacancy search started`,
      details: [
        `${groupedRuns.length} independent config ${groupedRuns.length === 1 ? "flow" : "flows"}`,
        directSources.length > 0
          ? `Direct-company direction: ${directCompanyDirections.find((option) => option.id === parserSearchForm.directCompanyDirection)?.label ?? "Any"}`
          : `Keywords: ${parserSearchForm.keywords || "Any"}`,
        `Location: ${parserSearchForm.location || parserSearchForm.country || "Any"}`,
        `Remote: ${parserSearchForm.remote}`,
        `Limit: ${parserSearchForm.resultsLimit || "10"}`,
      ].join("\n"),
    });

    try {
      const runs: JobSearchRunPayload[] = [];
      const requestFailures: Array<{ sources: string[]; message: string }> = [];
      for (const group of groupedRuns) {
        const groupLabel = group.sources.map(getParserLabel).join(" + ");
        setParserSearchMessage(`Searching ${groupLabel}...`);
        const progressPolling = startJobSearchProgressPolling(
          group.sources,
          groupLabel,
          Date.now(),
          appSettings.auto_ai_match_enabled,
        );
        try {
          const run = await jobSearchState.run({
              ...(group.configId
                ? { configId: group.configId }
                : {
                    config: {
                      name:
                        parserSearchForm.searchName.trim() || "Manual search",
                      filters:
                        group.filters ??
                        parserSearchFiltersFromForm(parserSearchForm),
                    },
                  }),
              sources: group.sources,
              sourceConfigIds: group.sourceConfigIds,
              sourceFilters: Object.fromEntries(
                group.sources.flatMap((source) => {
                  if (!selectedParserSources.has(source)) return [];
                  const parserSource = source as ParserId;
                  return [
                    [
                      source,
                      sourceSearchFiltersFromForm({
                        ...parserSearchForm,
                        ...sourceDraftFor(parserSource),
                      }),
                    ],
                  ];
                }),
              ),
              aiAnalysisEnabled: true,
          });
          runs.push(run);
        } catch (error) {
          requestFailures.push({
            sources: group.sources,
            message:
              error instanceof Error ? error.message : `${groupLabel} search failed`,
          });
        } finally {
          progressPolling.stop();
        }
      }
      if (runs.length === 0) {
        throw new Error(
          requestFailures.map((failure) => failure.message).join("; ") ||
            "Vacancy search failed",
        );
      }

      const totals = runs.reduce(
        (current, run) => ({
          jobsFound: current.jobsFound + (run.jobsFound ?? 0),
          jobsScreened: current.jobsScreened + (run.jobsScreened ?? 0),
          jobsPassed: current.jobsPassed + (run.jobsPassed ?? 0),
          jobsRejected: current.jobsRejected + (run.jobsRejected ?? 0),
          jobsUncertain: current.jobsUncertain + (run.jobsUncertain ?? 0),
          jobsDiscoveredNew:
            current.jobsDiscoveredNew + (run.jobsDiscoveredNew ?? 0),
          jobsAdded: current.jobsAdded + (run.jobsAdded ?? 0),
        }),
        {
          jobsFound: 0,
          jobsScreened: 0,
          jobsPassed: 0,
          jobsRejected: 0,
          jobsUncertain: 0,
          jobsDiscoveredNew: 0,
          jobsAdded: 0,
        },
      );
      const sourceErrors = Object.assign(
        {},
        ...runs.map((run) => run.sourceErrors ?? {}),
      ) as Record<string, string>;
      for (const failure of requestFailures) {
        for (const source of failure.sources) {
          sourceErrors[source] = failure.message;
        }
      }
      const refreshedJobs = await refreshStoredJobsFromServer();
      if (totals.jobsAdded > 0 && refreshedJobs.length > 0) {
        setSelectedJobId(refreshedJobs[0].id);
        setActiveTab("Overview");
      }
      const failedSources = Object.entries(sourceErrors).map(([source, error]) =>
        formatParserFailure(getParserLabel(source), error),
      );
      const finalMessage = failedSources.length
        ? `Added ${totals.jobsAdded} of ${totals.jobsFound} vacancies; failed: ${failedSources.join("; ")}`
        : totals.jobsAdded > 0
          ? `Added ${totals.jobsAdded} of ${totals.jobsFound} vacancies from ${parsersLabel}`
          : totals.jobsFound > 0
            ? `Found ${totals.jobsFound} vacancies; all were already saved or deleted`
            : `No vacancies returned from ${parsersLabel}`;
      const warnings = Array.from(
        new Set(runs.flatMap((run) => (run.warning ? [run.warning] : []))),
      );
      const parserMessage = warnings.length
        ? `${finalMessage} · ${warnings.join(" · ")}`
        : finalMessage;
      const message = parserMessage;

      setParserSearchStatus("ready");
      setParserSearchMessage(message);
      appendAppLog({
        level:
          failedSources.length > 0
            ? "warning"
            : totals.jobsAdded > 0
              ? "success"
              : "warning",
        area: "Vacancy search",
        message:
          failedSources.length > 0
            ? `${parsersLabel} search incomplete: provider results were not ready`
            : `${parsersLabel} search finished: ${totals.jobsFound} found, ${totals.jobsPassed} matched config, ${totals.jobsAdded} added`,
        details:
          failedSources.length > 0
            ? Object.entries(sourceErrors)
                .map(([source, error]) => `${getParserLabel(source)}: ${error}`)
                .join("\n")
            : [
                `Screened: ${totals.jobsScreened}`,
                `Matched config: ${totals.jobsPassed}`,
                `Rejected: ${totals.jobsRejected}`,
                `Uncertain: ${totals.jobsUncertain}`,
                `New inventory vacancies: ${totals.jobsDiscoveredNew}`,
                `Added to Jobs: ${totals.jobsAdded}`,
              ].join("\n"),
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Vacancy search failed";
      setParserSearchStatus("error");
      setParserSearchMessage(message);
      appendAppLog({
        level: "error",
        area: "Vacancy search",
        message,
      });
    }
  }

  function startJobSearchProgressPolling(
    sources: string[],
    parsersLabel: string,
    startedAfterMs: number,
    autoAiMatchEnabled: boolean,
  ) {
    let stopped = false;
    let timeoutId: number | null = null;
    let trackedRunId: string | null = null;
    let previousJobsFound = 0;
    let previousJobsScreened = 0;
    let previousJobsAnalyzed = 0;
    let previousPhase: JobSearchProgressPhase | null = null;

    const sameSources = (candidateSources: string[]) =>
      candidateSources.length === sources.length &&
      [...candidateSources].sort().every(
        (source, index) => source === [...sources].sort()[index],
      );

    const poll = async () => {
      if (stopped) return;
      try {
        const runs = await jobSearchState.fetchRuns();
        if (stopped) return;
        {
          const run = trackedRunId
            ? runs.find((candidate) => candidate.id === trackedRunId)
            : runs.find((candidate) => {
                const startedAt = Date.parse(candidate.startedAt);
                return (
                  candidate.runType === "manual" &&
                  Number.isFinite(startedAt) &&
                  startedAt >= startedAfterMs - 5_000 &&
                  sameSources(candidate.sources)
                );
              });

          if (run) {
            trackedRunId = run.id;
            const progress = getJobSearchProgress(
              run,
              parsersLabel,
              (Date.now() - startedAfterMs) / 1_000,
              autoAiMatchEnabled,
            );
            setParserSearchMessage(progress.message);
            if (progress.phase !== previousPhase) {
              if (progress.phase === "parsing") {
                appendAppLog({
                  level: "info",
                  area: "Vacancy search",
                  message: `${parsersLabel} parser is processing the request`,
                  details: "Waiting for the source provider to prepare results.",
                });
              } else if (progress.phase === "screening") {
                appendAppLog({
                  level: "info",
                  area: "Vacancy screening",
                  message: `${parsersLabel} screening started`,
                  details: `${progress.screeningTotal} new vacancies queued for screening.`,
                });
              } else if (progress.phase === "matching") {
                appendAppLog({
                  level: "info",
                  area: "AI Match",
                  message: `${parsersLabel} AI Match started`,
                  details: `${run.jobsAdded} accepted vacancies queued for analysis.`,
                });
              }
              previousPhase = progress.phase;
            }
            if (run.jobsFound > 0 && previousJobsFound === 0) {
              appendAppLog({
                level: "info",
                area: "Vacancy search",
                message: `${parsersLabel} parsing finished: ${run.jobsFound} unique vacancies found`,
                details: [
                  `New inventory vacancies: ${run.jobsDiscoveredNew}`,
                  `Updated inventory vacancies: ${run.jobsDiscoveredUpdated}`,
                  `Already observed: ${run.jobsAlreadyObserved}`,
                ].join("\n"),
              });
            }
            if (run.jobsScreened > previousJobsScreened) {
              appendAppLog({
                level: "info",
                area: "Vacancy screening",
                message: `${parsersLabel}: ${run.jobsScreened} screened, ${run.jobsPassed} matched config`,
                details: [
                  `Rejected: ${run.jobsRejected}`,
                  `Uncertain: ${run.jobsUncertain}`,
                  `Screening errors: ${run.screeningErrors}`,
                  `AI calls: ${run.jobsScreeningAiCalls}`,
                ].join("\n"),
              });
            }
            if (run.jobsAnalyzed > previousJobsAnalyzed) {
              appendAppLog({
                level: "info",
                area: "AI Match",
                message: `${parsersLabel}: ${run.jobsAnalyzed} of ${run.jobsAdded} vacancies analyzed`,
              });
            }
            previousJobsFound = Math.max(previousJobsFound, run.jobsFound);
            previousJobsScreened = Math.max(
              previousJobsScreened,
              run.jobsScreened,
            );
            previousJobsAnalyzed = Math.max(
              previousJobsAnalyzed,
              run.jobsAnalyzed,
            );
          }
        }
      } catch {
        // Progress polling is best-effort; the main POST still owns the result.
      } finally {
        if (!stopped) timeoutId = window.setTimeout(poll, 2_000);
      }
    };

    timeoutId = window.setTimeout(poll, 1_000);
    return {
      stop() {
        stopped = true;
        if (timeoutId !== null) window.clearTimeout(timeoutId);
      },
    };
  }

  return (
    <>
        {activeView === "Dashboard" ? (
          <DashboardView
            profile={profile}
            jobs={availableJobs.filter((job) => !job.archived)}
            applications={trackedApplications}
            events={trackedApplicationEvents}
            isLoading={!isProfileLoaded || !areApplicationsLoaded || !areApplicationEventsLoaded || !areSavedJobsLoaded}
            onStartSearch={startJobSearchFromDashboard}
            onOpenJobs={() => changeView("Jobs")}
            onOpenJob={openJobFromDashboard}
            onOpenApplications={openApplicationFromDashboard}
            onOpenCalendar={() => changeView("Calendar")}
            onOpenAssistant={(prompt, contextKind, contextId) => openAssistant(prompt, contextKind, contextId)}
          />
        ) : activeView === "ApplicationWorkspace" ? (
          <ApplicationWorkspace
            application={workspaceApplication}
            profile={profile}
            backLabel={workspaceApplication?.status === "draft" ? "Jobs" : "Applications"}
            onBack={() => changeView(workspaceApplication?.status === "draft" ? "Jobs" : "Applications")}
            onOpenAssistant={(prompt, applicationId) => openAssistant(prompt, "application", applicationId)}
            onDocumentAttached={attachGeneratedDocumentToApplication}
            onRefreshAnalysis={refreshApplicationAnalysis}
            isAnalysisRefreshing={Boolean(workspaceApplication && matchingApplicationIds.includes(workspaceApplication.id))}
            onMarkApplied={(applicationId) => {
              updateApplicationStatus(applicationId, "applied");
              appendAppLog({
                level: "success",
                area: "Applications",
                message: "Application marked as applied",
              });
            }}
          />
        ) : activeView === "Applications" ? (
          <ApplicationsView
            applications={trackedApplications}
            events={trackedApplicationEvents}
            matchingApplicationIds={matchingApplicationIds}
            profile={profile}
            selectedApplication={selectedApplication}
            onSelectApplication={setSelectedApplicationId}
            onOpenJobs={() => changeView("Jobs")}
            onPrepareApplication={openApplicationWorkspace}
            onAddManualApplication={addManualApplication}
            onChangeStatus={updateApplicationStatus}
            onChangeNotes={updateApplicationNotes}
            onChangeDocuments={updateApplicationDocuments}
            onDeleteApplication={deleteApplication}
            onSaveEvent={saveApplicationEvent}
            onDeleteEvent={deleteApplicationEvent}
            onUploadDocument={applicationState.uploadAttachment}
            onDeleteDocument={applicationState.deleteAttachment}
          />
        ) : activeView === "Calendar" ? (
          <CalendarView
            applications={trackedApplications}
            events={trackedApplicationEvents}
            demoMode={demoMode}
            onOpenAssistant={(prompt, applicationId) => openAssistant(prompt, applicationId ? "application" : "profile", applicationId)}
            onSaveEvent={saveApplicationEvent}
            onDeleteEvent={deleteApplicationEvent}
          />
        ) : activeView === "Assistant" ? (
          <AssistantView
            profile={profile}
            jobs={availableJobs}
            applications={applications}
            launch={assistantLaunch}
            onLaunchHandled={onAssistantLaunchHandled}
            onDocumentAttached={attachGeneratedDocumentToApplication}
            onActionApplied={syncAssistantAppliedAction}
          />
        ) : activeView === "Profile" && !isProfileLoaded ? (
          <section
            aria-busy="true"
            aria-label="Loading profile"
            className="flex min-h-0 min-w-0 flex-1 items-center justify-center text-sm font-semibold text-muted"
          >
            Loading profile...
          </section>
        ) : activeView === "Profile" ? (
          <ProfileView
            profile={profile}
            onProfileResumeUploaded={applyProfileResumeUpload}
            onOpenAssistant={(prompt) => openAssistant(prompt, "profile")}
            onEditProfile={openProfileEditor}
            onAddExperience={() => openExperienceEditor()}
            onEditExperience={openExperienceEditor}
            onDeleteExperience={deleteExperience}
            onImportExperienceFromCv={importExperienceFromCv}
            isExperienceImporting={isExperienceImporting}
            experienceImportMessage={experienceImportMessage}
            onAddEducation={() => openEducationEditor()}
            onEditEducation={openEducationEditor}
            onDeleteEducation={deleteEducation}
            onImportEducationFromCv={importEducationFromCv}
            isEducationImporting={isEducationImporting}
            educationImportMessage={educationImportMessage}
            onAddDocument={() => openDocumentEditor()}
            onEditDocument={openDocumentEditor}
            onDeleteDocument={deleteDocument}
            onEditPreferences={openPreferencesEditor}
            onEditSkills={openSkillsEditor}
            onEditDealbreakers={openDealbreakersEditor}
            onEditAdditionalNotes={openAdditionalNotesEditor}
            onImportSkillsFromCv={importSkillsFromCv}
            isSkillsImporting={isSkillsImporting}
            skillsImportMessage={skillsImportMessage}
          />
        ) : activeView === "Settings" ? (
          <SettingsView
            settings={appSettings}
            showLogs={uiSettings.showLogs}
            status={settingsConnection.status}
            message={
              settingsConnection.error?.message ??
              (settingsConnection.status === "ready"
                ? appSettings.has_brightdata_api_key
                  ? "Bright Data API key saved"
                  : "Bright Data API key cleared"
                : "")
            }
            aiStatus={aiSettings.status}
            aiMessage={
              aiSettings.error?.message ??
              (aiSettings.status === "ready"
                ? "AI backend settings saved and activated"
                : "")
            }
            onConnectionDraftChange={settingsConnection.reset}
            onSaveConnection={saveAppSettings}
            onSaveAi={saveAiSettings}
            onShowLogsChange={updateShowLogs}
          />
        ) : activeView === "Logs" && uiSettings.showLogs ? (
          <LogsView logs={appLogs} onClear={clearAppLogs} />
        ) : (
          <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
            <header className="shrink-0">
              <h1 className="page-title text-[24px] leading-tight text-foreground sm:text-[27px] 2xl:text-[31px]">
                Jobs
              </h1>

              <JobsToolbar
                className="mt-2.5 2xl:mt-4"
                searchQuery={query}
                savedJobsCount={savedJobsCount}
                archivedJobsCount={archivedJobsCount}
                showSavedJobs={showSavedJobs}
                showArchivedJobs={showArchivedJobs}
                isAnalysisMenuOpen={isAnalysisMenuOpen}
                bulkAnalysisScope={bulkAnalysisScope}
                recentAnalysisCount={recentAnalysisJobs.length}
                missingAnalysisCount={missingAnalysisJobs.length}
                onSearchQueryChange={setQuery}
                onAddVacancy={openManualJobDialog}
                onSearchVacancies={() => {
                  setParserSearchStatus("idle");
                  setParserSearchMessage("");
                  setIsParserDialogOpen(true);
                }}
                onToggleSavedJobs={() => {
                  setShowSavedJobs((current) => !current);
                  setShowArchivedJobs(false);
                  setSelectedJobId("");
                  setActiveTab("Overview");
                }}
                onToggleArchivedJobs={() => {
                  setShowArchivedJobs((current) => !current);
                  setShowSavedJobs(false);
                  setSelectedJobId("");
                  setActiveTab("Overview");
                }}
                onAnalysisMenuOpenChange={setIsAnalysisMenuOpen}
                onRunAnalysis={(scope) => void runBulkAiAnalysis(scope)}
                onVacanciesChanged={async () => {
                  await refreshStoredJobsFromServer();
                }}
              />
            </header>

            <div className="mt-3 flex shrink-0 flex-col gap-2 lg:flex-row lg:items-center lg:justify-between 2xl:mt-5 2xl:gap-3">
              <div className="flex flex-wrap gap-1.5 2xl:gap-2">
                {jobFilterControls.map((filter) => (
                  <JobFilterDropdown
                    key={filter.key}
                    filterKey={filter.key}
                    label={filter.label}
                    value={jobFilters[filter.key]}
                    options={filter.options}
                    icon={filter.icon}
                    className={jobFilterWidths[filter.key]}
                    onChange={(value) => updateJobFilter(filter.key, value)}
                  />
                ))}
                <button
                  type="button"
                  onClick={clearAllJobFilters}
                  className={cn(
                    "inline-flex h-8 items-center gap-2 rounded-md border border-border bg-[#fff8f1] px-3 text-xs font-semibold text-[#1d1e1c] shadow-[0_3px_10px_rgba(227,214,197,0.24)] transition hover:border-[#c0bbb6] hover:bg-[#fff3e8] 2xl:h-10 2xl:gap-2.5 2xl:px-5 2xl:text-sm",
                    (query ||
                      hasActiveJobFilters(jobFilters) ||
                      sortBy !== "AI Match") &&
                      "border-accent/60 text-foreground",
                  )}
                >
                  <RotateCcw
                    className="h-4 w-4 shrink-0 text-[#686762] 2xl:h-[18px] 2xl:w-[18px]"
                    strokeWidth={1.9}
                  />
                  Reset
                </button>
              </div>

              <label className="relative inline-flex h-8 w-fit min-w-[146px] items-center gap-1.5 whitespace-nowrap rounded-md bg-[#fff8f1] px-2.5 text-xs font-semibold text-[#1d1e1c] transition hover:bg-[#fff3e8] focus-within:ring-2 focus-within:ring-accent/20 2xl:h-10 2xl:min-w-[184px] 2xl:gap-2 2xl:px-4 2xl:text-sm">
                <SlidersHorizontal className="h-3.5 w-3.5 text-muted 2xl:h-4 2xl:w-4" />
                <select
                  aria-label="Sort jobs"
                  value={sortBy}
                  onChange={(event) =>
                    setSortBy(event.target.value as JobSortBy)
                  }
                  className="h-full min-w-0 flex-1 appearance-none !border-transparent !bg-transparent pr-6 font-semibold outline-none focus-visible:!outline-none"
                >
                  {jobSortOptions.map((option) => (
                    <option key={option} value={option}>
                      Sort by: {option}
                    </option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2.5 h-3.5 w-3.5 text-muted 2xl:right-4 2xl:h-4 2xl:w-4" />
              </label>
            </div>

            {aiMatchErrorMessage ? (
              <div className="mt-2.5 flex shrink-0 items-start gap-2 rounded-md border border-[#fa5d00]/45 bg-[#fa5d00]/13 px-3 py-2 text-xs font-semibold text-[#fa5d00] 2xl:mt-3 2xl:px-4 2xl:py-2.5 2xl:text-sm">
                <X className="mt-0.5 h-4 w-4 shrink-0" />
                <p className="min-w-0 flex-1">{aiMatchErrorMessage}</p>
                <button
                  type="button"
                  aria-label="Dismiss AI match error"
                  title="Dismiss AI match error"
                  onClick={() => setAiMatchErrorMessage("")}
                  className="grid h-5 w-5 shrink-0 place-items-center rounded text-accent transition hover:bg-[#fff3e8] hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : null}

            <div className="mt-2.5 grid min-h-0 flex-1 gap-3 xl:grid-cols-[330px_minmax(0,1fr)] 2xl:mt-4 2xl:grid-cols-[420px_minmax(0,1fr)] 2xl:gap-4">
              {filteredJobs.length === 0 ? (
                <div className="relative isolate grid min-h-[360px] overflow-hidden rounded-[20px] border border-dashed border-[#f4c8ad] bg-[#fffaf6] px-5 py-10 text-center shadow-[inset_0_0_80px_rgba(255,129,51,0.035)] xl:col-span-2 2xl:min-h-[420px]">
                  <div className="m-auto flex max-w-lg flex-col items-center">
                    <div
                      className="relative h-[82px] w-[94px] text-accent"
                      aria-hidden="true"
                    >
                      <span className="absolute left-0 top-[46px] h-2 w-2 rounded-sm bg-[#ffb57f]/45 rotate-12" />
                      <span className="absolute right-1 top-[35px] h-2.5 w-2.5 rounded-full border-2 border-[#ffb57f]/45" />
                      <span className="absolute right-3 top-[68px] h-2 w-2 rotate-45 rounded-sm bg-[#ffb57f]/40" />
                      <span className="absolute left-[14px] top-[66px] h-2 w-2 rotate-45 rounded-sm border-2 border-[#ffb57f]/40" />
                      <span className="absolute left-[30px] top-[5px] h-1.5 w-1.5 rounded-full bg-[#ffb57f]/35" />
                      <span className="absolute left-[30px] top-[18px] h-[58px] w-[58px] rounded-full bg-[#ffdbc3]/35 blur-[1px]" />
                      <Search
                        className="absolute left-[25px] top-[10px] h-[70px] w-[70px] text-[#ffb07a]/55"
                        strokeWidth={1.7}
                      />
                      <span className="absolute left-[35px] top-[20px] grid h-[42px] w-[42px] place-items-center rounded-full border border-[#ff9b5a]/50 bg-[#fffaf6]/90 shadow-[0_0_14px_rgba(255,112,32,0.12)]">
                        <BriefcaseBusiness
                          className="h-6 w-6 text-[#ff792e]"
                          strokeWidth={2}
                        />
                      </span>
                    </div>

                    <h2 className="mt-4 text-[24px] font-bold leading-tight text-foreground 2xl:text-[28px]">
                      {showArchivedJobs
                        ? "No archived jobs"
                        : showSavedJobs
                          ? "No saved jobs"
                          : "No jobs found"}
                    </h2>
                    <p className="mt-3 max-w-[480px] text-[15px] font-medium leading-relaxed text-muted 2xl:text-base">
                      {showArchivedJobs
                        ? "Archived vacancies will appear here after you archive them."
                        : showSavedJobs
                          ? "Saved vacancies will appear here after you click the bookmark or Save button."
                          : "Try changing the search, resetting filters, or searching for new vacancies."}
                    </p>

                    <button
                      type="button"
                      onClick={clearAllJobFilters}
                      className="mt-8 inline-flex h-12 items-center justify-center gap-2 rounded-xl border border-[#ffb17f] bg-white/70 px-6 text-sm font-bold text-accent shadow-[0_8px_24px_rgba(255,104,25,0.07)] transition hover:border-accent hover:bg-[#fff3e8] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-offset-2 2xl:h-14 2xl:px-7 2xl:text-base"
                    >
                      <RotateCcw
                        className="h-[18px] w-[18px] 2xl:h-5 2xl:w-5"
                        strokeWidth={2.2}
                      />
                      Clear all filters
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <aside className="flex min-h-0 flex-col overflow-hidden rounded-md bg-[#fff8f1]">
                    <p className="shrink-0 px-1 pb-3 pt-3 text-sm font-semibold text-muted 2xl:pb-4 2xl:pt-5 2xl:text-base">
                      {filteredJobs.length}{" "}
                      {showArchivedJobs
                        ? "archived jobs"
                        : showSavedJobs
                          ? "saved jobs"
                          : "jobs"}{" "}
                      found
                    </p>
                    <div className="job-scroll min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1 2xl:space-y-2">
                      {filteredJobs.map((job) => (
                        <article
                          key={job.id}
                          role="button"
                          tabIndex={0}
                          onClick={() => {
                            setSelectedJobId(job.id);
                            setActiveTab("Overview");
                          }}
                          onKeyDown={(event) => {
                            if (event.key !== "Enter" && event.key !== " ")
                              return;
                            event.preventDefault();
                            setSelectedJobId(job.id);
                            setActiveTab("Overview");
                          }}
                          className={cn(
                            "w-full cursor-pointer rounded-[8px] border p-2.5 text-left transition 2xl:p-3",
                            selectedJob?.id === job.id
                              ? "border-accent bg-[#fff8f1] shadow-[0_0_0_1px_rgba(255,90,0,0.12)]"
                              : "border-border/80 bg-[#fff8f1] hover:border-[#c0bbb6] hover:bg-[#fff3e8]",
                          )}
                        >
                          <div className="grid grid-cols-[42px_minmax(0,1fr)_68px] gap-2 2xl:grid-cols-[48px_minmax(0,1fr)_72px] 2xl:gap-3">
                            <JobRoleIcon job={job} compact />
                            <div className="min-w-0 pt-0.5">
                              <h2 className="line-clamp-2 text-[13px] font-bold leading-tight text-foreground 2xl:text-base">
                                {job.title}
                              </h2>
                              <p className="mt-0.5 truncate text-xs font-bold text-[#615f5c] 2xl:text-sm">
                                {job.company}
                              </p>
                              <p className="mt-1 truncate text-[10px] font-semibold text-[#615f5c] 2xl:text-[11px]">
                                Source: {getJobSourceLabel(job)}
                              </p>
                            </div>
                            <div className="grid grid-cols-2 justify-items-center gap-1.5">
                              <div className="col-span-2">
                                <JobMatchRing job={job} />
                              </div>
                              <button
                                type="button"
                                aria-label={
                                  savedJobs.includes(job.id)
                                    ? "Unsave job"
                                    : "Save job"
                                }
                                title={
                                  savedJobs.includes(job.id)
                                    ? "Unsave job"
                                    : "Save job"
                                }
                                onClick={(event) => {
                                  event.stopPropagation();
                                  toggleSaved(job.id);
                                }}
                                className={cn(
                                  "grid h-7 w-7 place-items-center rounded-md border border-border bg-[#fff8f1] text-muted transition hover:border-[#c0bbb6] hover:bg-[#fff3e8] hover:text-foreground 2xl:h-8 2xl:w-8",
                                  savedJobs.includes(job.id) &&
                                    "border-accent/60 text-accent",
                                )}
                              >
                                <Bookmark
                                  className={cn(
                                    "h-3.5 w-3.5 2xl:h-4 2xl:w-4",
                                    savedJobs.includes(job.id) &&
                                      "fill-accent text-accent",
                                  )}
                                />
                              </button>
                              <button
                                type="button"
                                aria-label="Rerun AI match"
                                title="Rerun AI match"
                                disabled={forceMatchingJobId === job.id}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void rerunAiMatch(job);
                                }}
                                className="grid h-7 w-7 place-items-center rounded-md border border-border bg-[#fff8f1] text-muted transition hover:border-[#c0bbb6] hover:bg-[#fff3e8] hover:text-foreground disabled:cursor-not-allowed disabled:opacity-55 2xl:h-8 2xl:w-8"
                              >
                                <RotateCcw
                                  className={cn(
                                    "h-3.5 w-3.5 2xl:h-4 2xl:w-4",
                                    forceMatchingJobId === job.id &&
                                      "animate-spin",
                                  )}
                                />
                              </button>
                            </div>
                          </div>

                          <div className="mt-2 border-t border-border/80 pt-2 2xl:mt-3 2xl:pt-2.5">
                            <div className="grid gap-1.5 text-xs font-semibold text-muted sm:grid-cols-[minmax(0,1fr)_auto] 2xl:text-[13px]">
                              <p className="flex min-w-0 flex-nowrap items-center gap-x-1.5">
                                <MapPin className="h-3.5 w-3.5 shrink-0 2xl:h-4 2xl:w-4" />
                                <span className="truncate">
                                  {formatJobLocationCompact(job.location)}
                                </span>
                                <span className="text-foreground/25">•</span>
                                <span className="shrink-0 capitalize">
                                  {job.type}
                                </span>
                              </p>
                              <p className="whitespace-nowrap text-left sm:text-right">
                                {formatJobPostedCompact(job.posted)}
                              </p>
                            </div>
                            {job.salary !== "Not specified" && (
                              <p className="mt-1.5 hidden truncate text-xs font-semibold text-muted/90 2xl:block 2xl:text-[13px]">
                                {job.salary}
                              </p>
                            )}
                            {job.archived && (
                              <p className="mt-1.5 inline-flex w-fit items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[11px] font-bold text-muted">
                                <Archive className="h-3 w-3" />
                                Archived
                              </p>
                            )}
                          </div>
                        </article>
                      ))}
                    </div>
                  </aside>

                  <section className="panel job-scroll min-h-0 overflow-y-auto p-3 md:p-4 2xl:p-5">
                    {selectedJob ? (
                      <>
                        <div className="grid gap-3 2xl:gap-4">
                          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.58fr)] min-[1500px]:grid-cols-[minmax(360px,1fr)_minmax(540px,0.95fr)] 2xl:gap-5">
                            <div className="flex min-w-0 items-start gap-2.5 2xl:gap-3">
                              <JobRoleIcon job={selectedJob} large />
                              <div className="min-w-0 pt-0.5">
                                <h2 className="text-[20px] font-bold leading-[1.2] tracking-[-0.01em] text-foreground lg:text-[19px] min-[1400px]:text-[20px] min-[1500px]:text-[22px] 2xl:text-[24px]">
                                  {selectedJob.title}
                                </h2>
                                <p className="mt-1 text-[13px] font-semibold text-muted 2xl:mt-1.5 2xl:text-sm">
                                  {selectedJob.company}{" "}
                                  <span className="text-foreground/35">•</span>{" "}
                                  {selectedJob.location}{" "}
                                  <span className="text-foreground/35">•</span>{" "}
                                  {selectedJob.type}
                                </p>
                                <p className="mt-0.5 text-[11px] font-semibold text-[#615f5c] 2xl:mt-1 2xl:text-xs">
                                  Source: {getJobSourceLabel(selectedJob)}
                                  {selectedJob.salary !== "Not specified" ? (
                                    <>
                                      <span className="mx-1 text-foreground/30">
                                        •
                                      </span>
                                      {selectedJob.salary}
                                    </>
                                  ) : null}
                                </p>
                              </div>
                            </div>

                            <div className="grid w-full content-start gap-2 sm:grid-cols-2 lg:max-w-[420px] lg:justify-self-end min-[1500px]:max-w-[600px] min-[1500px]:grid-cols-3 2xl:max-w-[600px]">
                              {selectedJobPostingUrl ? (
                                <Button
                                  asChild
                                  variant="ghost"
                                  className="h-10 rounded-md border border-[#fa5d00]/45 bg-[#fa5d00]/10 px-3 text-xs font-bold text-accent shadow-none hover:border-[#fa5d00]/70 hover:bg-[#fa5d00]/18 hover:text-foreground sm:col-span-2 min-[1500px]:col-span-1 xl:text-[13px] 2xl:h-11"
                                >
                                  <a
                                    href={selectedJobPostingUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    <ExternalLink className="h-4 w-4 2xl:h-[18px] 2xl:w-[18px]" />
                                    Open vacancy
                                  </a>
                                </Button>
                              ) : (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  disabled
                                  title="Vacancy link unavailable"
                                  className="h-10 rounded-md border border-border bg-transparent px-3 text-xs font-bold text-muted shadow-none sm:col-span-2 min-[1500px]:col-span-1 xl:text-[13px] 2xl:h-11"
                                >
                                  <ExternalLink className="h-4 w-4 2xl:h-[18px] 2xl:w-[18px]" />
                                  Vacancy link unavailable
                                </Button>
                              )}
                              <Button
                                className={cn(
                                  "h-10 rounded-md border border-border bg-[#fff8f1] px-3 text-xs font-bold text-[#1d1e1c] shadow-none hover:border-[#c0bbb6] hover:bg-[#fff3e8] hover:text-foreground xl:text-[13px] 2xl:h-11",
                                  selectedJobApplication &&
                                    "gap-1 px-2 text-[10px] shadow-none 2xl:gap-1.5 2xl:text-xs",
                                )}
                                onClick={() => {
                                  if (selectedJobApplication) {
                                    deleteApplication(
                                      selectedJobApplication.id,
                                    );
                                  } else {
                                    markJobApplied(selectedJob);
                                  }
                                }}
                              >
                                {selectedJobApplication ? (
                                  <X className="h-3.5 w-3.5 2xl:h-4 2xl:w-4" />
                                ) : (
                                  <span className="grid h-4 w-4 shrink-0 place-items-center rounded-full border border-[#c0bbb6] 2xl:h-[18px] 2xl:w-[18px]">
                                    <Check
                                      className="h-2.5 w-2.5 2xl:h-3 2xl:w-3"
                                      strokeWidth={2.4}
                                    />
                                  </span>
                                )}
                                {selectedJobApplication
                                  ? "Remove application"
                                  : "Mark as Applied"}
                              </Button>
                              <Button
                                variant="ghost"
                                className="h-10 rounded-md border border-[#e95300] bg-accent px-3 text-xs font-bold text-foreground shadow-[0_8px_20px_rgba(255,90,0,0.18)] hover:border-[#e95300] hover:bg-[#e95300] xl:text-[13px] 2xl:h-11"
                                onClick={() =>
                                  prepareJobApplication(selectedJob)
                                }
                              >
                                <FileText className="h-4 w-4 2xl:h-5 2xl:w-5" />
                                {selectedJobPreparation
                                  ? selectedJobPreparation.status === "draft"
                                    ? "Continue preparation"
                                    : "Open application"
                                  : "Prepare application"}
                              </Button>
                            </div>
                          </div>

                          <div className="h-px bg-border" />

                          <div>
                            <div className="grid gap-2 sm:grid-cols-2 2xl:gap-3">
                              {[
                                {
                                  label: hasDisplayableMatch(selectedJob)
                                    ? `Why ${selectedJob.match}%?`
                                    : "Why no match score?",
                                  prompt: hasDisplayableMatch(selectedJob)
                                    ? assistantPrompts.whyMatch(
                                        selectedJob.match,
                                      )
                                    : assistantPrompts.whyNoMatch,
                                  icon: BarChart3,
                                  autoSubmit: true,
                                },
                                {
                                  label: "What to know before applying",
                                  prompt: assistantPrompts.beforeApplying,
                                  icon: Info,
                                  autoSubmit: false,
                                },
                              ].map((action) => {
                                const Icon = action.icon;
                                return (
                                  <Button
                                    key={action.label}
                                    type="button"
                                    variant="ghost"
                                    className="h-10 justify-start rounded-md border border-accent/35 bg-accent/[0.045] px-3 text-xs font-bold text-[#1d1e1c] hover:border-accent/60 hover:bg-accent/[0.10] 2xl:h-11 2xl:text-sm"
                                    onClick={() =>
                                      openAssistant(
                                        action.prompt,
                                        "job",
                                        selectedJob.id,
                                        action.autoSubmit,
                                      )
                                    }
                                  >
                                    <Icon className="h-4 w-4 text-accent 2xl:h-[18px] 2xl:w-[18px]" />
                                    {action.label}
                                    <ChevronRight className="ml-auto h-4 w-4 text-muted" />
                                  </Button>
                                );
                              })}
                            </div>
                          </div>

                          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 2xl:gap-3">
                            <Button
                              type="button"
                              variant="ghost"
                              aria-label="Force AI match rerun"
                              title="Force AI match rerun"
                              disabled={forceMatchingJobId === selectedJob.id}
                              className="h-10 rounded-md border border-border bg-transparent px-3 text-xs font-semibold text-[#1d1e1c] hover:bg-[#fff3e8] disabled:cursor-not-allowed disabled:opacity-55 2xl:h-11 2xl:text-sm"
                              onClick={() => rerunAiMatch(selectedJob)}
                            >
                              <RotateCcw
                                className={cn(
                                  "h-4 w-4 2xl:h-[18px] 2xl:w-[18px]",
                                  forceMatchingJobId === selectedJob.id &&
                                    "animate-spin",
                                )}
                              />
                              {forceMatchingJobId === selectedJob.id
                                ? "Matching"
                                : "Rerun AI"}
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              aria-label={
                                isSelectedSaved ? "Unsave job" : "Save job"
                              }
                              title={
                                isSelectedSaved ? "Unsave job" : "Save job"
                              }
                              className="h-10 rounded-md border border-border bg-transparent px-3 text-xs font-semibold text-[#1d1e1c] hover:bg-[#fff3e8] 2xl:h-11 2xl:text-sm"
                              onClick={() => toggleSaved(selectedJob.id)}
                            >
                              <Bookmark
                                className={cn(
                                  "h-4 w-4 2xl:h-[18px] 2xl:w-[18px]",
                                  isSelectedSaved && "fill-accent text-accent",
                                )}
                              />
                              {isSelectedSaved ? "Saved" : "Save"}
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              aria-label={
                                selectedJob.archived
                                  ? "Restore job"
                                  : "Archive job"
                              }
                              title={
                                selectedJob.archived
                                  ? "Restore job"
                                  : "Archive job"
                              }
                              className="h-10 rounded-md border border-border bg-transparent px-3 text-xs font-semibold text-[#1d1e1c] hover:bg-[#fff3e8] 2xl:h-11 2xl:text-sm"
                              onClick={() =>
                                updateJobArchiveState(
                                  selectedJob,
                                  !selectedJob.archived,
                                )
                              }
                            >
                              {selectedJob.archived ? (
                                <ArchiveRestore className="h-4 w-4 2xl:h-[18px] 2xl:w-[18px]" />
                              ) : (
                                <Archive className="h-4 w-4 2xl:h-[18px] 2xl:w-[18px]" />
                              )}
                              {selectedJob.archived ? "Restore" : "Archive"}
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              aria-label="Delete job"
                              title="Delete job"
                              className="h-10 rounded-md border border-border bg-transparent px-3 text-xs font-semibold text-[#fa5d00] hover:border-[#fa5d00]/55 hover:bg-[#fa5d00]/12 2xl:h-11 2xl:text-sm"
                              onClick={() => deleteJob(selectedJob)}
                            >
                              <Trash2 className="h-4 w-4 2xl:h-[18px] 2xl:w-[18px]" />
                              Delete
                            </Button>
                          </div>
                        </div>

                        <div className="mt-3 flex gap-2 overflow-x-auto border-b border-border 2xl:mt-4 2xl:gap-4">
                          {tabs.map((tab) => (
                            <button
                              key={tab}
                              type="button"
                              onClick={() => setActiveTab(tab)}
                              className={cn(
                                "relative h-10 min-w-fit px-4 text-[13px] font-bold text-muted transition hover:text-foreground 2xl:h-11 2xl:px-5 2xl:text-sm",
                                activeTab === tab &&
                                  "text-foreground after:absolute after:bottom-[-1px] after:left-0 after:h-0.5 after:w-full after:bg-accent",
                              )}
                            >
                              {tab}
                            </button>
                          ))}
                        </div>

                        <div className="mt-4 grid gap-3 min-[1800px]:grid-cols-[minmax(0,1.12fr)_minmax(320px,0.9fr)] 2xl:mt-5 2xl:gap-4">
                          <JobMainPanel
                            job={selectedJob}
                            tab={activeTab}
                            analysisRef={aiMatchAnalysisRef}
                            recommendationsRef={aiMatchRecommendationsRef}
                          />

                          <div className="grid content-start gap-3 2xl:gap-4">
                            <MatchPanel
                              job={selectedJob}
                              onReviewFullAnalysis={() =>
                                openAiMatchSection("analysis")
                              }
                            />
                            <RecommendationsPanel
                              job={selectedJob}
                              onViewAllRecommendations={() =>
                                openAiMatchSection("recommendations")
                              }
                            />
                            <JobDetails job={selectedJob} />
                            <SalaryInsights job={selectedJob} />
                          </div>
                        </div>
                      </>
                    ) : (
                      <div className="grid min-h-[360px] place-items-center rounded-md border border-dashed border-border bg-[#fff8f1] p-6 text-center">
                        <div>
                          <Archive className="mx-auto h-9 w-9 text-muted" />
                          <h2 className="mt-4 text-xl font-bold text-foreground">
                            {showArchivedJobs
                              ? "No archived jobs"
                              : showSavedJobs
                                ? "No saved jobs"
                                : "No jobs found"}
                          </h2>
                          <p className="mt-2 max-w-md text-sm font-medium text-muted">
                            {showArchivedJobs
                              ? "Archived vacancies will appear here after you archive them."
                              : showSavedJobs
                                ? "Saved vacancies will appear here after you click the bookmark or Save button."
                                : "Try changing the search, resetting filters, or searching for new vacancies."}
                          </p>
                        </div>
                      </div>
                    )}
                  </section>
                </>
              )}
            </div>

            {isManualJobDialogOpen && (
              <ManualJobDialog
                draft={manualJobDraft}
                onChange={updateManualJobDraft}
                onClose={() => setIsManualJobDialogOpen(false)}
                onSave={() => void addManualJob()}
              />
            )}

            {isParserDialogOpen ? (
              <JobSearchDialog
                form={parserSearchForm}
                activeSource={activeSearchSource}
                sourceConfigs={sourceSearchConfigs}
                selectedSourceConfigIds={selectedSourceConfigIds}
                selectedParserSearchConfigId={selectedParserSearchConfigId}
                directCompanies={directCompanyCatalog}
                newLinkedInProfession={newLinkedInProfession}
                status={parserSearchStatus}
                message={parserSearchMessage}
                onClose={() => setIsParserDialogOpen(false)}
                onActivateSource={activateSearchSource}
                onToggleParser={toggleParser}
                onToggleDirectCompanies={toggleDirectCompanies}
                onStartSearch={runParsers}
                onFormChange={updateParserSearchForm}
                onReset={resetParserSearch}
                onSelectSourceConfig={selectSourceSearchConfig}
                onSaveSourceConfig={saveSourceSearchConfig}
                onSelectedDirectCompaniesChange={updateSelectedDirectCompanies}
                onNewLinkedInProfessionChange={setNewLinkedInProfession}
                onAddLinkedInProfession={addLinkedInProfession}
                onRemoveLinkedInProfession={removeLinkedInProfession}
              />
            ) : null}
          </section>
        )}
        {isProfileDialogOpen && (
        <ProfileEditorDialog
          profile={profileDraft}
          avatarFile={profileAvatarDraftFile}
          useDefaultAvatar={profileAvatarUseDefault}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onChange={updateProfileDraft}
          onAvatarFileSelected={(file) => {
            setProfileAvatarDraftFile(file);
            setProfileAvatarUseDefault(false);
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onUseDefaultAvatar={() => {
            setProfileAvatarDraftFile(null);
            setProfileAvatarUseDefault(true);
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onClose={closeProfileEditor}
          onSave={saveProfile}
        />
      )}
      {isExperienceDialogOpen && (
        <ExperienceEditorDialog
          experience={experienceDraft}
          isEditMode={isExperienceEditMode}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onChange={(field, value) => {
            setExperienceDraft((current) => ({ ...current, [field]: value }));
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onClose={() => setIsExperienceDialogOpen(false)}
          onSave={saveExperience}
        />
      )}
      {isEducationDialogOpen && (
        <EducationEditorDialog
          education={educationDraft}
          isEditMode={isEducationEditMode}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onChange={(field, value) => {
            setEducationDraft((current) => ({ ...current, [field]: value }));
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onClose={() => setIsEducationDialogOpen(false)}
          onSave={saveEducation}
        />
      )}
      {isDocumentDialogOpen && (
        <DocumentEditorDialog
          document={documentDraft}
          isEditMode={isDocumentEditMode}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onChange={(field, value) => {
            setDocumentDraft((current) => ({ ...current, [field]: value }));
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onAttachFile={attachDocumentFile}
          onClose={() => setIsDocumentDialogOpen(false)}
          onSave={saveDocument}
        />
      )}
      {isPreferencesDialogOpen && (
        <PreferencesEditorDialog
          preferences={preferencesDraft}
          inputs={preferenceInputs}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onChange={updatePreferencesDraft}
          onInputChange={updatePreferenceInput}
          onAddListItem={addPreferenceListItem}
          onRemoveListItem={removePreferenceListItem}
          onToggleOption={togglePreferenceOption}
          onSetAny={setPreferenceAny}
          onClose={() => setIsPreferencesDialogOpen(false)}
          onSave={savePreferences}
        />
      )}
      {isSkillsDialogOpen && (
        <SkillsEditorDialog
          skills={skillsDraft}
          skillInput={skillInput}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onSkillInputChange={(value) => {
            setSkillInput(value);
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onAddSkill={addSkillToDraft}
          onRemoveSkill={removeSkillFromDraft}
          onClose={() => setIsSkillsDialogOpen(false)}
          onSave={saveSkills}
        />
      )}
      {isDealbreakersDialogOpen && (
        <DealbreakersEditorDialog
          dealbreakers={dealbreakersDraft}
          dealbreakerInput={dealbreakerInput}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onDealbreakerInputChange={(value) => {
            setDealbreakerInput(value);
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onAddDealbreaker={addDealbreakerToDraft}
          onRemoveDealbreaker={removeDealbreakerFromDraft}
          onClearDealbreakers={clearDealbreakersDraft}
          onClose={() => setIsDealbreakersDialogOpen(false)}
          onSave={saveDealbreakers}
        />
      )}
      {isAdditionalNotesDialogOpen && (
        <AdditionalNotesEditorDialog
          notes={additionalNotesDraft}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onChange={(value) => {
            setAdditionalNotesDraft(value);
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onClear={() => {
            setAdditionalNotesDraft("");
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onClose={() => setIsAdditionalNotesDialogOpen(false)}
          onSave={saveAdditionalNotes}
        />
      )}
    </>
  );
}
