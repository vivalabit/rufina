"use client";

import { useEffect, useState } from "react";
import {
  BriefcaseBusiness,
  Calendar,
  Check,
  ChevronDown,
  ChevronRight,
  Download,
  ExternalLink,
  FileText,
  Info,
  Mail,
  MapPin,
  MoreHorizontal,
  Plus,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import {
  ApplicationAiInfoDialog,
  ApplicationEventDialog,
  ApplicationNotesDialog,
  ManualApplicationDialog,
} from "@/components/application-dialogs";
import { JobRoleIcon } from "@/components/job-visuals";
import { Button } from "@/components/ui/button";
import {
  formatApplicationDate,
  formatApplicationEventDate,
  formatApplicationEventTime,
  getApplicationDocumentBadge,
  getApplicationEventOutcomeLabel,
  getApplicationStatusLabel,
  getVisibleApplicationNotes,
} from "@/features/applications/formatting";
import {
  applicationSortOptions,
  applicationStatusStyles,
  defaultManualApplicationDraft,
  trackedApplicationStatuses,
} from "@/features/applications/model/constants";
import {
  createApplicationEvent,
  createDefaultEventDraft,
  createEventDraftFromEvent,
} from "@/features/applications/model/event-drafts";
import {
  buildApplicationTimeline,
  filterAndSortApplications,
  getApplicationEventsFor,
  getApplicationStatusCounts,
  getNextUpcomingApplicationEvent,
  getVisibleSelectedApplication,
} from "@/features/applications/model/selectors";
import type {
  ApplicationSortBy,
  ApplicationStatusFilter,
  ManualApplicationDraft,
} from "@/features/applications/model/types";
import { formatFileSize } from "@/shared/formatting/files";
import {
  formatJobLocationCompact,
  getJobApplyUrl,
} from "@/features/jobs/formatting";
import { formatMatchValue } from "@/features/jobs/model/ai-match";
import { createClientId } from "@/lib/client-id";
import { cn } from "@/lib/utils";
import type {
  ApplicationDocument,
  ApplicationEvent,
  ApplicationEventDraft,
  ApplicationStatus,
  TrackedApplication,
} from "@/shared/types/application";
import type { CandidateProfile } from "@/shared/types/profile";

export type ApplicationAttachmentMetadata = {
  fileName: string;
  title: string;
};

type ApplicationsViewProps = {
  applications: TrackedApplication[];
  events: ApplicationEvent[];
  matchingApplicationIds: string[];
  profile: CandidateProfile;
  selectedApplication: TrackedApplication | null;
  onSelectApplication: (applicationId: string) => void;
  onOpenJobs: () => void;
  onPrepareApplication: (applicationId: string) => void;
  onAddManualApplication: (draft: ManualApplicationDraft) => Promise<void>;
  onChangeStatus: (applicationId: string, status: ApplicationStatus) => void;
  onChangeNotes: (applicationId: string, notes: string) => void;
  onChangeDocuments: (
    applicationId: string,
    documents: ApplicationDocument[],
  ) => void;
  onDeleteApplication: (applicationId: string) => void;
  onSaveEvent: (event: ApplicationEvent) => void;
  onDeleteEvent: (eventId: string) => void;
  onUploadDocument: (
    applicationId: string,
    file: File,
    metadata: ApplicationAttachmentMetadata,
  ) => Promise<ApplicationDocument>;
  onDeleteDocument: (
    applicationId: string,
    document: ApplicationDocument,
  ) => Promise<void>;
};

function createProfileResumeApplicationDocument(
  profile: CandidateProfile,
): ApplicationDocument | null {
  if (!profile.resume_file_name || !profile.resume_download_url) return null;

  return {
    id: createClientId("profile-resume"),
    kind: "profile",
    title:
      profile.resume_file_name
        .replace(/\.[^.]+$/, "")
        .replace(/[_-]+/g, " ")
        .trim() || "Profile resume",
    fileName: profile.resume_file_name,
    fileSize: profile.resume_file_size,
    fileType: "application/octet-stream",
    uploadedAt: profile.resume_updated_at || new Date().toISOString(),
    downloadUrl: profile.resume_download_url,
  };
}

export function ApplicationsView({
  applications,
  events,
  matchingApplicationIds,
  profile,
  selectedApplication,
  onSelectApplication,
  onOpenJobs,
  onPrepareApplication,
  onAddManualApplication,
  onChangeStatus,
  onChangeNotes,
  onChangeDocuments,
  onDeleteApplication,
  onSaveEvent,
  onDeleteEvent,
  onUploadDocument,
  onDeleteDocument,
}: ApplicationsViewProps) {
  const [applicationQuery, setApplicationQuery] = useState("");
  const [selectedStatusFilter, setSelectedStatusFilter] =
    useState<ApplicationStatusFilter>("all");
  const [applicationSortBy, setApplicationSortBy] =
    useState<ApplicationSortBy>("Date applied");
  const [isScheduleDialogOpen, setIsScheduleDialogOpen] = useState(false);
  const [eventDraft, setEventDraft] = useState<ApplicationEventDraft | null>(
    null,
  );
  const [activeEventMenuId, setActiveEventMenuId] = useState("");
  const [isApplicationMenuOpen, setIsApplicationMenuOpen] = useState(false);
  const [isNotesDialogOpen, setIsNotesDialogOpen] = useState(false);
  const [applicationNotesDraft, setApplicationNotesDraft] = useState("");
  const [aiInfoApplicationId, setAiInfoApplicationId] = useState("");
  const [isManualApplicationDialogOpen, setIsManualApplicationDialogOpen] =
    useState(false);
  const [manualApplicationDraft, setManualApplicationDraft] =
    useState<ManualApplicationDraft>(defaultManualApplicationDraft);
  const [isManualApplicationSaving, setIsManualApplicationSaving] =
    useState(false);
  const [manualApplicationError, setManualApplicationError] = useState("");
  const statusCounts = getApplicationStatusCounts(applications);
  const filteredApplications = filterAndSortApplications(applications, {
    query: applicationQuery,
    status: selectedStatusFilter,
    sortBy: applicationSortBy,
  });
  const matchingApplicationIdSet = new Set(matchingApplicationIds);
  const visibleSelectedApplication = getVisibleSelectedApplication(
    selectedApplication,
    filteredApplications,
  );

  useEffect(() => {
    if (!visibleSelectedApplication) return;
    if (selectedApplication?.id === visibleSelectedApplication.id) return;
    onSelectApplication(visibleSelectedApplication.id);
  }, [onSelectApplication, selectedApplication?.id, visibleSelectedApplication]);
  const visibleApplicationEvents = visibleSelectedApplication
    ? getApplicationEventsFor(events, visibleSelectedApplication.id)
    : [];
  const aiInfoApplication =
    applications.find(
      (application) => application.id === aiInfoApplicationId,
    ) ?? null;
  const nextApplicationEvent = getNextUpcomingApplicationEvent(
    visibleApplicationEvents,
    Date.now(),
  );
  const timelineItems = visibleSelectedApplication
    ? buildApplicationTimeline(
        visibleSelectedApplication,
        visibleApplicationEvents,
        nextApplicationEvent,
      )
    : [];

  function openManualApplicationDialog() {
    setManualApplicationDraft({
      ...defaultManualApplicationDraft,
      id: createClientId("manual-application"),
      jobId: createClientId("manual-job"),
    });
    setManualApplicationError("");
    setIsManualApplicationDialogOpen(true);
  }

  function clearAllApplicationFilters() {
    setApplicationQuery("");
    setSelectedStatusFilter("all");
    setApplicationSortBy("Date applied");
  }

  function updateManualApplicationDraft<
    Field extends keyof ManualApplicationDraft,
  >(field: Field, value: ManualApplicationDraft[Field]) {
    setManualApplicationDraft((currentDraft) => ({
      ...currentDraft,
      [field]: value,
    }));
    setManualApplicationError("");
  }

  function useProfileResumeForManualApplication() {
    const resumeDocument = createProfileResumeApplicationDocument(profile);
    if (!resumeDocument) return;

    updateManualApplicationDraft("documents", [resumeDocument]);
  }

  function attachManualApplicationResume(file: File | undefined) {
    if (!file) return;

    const allowedTypes = new Set([
      "application/pdf",
      "application/msword",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]);
    const allowedExtensions = [".pdf", ".doc", ".docx"];
    const lowerFileName = file.name.toLowerCase();
    const hasAllowedExtension = allowedExtensions.some((extension) =>
      lowerFileName.endsWith(extension),
    );

    if (!allowedTypes.has(file.type) && !hasAllowedExtension) {
      window.alert("Upload a PDF, DOC, or DOCX resume.");
      return;
    }

    if (file.size > 5_000_000) {
      window.alert("Resume file must be under 5MB.");
      return;
    }

    const title =
      file.name
        .replace(/\.[^.]+$/, "")
        .replace(/[_-]+/g, " ")
        .trim() || file.name;
    updateManualApplicationDraft("documents", [
      {
        id: createClientId("application-resume"),
        kind: "uploaded",
        title,
        fileName: file.name,
        fileSize: formatFileSize(file.size),
        fileType: file.type || "application/octet-stream",
        uploadedAt: new Date().toISOString(),
        downloadUrl: "",
        pendingFile: file,
      },
    ]);
  }

  async function saveManualApplication() {
    if (
      !manualApplicationDraft.title.trim() ||
      !manualApplicationDraft.company.trim() ||
      !manualApplicationDraft.location.trim() ||
      !manualApplicationDraft.applyUrl.trim() ||
      !manualApplicationDraft.overview.trim()
    ) {
      return;
    }

    setIsManualApplicationSaving(true);
    setManualApplicationError("");
    try {
      await onAddManualApplication(manualApplicationDraft);
      setManualApplicationDraft(defaultManualApplicationDraft);
      setIsManualApplicationDialogOpen(false);
    } catch (error) {
      setManualApplicationError(
        error instanceof Error
          ? error.message
          : "Application could not be saved",
      );
    } finally {
      setIsManualApplicationSaving(false);
    }
  }

  function openApplicationAiInfo(applicationId: string) {
    setAiInfoApplicationId(applicationId);
    setIsApplicationMenuOpen(false);
  }

  function openScheduleDialog() {
    if (!visibleSelectedApplication) return;

    setEventDraft(createDefaultEventDraft(visibleSelectedApplication));
    setActiveEventMenuId("");
    setIsScheduleDialogOpen(true);
  }

  function openEditEventDialog(event: ApplicationEvent) {
    setEventDraft(createEventDraftFromEvent(event));
    setActiveEventMenuId("");
    setIsScheduleDialogOpen(true);
  }

  function updateEventDraft<Field extends keyof ApplicationEventDraft>(
    field: Field,
    value: ApplicationEventDraft[Field],
  ) {
    setEventDraft((currentDraft) => {
      if (!currentDraft) return currentDraft;

      const nextDraft = { ...currentDraft, [field]: value };
      if (field === "status" && value !== "completed") {
        nextDraft.outcome = "";
      }

      return nextDraft;
    });
  }

  function saveEventDraft() {
    if (!visibleSelectedApplication || !eventDraft || !eventDraft.startsAt)
      return;

    onSaveEvent(
      createApplicationEvent(visibleSelectedApplication.id, eventDraft),
    );
    setIsScheduleDialogOpen(false);
    setEventDraft(null);
  }

  function updateEvent(
    event: ApplicationEvent,
    updates: Partial<Pick<ApplicationEvent, "status" | "outcome">>,
  ) {
    onSaveEvent({
      ...event,
      ...updates,
    });
    setActiveEventMenuId("");
  }

  function deleteEvent(eventId: string) {
    onDeleteEvent(eventId);
    setActiveEventMenuId("");
  }

  function openApplicationPosting() {
    if (!visibleSelectedApplication) return;

    const postingUrl = getJobApplyUrl(visibleSelectedApplication.job);
    if (!postingUrl) return;

    window.open(postingUrl, "_blank", "noopener,noreferrer");
    setIsApplicationMenuOpen(false);
  }

  function changeApplicationStatus(status: ApplicationStatus) {
    if (!visibleSelectedApplication) return;

    onChangeStatus(visibleSelectedApplication.id, status);
    setIsApplicationMenuOpen(false);
  }

  function openNotesDialog() {
    if (!visibleSelectedApplication) return;

    setApplicationNotesDraft(
      getVisibleApplicationNotes(visibleSelectedApplication.notes),
    );
    setIsApplicationMenuOpen(false);
    setIsNotesDialogOpen(true);
  }

  function saveApplicationNotes() {
    if (!visibleSelectedApplication) return;

    onChangeNotes(visibleSelectedApplication.id, applicationNotesDraft.trim());
    setIsNotesDialogOpen(false);
  }

  function deleteSelectedApplication() {
    if (!visibleSelectedApplication) return;
    const shouldDelete = window.confirm(
      `Delete application for ${visibleSelectedApplication.job.title} at ${visibleSelectedApplication.job.company}?`,
    );
    if (!shouldDelete) return;

    onDeleteApplication(visibleSelectedApplication.id);
    setIsApplicationMenuOpen(false);
  }

  async function attachApplicationDocument(file: File | undefined) {
    if (!file || !visibleSelectedApplication) return;

    const allowedTypes = new Set([
      "application/pdf",
      "application/msword",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "image/png",
      "image/jpeg",
      "image/webp",
    ]);
    const allowedExtensions = [
      ".pdf",
      ".doc",
      ".docx",
      ".png",
      ".jpg",
      ".jpeg",
      ".webp",
    ];
    const lowerFileName = file.name.toLowerCase();
    const hasAllowedExtension = allowedExtensions.some((extension) =>
      lowerFileName.endsWith(extension),
    );

    if (!allowedTypes.has(file.type) && !hasAllowedExtension) {
      window.alert("Upload a PDF, DOC, DOCX, PNG, JPG, or WebP file.");
      return;
    }

    if (file.size > 5_000_000) {
      window.alert("Document file must be under 5MB.");
      return;
    }

    const application = visibleSelectedApplication;
    const title =
      file.name
        .replace(/\.[^.]+$/, "")
        .replace(/[_-]+/g, " ")
        .trim() || file.name;
    try {
      const document = await onUploadDocument(application.id, file, {
        fileName: file.name,
        title,
      });
      onChangeDocuments(application.id, [...application.documents, document]);
    } catch (error) {
      window.alert(
        error instanceof Error
          ? error.message
          : "Document could not be uploaded",
      );
    }
  }

  async function deleteApplicationDocument(documentId: string) {
    if (!visibleSelectedApplication) return;

    const document = visibleSelectedApplication.documents.find(
      (item) => item.id === documentId,
    );
    if (!document) return;
    try {
      await onDeleteDocument(visibleSelectedApplication.id, document);
      onChangeDocuments(
        visibleSelectedApplication.id,
        visibleSelectedApplication.documents.filter(
          (item) => item.id !== documentId,
        ),
      );
    } catch (error) {
      window.alert(
        error instanceof Error
          ? error.message
          : "Document could not be deleted",
      );
    }
  }

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
      <header className="shrink-0">
        <h1 className="page-title text-[24px] leading-tight text-foreground sm:text-[27px] 2xl:text-[31px]">
          Applications
        </h1>

        <div
          aria-label="Applications actions"
          className="mt-2.5 flex min-w-0 flex-col gap-2 pb-1 xl:flex-row xl:items-center 2xl:mt-4"
        >
          <div className="flex shrink-0 items-center gap-2">
            <Button
              className="h-10 shrink-0 rounded-lg border border-[#fa5d00] bg-[linear-gradient(135deg,#fa5d00_0%,#e95300_100%)] px-4 text-[13px] font-bold text-foreground shadow-[0_10px_28px_rgba(255,90,0,0.24),inset_0_1px_0_rgba(255,255,255,0.18)] hover:bg-[linear-gradient(135deg,#fa5d00_0%,#e95300_100%)] 2xl:h-12 2xl:px-5 2xl:text-sm"
              onClick={openManualApplicationDialog}
            >
              <Plus className="h-[18px] w-[18px] stroke-[2.3] 2xl:h-5 2xl:w-5" />
              Add application
            </Button>
            <Button
              variant="ghost"
              className="h-10 shrink-0 rounded-lg border border-[#fa5d00] bg-transparent px-4 text-[13px] font-bold text-accent shadow-none hover:border-[#e95300] hover:bg-[#fa5d00]/10 hover:text-accent 2xl:h-12 2xl:px-5 2xl:text-sm"
              onClick={onOpenJobs}
            >
              <BriefcaseBusiness className="h-[18px] w-[18px] stroke-[2.3] text-accent 2xl:h-5 2xl:w-5" />
              Browse jobs
            </Button>
          </div>

          <label className="flex h-10 min-w-[220px] flex-1 items-center gap-2.5 rounded-lg border border-border bg-white px-3 shadow-[0_4px_14px_rgba(227,214,197,0.3)] focus-within:border-accent/70 focus-within:ring-2 focus-within:ring-accent/15 2xl:h-12 2xl:px-4">
            <Search className="h-[18px] w-[18px] shrink-0 text-muted 2xl:h-5 2xl:w-5" />
            <input
              type="search"
              value={applicationQuery}
              onChange={(event) => setApplicationQuery(event.target.value)}
              aria-label="Search applications"
              placeholder="Search applications..."
              className="h-full min-w-0 flex-1 !border-transparent !bg-transparent text-[13px] font-medium text-foreground outline-none placeholder:text-muted focus-visible:!outline-none 2xl:text-sm"
            />
          </label>
        </div>
      </header>

      <div className="mt-3 flex shrink-0 flex-col gap-2 lg:flex-row lg:items-center lg:justify-between 2xl:mt-5 2xl:gap-3">
        <div className="flex flex-wrap gap-1.5 2xl:gap-2">
          {[
            { value: "all" as const, label: "All", count: applications.length },
            ...trackedApplicationStatuses.map((item) => ({
              value: item.status,
              label: item.label,
              count: statusCounts[item.status],
            })),
          ].map((item) => {
            const isActive = selectedStatusFilter === item.value;

            return (
              <button
                key={item.value}
                type="button"
                aria-label={`${item.label} applications: ${item.count}`}
                aria-pressed={isActive}
                onClick={() => setSelectedStatusFilter(item.value)}
                className={cn(
                  "inline-flex h-8 items-center gap-2 rounded-md border border-border/80 bg-[#fff8f1] px-3 text-xs font-semibold text-[#1d1e1c] shadow-[0_3px_10px_rgba(227,214,197,0.24)] transition hover:border-[#c0bbb6] hover:bg-[#fff3e8] 2xl:h-10 2xl:px-4 2xl:text-sm",
                  isActive && "border-accent/70 bg-accent/10 text-foreground",
                )}
              >
                {item.label}
                <span
                  className={cn(
                    "grid min-w-5 place-items-center rounded-full bg-white px-1.5 py-0.5 text-[10px] font-bold text-muted",
                    isActive && "text-accent",
                  )}
                >
                  {item.count}
                </span>
              </button>
            );
          })}
          <button
            type="button"
            onClick={clearAllApplicationFilters}
            className={cn(
              "inline-flex h-8 items-center gap-2 rounded-md border border-border bg-[#fff8f1] px-3 text-xs font-semibold text-[#1d1e1c] shadow-[0_3px_10px_rgba(227,214,197,0.24)] transition hover:border-[#c0bbb6] hover:bg-[#fff3e8] 2xl:h-10 2xl:gap-2.5 2xl:px-5 2xl:text-sm",
              (applicationQuery ||
                selectedStatusFilter !== "all" ||
                applicationSortBy !== "Date applied") &&
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

        <label className="relative inline-flex h-8 w-fit min-w-[178px] items-center gap-1.5 whitespace-nowrap rounded-md bg-[#fff8f1] px-2.5 text-xs font-semibold text-[#1d1e1c] transition hover:bg-[#fff3e8] focus-within:ring-2 focus-within:ring-accent/20 2xl:h-10 2xl:min-w-[214px] 2xl:gap-2 2xl:px-4 2xl:text-sm">
          <SlidersHorizontal className="h-3.5 w-3.5 text-muted 2xl:h-4 2xl:w-4" />
          <select
            aria-label="Sort applications"
            value={applicationSortBy}
            onChange={(event) =>
              setApplicationSortBy(event.target.value as ApplicationSortBy)
            }
            className="h-full min-w-0 flex-1 appearance-none !border-transparent !bg-transparent pr-6 font-semibold outline-none focus-visible:!outline-none"
          >
            {applicationSortOptions.map((option) => (
              <option key={option} value={option}>
                Sort by: {option}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2.5 h-3.5 w-3.5 text-muted 2xl:right-4 2xl:h-4 2xl:w-4" />
        </label>
      </div>

      <div
        data-testid="applications-layout"
        className="mt-2.5 grid min-h-0 flex-1 gap-3 xl:grid-cols-[330px_minmax(0,1fr)] 2xl:mt-4 2xl:grid-cols-[420px_minmax(0,1fr)] 2xl:gap-4"
      >
        {applications.length === 0 ? (
          <div className="relative isolate grid min-h-[360px] overflow-hidden rounded-[20px] border border-dashed border-[#f4c8ad] bg-[#fffaf6] px-5 py-10 text-center shadow-[inset_0_0_80px_rgba(255,129,51,0.035)] xl:col-span-2 2xl:min-h-[420px]">
            <div className="m-auto flex max-w-lg flex-col items-center">
              <div
                className="relative h-[82px] w-[94px] text-accent"
                aria-hidden="true"
              >
                <span className="absolute left-0 top-[46px] h-2 w-2 rotate-12 rounded-sm bg-[#ffb57f]/45" />
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
                  <Mail className="h-6 w-6 text-[#ff792e]" strokeWidth={2} />
                </span>
              </div>
              <h2 className="mt-4 text-[24px] font-bold leading-tight text-foreground 2xl:text-[28px]">
                No applications yet
              </h2>
              <p className="mt-3 max-w-[480px] text-[15px] font-medium leading-relaxed text-muted 2xl:text-base">
                Add a vacancy manually or browse Jobs and mark a matching
                vacancy as applied.
              </p>
              <div className="mt-8 flex flex-col justify-center gap-2 sm:flex-row">
                <Button
                  className="h-12 rounded-xl bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-6 text-sm font-bold 2xl:h-14 2xl:px-7 2xl:text-base"
                  onClick={openManualApplicationDialog}
                >
                  <Plus className="h-[18px] w-[18px] 2xl:h-5 2xl:w-5" />
                  Add application
                </Button>
                <Button
                  variant="ghost"
                  className="h-12 rounded-xl border border-[#ffb17f] bg-white/70 px-6 text-sm font-bold text-accent hover:border-accent hover:bg-[#fff3e8] 2xl:h-14 2xl:px-7 2xl:text-base"
                  onClick={onOpenJobs}
                >
                  Browse jobs
                  <ChevronRight className="h-[18px] w-[18px] 2xl:h-5 2xl:w-5" />
                </Button>
              </div>
            </div>
          </div>
        ) : filteredApplications.length === 0 ? (
          <div className="relative isolate grid min-h-[360px] overflow-hidden rounded-[20px] border border-dashed border-[#f4c8ad] bg-[#fffaf6] px-5 py-10 text-center shadow-[inset_0_0_80px_rgba(255,129,51,0.035)] xl:col-span-2 2xl:min-h-[420px]">
            <div className="m-auto flex max-w-lg flex-col items-center">
              <Search
                className="h-14 w-14 text-[#ffb07a]/70"
                strokeWidth={1.7}
              />
              <h2 className="mt-4 text-[24px] font-bold leading-tight text-foreground 2xl:text-[28px]">
                No applications found
              </h2>
              <p className="mt-3 max-w-[480px] text-[15px] font-medium leading-relaxed text-muted 2xl:text-base">
                Try changing the search or resetting the status filter.
              </p>
              <button
                type="button"
                onClick={clearAllApplicationFilters}
                className="mt-8 inline-flex h-12 items-center justify-center gap-2 rounded-xl border border-[#ffb17f] bg-white/70 px-6 text-sm font-bold text-accent shadow-[0_8px_24px_rgba(255,104,25,0.07)] transition hover:border-accent hover:bg-[#fff3e8] 2xl:h-14 2xl:px-7 2xl:text-base"
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
                {filteredApplications.length}{" "}
                {filteredApplications.length === 1
                  ? "application"
                  : "applications"}
              </p>
              <div className="job-scroll min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1 2xl:space-y-2">
                {filteredApplications.map((application) => (
                  <article
                    key={application.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => onSelectApplication(application.id)}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter" && event.key !== " ") return;
                      event.preventDefault();
                      onSelectApplication(application.id);
                    }}
                    className={cn(
                      "w-full cursor-pointer rounded-[8px] border p-2.5 text-left transition 2xl:p-3",
                      visibleSelectedApplication?.id === application.id
                        ? "border-accent bg-[#fff8f1] shadow-[0_0_0_1px_rgba(255,90,0,0.12)]"
                        : "border-border/80 bg-[#fff8f1] hover:border-[#c0bbb6] hover:bg-[#fff3e8]",
                    )}
                  >
                    <div className="grid grid-cols-[42px_minmax(0,1fr)_88px] gap-2 2xl:grid-cols-[48px_minmax(0,1fr)_96px] 2xl:gap-3">
                      <JobRoleIcon job={application.job} compact />
                      <div className="min-w-0 pt-0.5">
                        <h3 className="line-clamp-2 text-[13px] font-bold leading-tight text-foreground 2xl:text-base">
                          {application.job.title}
                        </h3>
                        <p className="mt-0.5 truncate text-xs font-bold text-[#615f5c] 2xl:text-sm">
                          {application.job.company}
                        </p>
                        <p className="mt-1 truncate text-[10px] font-semibold text-[#615f5c] 2xl:text-[11px]">
                          Applied {formatApplicationDate(application.appliedAt)}
                        </p>
                      </div>
                      <div className="flex min-w-0 flex-col items-end gap-1.5">
                        <span
                          className={cn(
                            "max-w-full truncate rounded-md border px-2 py-1 text-[10px] font-bold 2xl:text-[11px]",
                            applicationStatusStyles[application.status],
                          )}
                        >
                          {matchingApplicationIdSet.has(application.id)
                            ? "Analyzing"
                            : getApplicationStatusLabel(application.status)}
                        </span>
                        <div className="flex items-center gap-1.5">
                          <span className="text-[11px] font-bold text-success 2xl:text-xs">
                            {formatMatchValue(application.job)}
                          </span>
                          <button
                            type="button"
                            aria-label={`Open AI info for ${application.job.title}`}
                            title="AI info"
                            onClick={(event) => {
                              event.stopPropagation();
                              openApplicationAiInfo(application.id);
                            }}
                            className="grid h-7 w-7 shrink-0 place-items-center rounded-md border border-border bg-[#fff8f1] text-muted transition hover:border-[#c0bbb6] hover:bg-[#fff3e8] hover:text-foreground 2xl:h-8 2xl:w-8"
                          >
                            <Info className="h-3.5 w-3.5 2xl:h-4 2xl:w-4" />
                          </button>
                        </div>
                      </div>
                    </div>
                    <div className="mt-2 border-t border-border/80 pt-2 2xl:mt-3 2xl:pt-2.5">
                      <div className="grid gap-1.5 text-xs font-semibold text-muted sm:grid-cols-[minmax(0,1fr)_auto] 2xl:text-[13px]">
                        <p className="flex min-w-0 flex-nowrap items-center gap-x-1.5">
                          <MapPin className="h-3.5 w-3.5 shrink-0 2xl:h-4 2xl:w-4" />
                          <span className="truncate">
                            {formatJobLocationCompact(application.job.location)}
                          </span>
                          <span className="text-foreground/25">•</span>
                          <span className="shrink-0 capitalize">
                            {application.job.type}
                          </span>
                        </p>
                        <p className="whitespace-nowrap text-left sm:text-right">
                          {application.nextStep || "No next step"}
                        </p>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </aside>

            <section className="panel job-scroll min-h-0 overflow-y-auto p-3 md:p-4 2xl:p-5">
              {visibleSelectedApplication ? (
                <div className="grid min-h-0 gap-3 2xl:gap-4">
                  <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start 2xl:gap-5">
                    <div className="flex min-w-0 items-start gap-2.5 2xl:gap-3">
                      <JobRoleIcon job={visibleSelectedApplication.job} large />
                      <div className="min-w-0 pt-0.5">
                        <h2 className="text-[20px] font-bold leading-[1.2] tracking-[-0.01em] text-foreground lg:text-[19px] min-[1400px]:text-[20px] min-[1500px]:text-[22px] 2xl:text-[24px]">
                          {visibleSelectedApplication.job.title}
                        </h2>
                        <p className="mt-1 text-[13px] font-semibold text-muted 2xl:mt-1.5 2xl:text-sm">
                          {visibleSelectedApplication.job.company}{" "}
                          <span className="text-foreground/35">•</span>{" "}
                          {visibleSelectedApplication.job.location}{" "}
                          <span className="text-foreground/35">•</span>{" "}
                          {visibleSelectedApplication.job.type}
                        </p>
                        {visibleSelectedApplication.job.applyUrl ||
                        visibleSelectedApplication.job.sourceUrl ? (
                          <a
                            href={getJobApplyUrl(
                              visibleSelectedApplication.job,
                            )}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-1 inline-flex items-center gap-1.5 text-[11px] font-bold text-accent hover:text-foreground 2xl:text-xs"
                          >
                            View job posting
                            <ExternalLink className="h-3.5 w-3.5" />
                          </a>
                        ) : (
                          <p className="mt-2 text-sm font-semibold text-muted">
                            {visibleSelectedApplication.job.salary}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="relative flex shrink-0 flex-wrap items-center justify-end gap-2 lg:max-w-[360px]">
                      <Button
                        type="button"
                        onClick={() =>
                          onPrepareApplication(visibleSelectedApplication.id)
                        }
                        className="h-10 rounded-md border border-[#e95300] bg-accent px-4 text-xs font-bold text-foreground shadow-[0_8px_20px_rgba(255,90,0,0.18)] hover:border-[#e95300] hover:bg-[#e95300] 2xl:h-11 2xl:text-[13px]"
                      >
                        <FileText className="h-4 w-4 2xl:h-5 2xl:w-5" />
                        Prepare application
                      </Button>
                      <button
                        type="button"
                        aria-label="Open AI info"
                        title="AI info"
                        onClick={() =>
                          openApplicationAiInfo(visibleSelectedApplication.id)
                        }
                        className="grid h-10 w-10 place-items-center rounded-md border border-border bg-[#fff8f1] text-muted transition hover:border-[#c0bbb6] hover:bg-[#fff3e8] hover:text-foreground 2xl:h-11 2xl:w-11"
                      >
                        <Info className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        aria-label="Application actions"
                        onClick={() =>
                          setIsApplicationMenuOpen((isOpen) => !isOpen)
                        }
                        className="grid h-10 w-10 place-items-center rounded-md border border-border bg-[#fff8f1] text-muted transition hover:border-[#c0bbb6] hover:bg-[#fff3e8] hover:text-foreground 2xl:h-11 2xl:w-11"
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </button>

                      {isApplicationMenuOpen && (
                        <div className="absolute right-0 top-12 z-30 grid w-[184px] gap-1 rounded-md border border-border bg-[#ffffff] p-1.5 shadow-[0_18px_40px_rgba(0,0,0,0.42)]">
                          <button
                            type="button"
                            onClick={openApplicationPosting}
                            disabled={
                              !visibleSelectedApplication.job.applyUrl &&
                              !visibleSelectedApplication.job.sourceUrl
                            }
                            className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#1d1e1c] hover:bg-[#fff3e8] disabled:cursor-not-allowed disabled:text-muted/45 disabled:hover:bg-transparent"
                          >
                            Open job posting
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              openApplicationAiInfo(
                                visibleSelectedApplication.id,
                              )
                            }
                            className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#1d1e1c] hover:bg-[#fff3e8]"
                          >
                            AI info
                          </button>
                          <div className="my-1 h-px bg-border" />
                          <p className="px-2 py-1 text-[10px] font-bold uppercase tracking-normal text-muted">
                            Change status
                          </p>
                          {trackedApplicationStatuses.map((item) => (
                            <button
                              key={item.status}
                              type="button"
                              onClick={() =>
                                changeApplicationStatus(item.status)
                              }
                              className={cn(
                                "rounded-md px-2 py-1.5 text-left text-[11px] font-bold hover:bg-[#fff3e8]",
                                visibleSelectedApplication.status ===
                                  item.status
                                  ? "text-accent"
                                  : "text-[#1d1e1c]",
                              )}
                            >
                              {item.label}
                            </button>
                          ))}
                          <div className="my-1 h-px bg-border" />
                          <button
                            type="button"
                            onClick={deleteSelectedApplication}
                            className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#fa5d00] hover:bg-[#fa5d00]/12"
                          >
                            Delete application
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="h-px bg-border" />

                  <section className="shrink-0 rounded-md border border-border bg-[#fff8f1] p-3 2xl:p-4">
                    <h3 className="text-[13px] font-bold text-foreground 2xl:text-sm">
                      Status timeline
                    </h3>
                    <div className="mt-2 space-y-0">
                      {timelineItems.map((item, index) => {
                        const event = item.event;

                        return (
                          <div
                            key={`${item.label}-${index}`}
                            className="grid grid-cols-[28px_minmax(0,1fr)] gap-2"
                          >
                            <div className="relative flex justify-center">
                              <span
                                className={cn(
                                  "z-10 mt-0.5 grid h-4 w-4 place-items-center rounded-full border",
                                  item.state === "done"
                                    ? "border-accent bg-accent text-foreground"
                                    : item.state === "rejected"
                                      ? "border-[#fa5d00] bg-[#fa5d00]/20 text-[#fa5d00]"
                                      : item.state === "canceled"
                                        ? "border-border bg-[#fff8f1] text-muted"
                                        : item.state === "current"
                                          ? "border-accent bg-accent/18"
                                          : "border-border bg-[#fff8f1]",
                                )}
                              >
                                {item.state === "done" && (
                                  <Check className="h-2.5 w-2.5" />
                                )}
                                {(item.state === "canceled" ||
                                  item.state === "rejected") && (
                                  <X className="h-2.5 w-2.5" />
                                )}
                              </span>
                              {index < timelineItems.length - 1 && (
                                <span
                                  className={cn(
                                    "absolute bottom-0 top-4 w-px",
                                    item.state === "done"
                                      ? "bg-accent"
                                      : "bg-[#fff8f1]",
                                  )}
                                />
                              )}
                            </div>
                            <div className="relative pb-1.5">
                              <div className="flex items-center justify-between gap-3">
                                <p
                                  className={cn(
                                    "text-[12px] font-bold 2xl:text-[13px]",
                                    item.state === "current"
                                      ? "text-accent"
                                      : item.state === "rejected"
                                        ? "text-[#fa5d00]"
                                        : "text-foreground",
                                  )}
                                >
                                  {item.label}
                                </p>
                                <div className="flex shrink-0 items-center gap-1.5">
                                  {item.state === "current" && (
                                    <span className="rounded-md border border-accent/30 bg-accent/12 px-2 py-0.5 text-[10px] font-bold text-accent">
                                      Current
                                    </span>
                                  )}
                                  {event?.status === "completed" && (
                                    <span className="rounded-md border border-success/30 bg-success/12 px-2 py-0.5 text-[10px] font-bold text-success">
                                      {getApplicationEventOutcomeLabel(
                                        event.outcome,
                                      ) || "Completed"}
                                    </span>
                                  )}
                                  {event?.status === "canceled" && (
                                    <span className="rounded-md border border-border bg-[#fff8f1] px-2 py-0.5 text-[10px] font-bold text-muted">
                                      Canceled
                                    </span>
                                  )}
                                  {event && (
                                    <button
                                      type="button"
                                      aria-label="Event actions"
                                      onClick={() =>
                                        setActiveEventMenuId((currentId) =>
                                          currentId === event.id
                                            ? ""
                                            : event.id,
                                        )
                                      }
                                      className="grid h-6 w-6 place-items-center rounded-md border border-border text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
                                    >
                                      <MoreHorizontal className="h-3.5 w-3.5" />
                                    </button>
                                  )}
                                </div>
                              </div>
                              <p className="mt-0.5 text-[10px] font-medium text-muted 2xl:text-[11px]">
                                {item.date}
                              </p>
                              {event && activeEventMenuId === event.id && (
                                <div className="absolute right-0 top-7 z-20 grid w-[158px] gap-1 rounded-md border border-border bg-[#ffffff] p-1.5 shadow-[0_16px_34px_rgba(0,0,0,0.38)]">
                                  <button
                                    type="button"
                                    onClick={() => openEditEventDialog(event)}
                                    className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#1d1e1c] hover:bg-[#fff3e8]"
                                  >
                                    Edit time
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      updateEvent(event, {
                                        status: "completed",
                                        outcome: "positive",
                                      })
                                    }
                                    className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#1d1e1c] hover:bg-[#fff3e8]"
                                  >
                                    Mark completed
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      updateEvent(event, {
                                        status: "canceled",
                                        outcome: undefined,
                                      })
                                    }
                                    className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#1d1e1c] hover:bg-[#fff3e8]"
                                  >
                                    Mark canceled
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      updateEvent(event, {
                                        status: "completed",
                                        outcome: "negative",
                                      })
                                    }
                                    className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#fa5d00] hover:bg-[#fa5d00]/12"
                                  >
                                    Mark rejected
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => deleteEvent(event.id)}
                                    className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#fa5d00] hover:bg-[#fa5d00]/12"
                                  >
                                    Delete
                                  </button>
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </section>

                  <section className="shrink-0 rounded-md border border-border bg-[#fff8f1] p-3 2xl:p-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0">
                        <h3 className="flex items-center gap-2 text-[13px] font-bold text-foreground 2xl:text-sm">
                          <Calendar className="h-3.5 w-3.5 text-accent" />
                          Next action
                        </h3>
                        <p className="mt-1 text-[12px] font-semibold text-[#1d1e1c] 2xl:text-[13px]">
                          {nextApplicationEvent
                            ? nextApplicationEvent.title
                            : "No event scheduled"}
                        </p>
                        <p className="mt-0.5 truncate text-[10px] text-muted 2xl:text-[11px]">
                          {nextApplicationEvent
                            ? `${formatApplicationEventDate(nextApplicationEvent.startsAt)} at ${formatApplicationEventTime(nextApplicationEvent.startsAt)}`
                            : "Schedule a screening, interview, assessment, or follow-up"}
                        </p>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        className="h-7 rounded-md border border-border bg-transparent px-3 text-[11px] text-[#1d1e1c] hover:bg-[#fff3e8]"
                        onClick={openScheduleDialog}
                      >
                        Schedule
                      </Button>
                    </div>
                  </section>

                  <section className="shrink-0">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-[13px] font-bold text-foreground 2xl:text-sm">
                        Documents used
                      </h3>
                      <label className="inline-flex h-7 cursor-pointer items-center gap-2 rounded-md border border-border bg-transparent px-2.5 text-[11px] font-semibold text-[#1d1e1c] transition hover:bg-[#fff3e8]">
                        <Upload className="h-3.5 w-3.5" />
                        Add document
                        <input
                          type="file"
                          accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/png,image/jpeg,image/webp"
                          className="hidden"
                          onChange={(event) => {
                            void attachApplicationDocument(
                              event.target.files?.[0],
                            );
                            event.currentTarget.value = "";
                          }}
                        />
                      </label>
                    </div>
                    <div className="mt-1.5 overflow-hidden rounded-md border border-border">
                      {visibleSelectedApplication.documents.length === 0 ? (
                        <div className="bg-[#fff8f1] px-2.5 py-3 text-[12px] font-semibold leading-5 text-muted 2xl:text-[13px]">
                          No documents attached yet.
                        </div>
                      ) : (
                        <div className="divide-y divide-border">
                          {visibleSelectedApplication.documents.map(
                            (document) => (
                              <div
                                key={document.id}
                                className="flex items-center gap-2.5 bg-[#fff8f1] px-2.5 py-1.5 text-[12px] font-semibold text-[#1d1e1c] 2xl:text-[13px]"
                              >
                                <span className="grid h-5 min-w-8 place-items-center rounded-sm bg-[#fa5d00] px-1 text-[7px] font-black leading-none text-foreground">
                                  {getApplicationDocumentBadge(document)}
                                </span>
                                <span
                                  className="min-w-0 flex-1 truncate"
                                  title={document.fileName}
                                >
                                  {document.title}
                                  {document.fileSize ? (
                                    <span className="font-medium text-muted">
                                      {" "}
                                      • {document.fileSize}
                                    </span>
                                  ) : null}
                                </span>
                                <Info className="h-3.5 w-3.5 shrink-0 text-muted" />
                                <a
                                  href={document.downloadUrl}
                                  download={document.fileName}
                                  aria-label={`Download ${document.fileName}`}
                                  title={`Download ${document.fileName}`}
                                  className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
                                >
                                  <Download className="h-3.5 w-3.5" />
                                </a>
                                <button
                                  type="button"
                                  aria-label={`Delete ${document.fileName}`}
                                  title={`Delete ${document.fileName}`}
                                  onClick={() =>
                                    void deleteApplicationDocument(document.id)
                                  }
                                  className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted transition hover:bg-[#fa5d00]/12 hover:text-[#fa5d00]"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            ),
                          )}
                        </div>
                      )}
                    </div>
                  </section>

                  <section className="min-h-0 shrink rounded-md border border-border bg-[#fff8f1] p-3 2xl:p-4">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-[13px] font-bold text-foreground 2xl:text-sm">
                        Notes
                      </h3>
                      <Button
                        variant="ghost"
                        className="h-7 rounded-md border border-border bg-transparent px-2.5 text-[11px] text-[#1d1e1c] hover:bg-[#fff3e8]"
                        onClick={openNotesDialog}
                      >
                        Edit note
                      </Button>
                    </div>
                    <p className="mt-1.5 line-clamp-2 text-[11px] leading-4 text-muted 2xl:text-xs 2xl:leading-5">
                      {getVisibleApplicationNotes(
                        visibleSelectedApplication.notes,
                      ) || "No notes yet."}
                    </p>
                  </section>
                </div>
              ) : (
                <div className="grid min-h-[320px] place-items-center text-center">
                  <div className="max-w-[360px]">
                    <Search className="mx-auto h-8 w-8 text-muted" />
                    <h3 className="mt-3 text-base font-bold text-foreground">
                      No matching application
                    </h3>
                    <p className="mt-2 text-sm leading-6 text-muted">
                      Adjust the search or choose another status filter.
                    </p>
                  </div>
                </div>
              )}
            </section>
          </>
        )}
      </div>

      {aiInfoApplication ? (
        <ApplicationAiInfoDialog
          application={aiInfoApplication}
          isAnalyzing={matchingApplicationIdSet.has(aiInfoApplication.id)}
          onClose={() => setAiInfoApplicationId("")}
        />
      ) : null}

      {isManualApplicationDialogOpen ? (
        <ManualApplicationDialog
          draft={manualApplicationDraft}
          profile={profile}
          isSaving={isManualApplicationSaving}
          error={manualApplicationError}
          onChange={updateManualApplicationDraft}
          onUseProfileResume={useProfileResumeForManualApplication}
          onAttachResume={attachManualApplicationResume}
          onClose={() => setIsManualApplicationDialogOpen(false)}
          onSave={() => void saveManualApplication()}
        />
      ) : null}

      {isNotesDialogOpen && visibleSelectedApplication ? (
        <ApplicationNotesDialog
          application={visibleSelectedApplication}
          notes={applicationNotesDraft}
          onChange={setApplicationNotesDraft}
          onClear={() => setApplicationNotesDraft("")}
          onClose={() => setIsNotesDialogOpen(false)}
          onSave={saveApplicationNotes}
        />
      ) : null}

      {isScheduleDialogOpen && eventDraft && visibleSelectedApplication ? (
        <ApplicationEventDialog
          application={visibleSelectedApplication}
          draft={eventDraft}
          onChange={updateEventDraft}
          onClose={() => {
            setIsScheduleDialogOpen(false);
            setEventDraft(null);
          }}
          onSave={saveEventDraft}
        />
      ) : null}
    </section>
  );
}
