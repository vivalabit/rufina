"use client";

import { useEffect, useState } from "react";
import {
  BriefcaseBusiness,
  ChevronLeft,
  ChevronRight,
  Plus,
  Search,
  Send,
  Sparkles,
} from "lucide-react";

import type { AssistantLaunch } from "@/components/assistant-view";
import { Button } from "@/components/ui/button";
import { DashboardGreeting, useHydrationSafeCurrentTime } from "@/components/dashboard-greeting";
import { JobRoleIcon } from "@/components/job-visuals";
import { assistantPrompts } from "@/features/app-shell/model/assistant-prompts";
import {
  formatApplicationEventDate,
  formatApplicationEventTime,
} from "@/features/applications/formatting";
import { formatCalendarLongDate } from "@/features/calendar/formatting";
import { calendarWeekdays } from "@/features/calendar/model/constants";
import { getCalendarDateKey } from "@/features/calendar/model/date-grid";
import {
  buildDashboardApplicationStatusOverview,
  buildDashboardCalendarModel,
  countDashboardActiveApplications,
  countDashboardStrongMatches,
  countDashboardUpcomingInterviews,
  findDashboardEventApplication,
  selectRecommendedDashboardJobs,
  selectUpcomingDashboardEvents,
} from "@/features/dashboard/model/selectors";
import {
  formatMatchValue,
  hasDisplayableMatch,
} from "@/features/jobs/model/ai-match";
import { getProfileCompletion } from "@/features/profile/model/selectors";
import { createClientId } from "@/lib/client-id";
import { cn } from "@/lib/utils";
import type {
  ApplicationEvent,
  TrackedApplication,
} from "@/shared/types/application";
import type { Job } from "@/shared/types/job";
import type { CandidateProfile } from "@/shared/types/profile";

type DashboardKpiIconName = "lucide:search" | "tabler:target-arrow" | "lucide:hourglass" | "lucide:users-round";

function DashboardKpiIcon({ icon, className }: { icon: DashboardKpiIconName; className?: string }) {
  const sharedProps = {
    className,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    strokeWidth: 2,
    "aria-hidden": true,
  };

  if (icon === "tabler:target-arrow") {
    return (
      <svg {...sharedProps}>
        <path d="M11 12a1 1 0 1 0 2 0a1 1 0 1 0-2 0" />
        <path d="M12 7a5 5 0 1 0 5 5" />
        <path d="M13 3.055A9 9 0 1 0 20.941 11" />
        <path d="M15 6v3h3l3-3h-3V3zm0 3-3 3" />
      </svg>
    );
  }

  if (icon === "lucide:hourglass") {
    return (
      <svg {...sharedProps}>
        <path d="M5 22h14M5 2h14m-2 20v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2" />
      </svg>
    );
  }

  if (icon === "lucide:users-round") {
    return (
      <svg {...sharedProps}>
        <path d="M18 21a8 8 0 0 0-16 0" />
        <circle cx="10" cy="8" r="5" />
        <path d="M22 20c0-3.37-2-6.5-4-8a5 5 0 0 0-.45-8.3" />
      </svg>
    );
  }

  return (
    <svg {...sharedProps}>
      <path d="m21 21-4.34-4.34" />
      <circle cx="11" cy="11" r="8" />
    </svg>
  );
}

export function DashboardView({
  profile,
  jobs,
  applications,
  events,
  isLoading,
  onStartSearch,
  onOpenJobs,
  onOpenJob,
  onOpenApplications,
  onOpenCalendar,
  onOpenAssistant,
}: {
  profile: CandidateProfile;
  jobs: Job[];
  applications: TrackedApplication[];
  events: ApplicationEvent[];
  isLoading: boolean;
  onStartSearch: () => void;
  onOpenJobs: () => void;
  onOpenJob: (jobId: string) => void;
  onOpenApplications: (applicationId?: string) => void;
  onOpenCalendar: () => void;
  onOpenAssistant: (prompt?: string, contextKind?: AssistantLaunch["contextKind"], contextId?: string) => void;
}) {
  const currentTime = useHydrationSafeCurrentTime();
  const [dashboardMonthOffset, setDashboardMonthOffset] = useState(0);
  const now = currentTime?.getTime() ?? Number.NEGATIVE_INFINITY;
  const jobSortNowMs = Date.now();
  const profileCompletion = getProfileCompletion(profile, createClientId);
  const recommendedJobs = selectRecommendedDashboardJobs(
    jobs,
    jobSortNowMs,
  );
  const upcomingEvents = selectUpcomingDashboardEvents(events, now);
  const nearestUpcomingEvents = upcomingEvents.slice(0, 2);
  const upcomingInterviewCount = countDashboardUpcomingInterviews(upcomingEvents);
  const nextEvent = upcomingEvents[0] ?? null;
  const nextEventApplication = findDashboardEventApplication(
    applications,
    nextEvent,
  );
  const strongMatches = countDashboardStrongMatches(jobs);
  const activeApplications = countDashboardActiveApplications(applications);
  const statusOverview = buildDashboardApplicationStatusOverview(applications);
  const visibleStatusCount = statusOverview.filter((item) => item.count > 0).length;
  const {
    month: dashboardCalendarMonth,
    days: dashboardCalendarDays,
    monthLabel: dashboardMonthLabel,
    todayKey,
    eventDateKeys,
  } = buildDashboardCalendarModel({
    currentTime,
    upcomingEvents,
    events,
    monthOffset: dashboardMonthOffset,
  });
  const statCards: Array<{
    label: string;
    value: string;
    note: string;
    icon: DashboardKpiIconName;
    onClick: () => void;
  }> = [
    {
      label: "New Matches",
      value: jobs.length.toString(),
      note: "New opportunities",
      icon: "lucide:search",
      onClick: onOpenJobs,
    },
    {
      label: "Strong Matches",
      value: strongMatches.toString(),
      note: "High match score",
      icon: "tabler:target-arrow",
      onClick: onOpenJobs,
    },
    {
      label: "In Progress",
      value: activeApplications.toString(),
      note: "Active applications",
      icon: "lucide:hourglass",
      onClick: () => onOpenApplications(),
    },
    {
      label: "Interviews",
      value: upcomingInterviewCount.toString(),
      note: "Upcoming interviews",
      icon: "lucide:users-round",
      onClick: onOpenCalendar,
    },
  ];

  useEffect(() => {
    const openSearch = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onStartSearch();
      }
    };
    window.addEventListener("keydown", openSearch);
    return () => window.removeEventListener("keydown", openSearch);
  }, [onStartSearch]);

  function openNextAssistantAction() {
    if (nextEvent && nextEventApplication && (nextEvent.type === "interview" || nextEvent.type === "screening")) {
      onOpenAssistant(assistantPrompts.prepareInterview, "application", nextEventApplication.id);
      return;
    }
    if (profileCompletion < 70) {
      onOpenAssistant(assistantPrompts.improveProfile, "profile");
      return;
    }
    onOpenAssistant("Review my current job search pipeline and give me the three highest-impact next actions.", "profile");
  }

  return (
    <section className="job-scroll flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto px-3 py-3 sm:px-4 2xl:px-5 2xl:py-4">
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_352px] 2xl:grid-cols-[minmax(0,1fr)_392px]">
        <div className="flex min-w-0 flex-col justify-between gap-5">
          <header className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
            <div className="max-w-3xl">
              <DashboardGreeting name={profile.name} currentTime={currentTime} />
              <p className="mt-4 max-w-2xl text-[13px] leading-5 text-muted 2xl:text-[15px] 2xl:leading-6">
                Keep your search, applications, documents, and next move in one calm place.
              </p>
            </div>
            <Button onClick={onStartSearch} className="h-11 shrink-0 px-5 text-[13px] active:scale-[0.98] 2xl:h-12 2xl:px-6 2xl:text-sm">
              <Search className="h-4 w-4" />
              Find opportunities
            </Button>
          </header>

          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4 2xl:gap-3">
            {statCards.map((stat) => (
              <button
                key={stat.label}
                type="button"
                onClick={stat.onClick}
                className="panel group min-h-[116px] p-3 text-left transition hover:-translate-y-0.5 hover:border-[#c0bbb6] hover:bg-[#fff3e8] active:scale-[0.985] 2xl:min-h-[132px] 2xl:p-4"
              >
                <div className="flex items-start gap-3">
                  <div className="grid h-11 w-11 shrink-0 place-items-center rounded-[14px] bg-accent/[0.14] text-accent 2xl:h-12 2xl:w-12">
                    <DashboardKpiIcon icon={stat.icon} className="h-5 w-5 2xl:h-6 2xl:w-6" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs text-[#1d1e1c] 2xl:text-sm">{stat.label}</p>
                    <p className="mt-1 text-[25px] font-bold leading-none 2xl:text-[29px]">{isLoading ? "—" : stat.value}</p>
                    <p className="mt-2 truncate text-[11px] text-muted 2xl:text-xs">{isLoading ? "Loading…" : stat.note}</p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>

        <section className="panel ml-8 h-[252px] p-3 2xl:h-[276px] 2xl:p-4" aria-label="Dashboard calendar">
          <div className="flex items-center justify-between">
            <button type="button" aria-label="Previous month" onClick={() => setDashboardMonthOffset((offset) => offset - 1)} className="grid h-7 w-7 place-items-center rounded-full text-muted transition hover:bg-[#fff3e8] hover:text-foreground active:scale-95">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <h2 className="text-xs font-bold 2xl:text-sm">{dashboardMonthLabel}</h2>
            <button type="button" aria-label="Next month" onClick={() => setDashboardMonthOffset((offset) => offset + 1)} className="grid h-7 w-7 place-items-center rounded-full text-muted transition hover:bg-[#fff3e8] hover:text-foreground active:scale-95">
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          <div className="mt-2 grid grid-cols-7 text-center text-[9px] font-medium text-muted 2xl:text-[10px]">
            {calendarWeekdays.map((day) => <span key={day}>{day.slice(0, 2)}</span>)}
          </div>
          <div className="mt-1.5 grid grid-cols-7 gap-y-0.5 text-center text-[10px] 2xl:text-[11px]">
            {dashboardCalendarDays.map((date) => {
              const dateKey = getCalendarDateKey(date);
              const isCurrentMonth = date.getMonth() === dashboardCalendarMonth.getMonth();
              const hasEvent = eventDateKeys.has(dateKey);
              const isToday = dateKey === todayKey;
              return (
                <button
                  key={dateKey}
                  type="button"
                  onClick={onOpenCalendar}
                  aria-label={`Open calendar for ${formatCalendarLongDate(date)}`}
                  className={cn(
                    "mx-auto grid h-6 w-6 place-items-center rounded-full transition active:scale-90 2xl:h-7 2xl:w-7",
                    !isCurrentMonth && "text-muted/50",
                    hasEvent && "bg-accent text-white shadow-[0_5px_14px_rgba(250,93,0,0.22)]",
                    !hasEvent && isToday && "border border-accent text-accent",
                    !hasEvent && !isToday && "hover:bg-[#fff3e8]",
                  )}
                >
                  {date.getDate()}
                </button>
              );
            })}
          </div>
        </section>
      </div>

      <div className="mt-3 grid gap-3 xl:min-h-[390px] xl:flex-1 xl:grid-cols-[minmax(0,1.18fr)_minmax(360px,0.96fr)_352px] 2xl:grid-cols-[minmax(0,1.18fr)_minmax(360px,0.96fr)_392px]">
        <section className="panel flex min-h-[360px] flex-col overflow-hidden p-3 2xl:p-4">
          <div className="flex items-center justify-between border-b border-border pb-3">
            <h2 className="text-base font-bold 2xl:text-lg">Best Matches</h2>
            <button type="button" className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent transition hover:text-[#e95300] active:scale-[0.98] 2xl:text-sm" onClick={onOpenJobs}>
              View all jobs <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          {recommendedJobs.length > 0 ? (
            <div className="min-h-0 flex-1 overflow-hidden">
              {recommendedJobs.map((job) => (
                  <article key={job.id} className="grid min-h-[92px] grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-border px-2 py-2.5 last:border-0 hover:bg-[#fff3e8] 2xl:min-h-[104px]">
                    <button type="button" className="grid min-w-0 grid-cols-[46px_minmax(0,1fr)] items-center gap-3 text-left active:scale-[0.995]" onClick={() => onOpenJob(job.id)}>
                      <JobRoleIcon job={job} />
                      <span className="grid min-w-0 gap-2 sm:grid-cols-[minmax(130px,0.9fr)_minmax(160px,1.1fr)] sm:items-center">
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold 2xl:text-base">{job.title}</span>
                          <span className="mt-1 block truncate text-xs text-muted">{job.company}</span>
                          <span className="mt-0.5 block truncate text-[11px] text-muted">{job.location} · {job.type}</span>
                        </span>
                        <span className="min-w-0">
                          {hasDisplayableMatch(job) ? <span className="inline-flex rounded-full bg-[#eaf7e9] px-2 py-1 text-[10px] font-semibold text-[#237a31] 2xl:text-[11px]">{formatMatchValue(job)} match</span> : null}
                          <span className="mt-2 flex min-w-0 gap-1.5 overflow-hidden">
                            {job.skills.slice(0, 3).map((skill) => <span key={skill} className="tag max-w-[104px] truncate">{skill}</span>)}
                          </span>
                        </span>
                      </span>
                    </button>
                    <Button variant="outline" size="sm" className="mr-1 h-9 border-accent/55 px-4 text-accent hover:bg-accent hover:text-white active:scale-95" onClick={() => onOpenJob(job.id)}>Open</Button>
                  </article>
              ))}
            </div>
          ) : (
            <button type="button" onClick={onOpenJobs} className="grid min-h-0 flex-1 place-items-center rounded-[14px] border border-dashed border-border px-4 text-center hover:border-accent/40 hover:bg-accent/[0.025]">
              <span><BriefcaseBusiness className="mx-auto h-7 w-7 text-muted" /><span className="mt-2 block text-sm font-bold">No matches yet</span><span className="mt-1 block text-xs text-muted">Start a search to add vacancies.</span></span>
            </button>
          )}
        </section>

        <section className="panel flex min-h-[360px] flex-col p-3 2xl:p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold 2xl:text-lg">Application Overview</h2>
            <span className="rounded-full border border-border px-3 py-1 text-[11px] text-muted 2xl:text-xs">All time</span>
          </div>
          <div className="grid flex-1 items-center gap-4 sm:grid-cols-[148px_minmax(0,1fr)] 2xl:grid-cols-[162px_minmax(0,1fr)]">
            <button type="button" aria-label={`Open ${applications.length} applications`} onClick={() => onOpenApplications()} className="group relative mx-auto h-[148px] w-[148px] rounded-full transition hover:scale-[1.025] active:scale-[0.985] 2xl:h-[162px] 2xl:w-[162px]">
              <svg viewBox="0 0 120 120" className="absolute inset-0 h-full w-full -rotate-90 overflow-visible drop-shadow-[0_5px_12px_rgba(29,30,28,0.18)]" aria-hidden="true">
                <circle cx="60" cy="60" r="47" pathLength="100" fill="none" stroke="#eee9e3" strokeWidth="10" />
                {statusOverview.map((item) => {
                  if (item.arcPercentage === 0) return null;
                  const segmentLength = visibleStatusCount > 1 ? Math.max(item.arcPercentage - 1.4, 0) : item.arcPercentage;
                  return <circle key={item.status} cx="60" cy="60" r="47" pathLength="100" fill="none" stroke={item.color} strokeWidth="10" strokeLinecap="round" strokeDasharray={`${segmentLength} ${100 - segmentLength}`} strokeDashoffset={-item.arcOffset} className="transition-[stroke-width,opacity] group-hover:[stroke-width:11]" />;
                })}
              </svg>
              <span className="absolute inset-[32px] grid place-items-center rounded-full border border-border bg-white shadow-[0_5px_18px_rgba(29,30,28,0.10)] 2xl:inset-[35px]">
                <span className="text-center"><span className="block text-[28px] font-bold leading-none tracking-tight">{isLoading ? "—" : applications.length}</span><span className="mt-2 block text-[10px] font-medium uppercase tracking-[0.16em] text-muted">Total</span></span>
              </span>
            </button>
            <div className="space-y-2.5">
              {statusOverview.map((item) => (
                <button key={item.status} type="button" onClick={() => onOpenApplications()} className="flex w-full items-center gap-2.5 rounded-md px-1.5 py-1 text-left text-xs transition hover:bg-[#fff3e8] active:scale-[0.99] 2xl:text-sm">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color, boxShadow: `0 0 8px ${item.color}55` }} />
                  <span className="flex-1 text-muted">{item.label}</span>
                  <span className="text-[#4a4a47]">{item.count} <span className="text-muted">({item.percentage}%)</span></span>
                </button>
              ))}
            </div>
          </div>
          <button type="button" onClick={() => onOpenApplications()} className="inline-flex w-fit items-center gap-1.5 text-[13px] font-semibold text-accent transition hover:text-[#e95300] active:scale-[0.98] 2xl:text-sm">Open applications <ChevronRight className="h-4 w-4" /></button>
        </section>

        <aside className="ml-8 grid min-h-[445px] gap-3 xl:grid-rows-[minmax(213px,0.82fr)_minmax(220px,1fr)]">
          <section className="panel flex min-h-0 flex-col overflow-hidden p-3 2xl:p-4">
            <h2 className="text-base font-bold 2xl:text-lg">Upcoming Events</h2>
            <div className="mt-2 grid gap-1.5">
              {nearestUpcomingEvents.length > 0 ? nearestUpcomingEvents.map((event) => {
                const application = applications.find((item) => item.id === event.applicationId);
                return (
                  <button key={event.id} type="button" onClick={() => application ? onOpenApplications(application.id) : onOpenCalendar()} className="flex min-h-[56px] w-full items-start gap-2.5 rounded-[12px] border border-border p-2.5 text-left transition hover:border-accent/35 hover:bg-[#fff3e8] active:scale-[0.99]">
                    <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-accent" />
                    <span className="min-w-0">
                      <span className="block truncate text-[10px] text-muted 2xl:text-[11px]">{formatApplicationEventDate(event.startsAt)} · {formatApplicationEventTime(event.startsAt)}</span>
                      <span className="mt-1 block truncate text-xs font-semibold 2xl:text-[13px]">{event.title}</span>
                    </span>
                  </button>
                );
              }) : (
                <button type="button" onClick={onOpenCalendar} className="flex w-full items-center justify-between rounded-[12px] border border-dashed border-border p-3 text-left text-xs text-muted hover:border-accent/40 hover:text-foreground">No upcoming events <Plus className="h-4 w-4" /></button>
              )}
            </div>
            <button type="button" onClick={onOpenCalendar} className="mt-auto inline-flex items-center self-end pt-1 text-[11px] font-semibold text-accent transition hover:text-[#e95300] active:scale-[0.98] 2xl:text-xs">View calendar <ChevronRight className="ml-1 h-4 w-4" /></button>
          </section>

          <section className="panel flex min-h-0 flex-col p-3 2xl:p-4">
            <div className="flex items-center gap-2.5"><Sparkles className="h-5 w-5 text-accent" /><h2 className="text-base font-bold 2xl:text-lg">Rufina AI</h2></div>
            <button type="button" onClick={openNextAssistantAction} className="mt-3 flex-1 rounded-[12px] border border-border bg-[#fffaf5] p-3 text-left text-xs leading-5 text-[#4a4a47] transition hover:border-accent/35 hover:bg-[#fff3e8] active:scale-[0.99] 2xl:text-sm">
              {nextEventApplication ? `I can help you prepare for ${nextEventApplication.job.company}. Review the role and plan the next step.` : profileCompletion < 70 ? `Your profile is ${profileCompletion}% complete. Let’s strengthen it for better matches.` : "Let’s review your pipeline and choose the three highest-impact next moves."}
            </button>
            <Button className="mt-2 h-10 w-full active:scale-[0.98]" onClick={openNextAssistantAction}>Review</Button>
            <Button variant="outline" className="mt-2 h-10 w-full border-accent/55 text-accent hover:bg-[#fff3e8] active:scale-[0.98]" onClick={() => onOpenAssistant()}> <Send className="h-4 w-4" /> New chat</Button>
          </section>
        </aside>
      </div>
    </section>
  );
}
