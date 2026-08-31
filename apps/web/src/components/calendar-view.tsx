"use client";

import { useMemo, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Plus,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { assistantPrompts } from "@/features/app-shell/model/assistant-prompts";
import {
  formatApplicationEventTime,
  getApplicationEventTypeLabel,
} from "@/features/applications/formatting";
import {
  applicationEventTypes,
} from "@/features/applications/model/constants";
import {
  createApplicationEvent,
  createEventDraftFromEvent,
  getLocalTimezone,
  toDateTimeLocalValue,
} from "@/features/applications/model/event-drafts";
import {
  formatCalendarMonthLabel,
  formatInterviewPreparationPrompt,
} from "@/features/calendar/formatting";
import {
  calendarEventTheme,
  calendarWeekdays,
} from "@/features/calendar/model/constants";
import {
  getCalendarDateKey,
  getCalendarMonthDays,
  getCalendarWeekDays,
} from "@/features/calendar/model/date-grid";
import { createCalendarDemoEvents } from "@/features/calendar/model/demo-events";
import {
  filterCalendarEventsByType,
  findCalendarEventApplication,
  getCalendarEventCompany,
  selectCalendarDisplayEvents,
  selectCalendarMonthEvents,
  selectNextCalendarInterview,
  selectUpcomingCalendarEvents,
} from "@/features/calendar/model/selectors";
import type {
  CalendarEventFilter,
  CalendarMode,
} from "@/features/calendar/model/types";
import { sortApplicationEvents } from "@/features/applications/model/selectors";
import { cn } from "@/lib/utils";
import type {
  ApplicationEvent,
  ApplicationEventDraft,
  ApplicationEventType,
  TrackedApplication,
} from "@/shared/types/application";

export function CalendarView({
  applications,
  events,
  demoMode,
  onOpenAssistant,
  onSaveEvent,
  onDeleteEvent,
}: {
  applications: TrackedApplication[];
  events: ApplicationEvent[];
  demoMode: boolean;
  onOpenAssistant: (prompt: string, applicationId: string) => void;
  onSaveEvent: (event: ApplicationEvent) => void;
  onDeleteEvent: (eventId: string) => void;
}) {
  const today = useMemo(() => new Date(), []);
  const [visibleMonth, setVisibleMonth] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1));
  const [selectedDate, setSelectedDate] = useState(today);
  const [mode, setMode] = useState<CalendarMode>("month");
  const [activeType, setActiveType] = useState<CalendarEventFilter>("all");
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [eventDraft, setEventDraft] = useState<ApplicationEventDraft | null>(null);
  const [draftApplicationId, setDraftApplicationId] = useState("");
  const demoEvents = useMemo(
    () =>
      demoMode
        ? createCalendarDemoEvents(visibleMonth, getLocalTimezone())
        : [],
    [demoMode, visibleMonth],
  );
  const displayEvents = selectCalendarDisplayEvents(events, demoEvents);
  const filteredEvents = filterCalendarEventsByType(displayEvents, activeType);
  const monthDays = getCalendarMonthDays(visibleMonth);
  const monthRowCount = monthDays.length / 7;
  const weekDays = getCalendarWeekDays(selectedDate);
  const todayKey = getCalendarDateKey(today);
  const monthLabel = formatCalendarMonthLabel(visibleMonth);
  const calendarEvents = selectCalendarMonthEvents(
    filteredEvents,
    visibleMonth,
  );
  const upcomingEvents = selectUpcomingCalendarEvents(
    filteredEvents,
    today.getTime(),
  );
  const nextInterview = selectNextCalendarInterview(
    displayEvents,
    today.getTime(),
  );

  function prepareForNextInterview() {
    if (!nextInterview) return;
    const application = findCalendarEventApplication(
      applications,
      nextInterview,
    );
    const prompt = formatInterviewPreparationPrompt(
      nextInterview,
      application,
      assistantPrompts.prepareInterview,
    );

    onOpenAssistant(prompt, application?.id ?? "");
  }

  function moveMonth(offset: number) {
    const next = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + offset, 1);
    setVisibleMonth(next);
    setSelectedDate(next);
  }

  function goToToday() {
    const now = new Date();
    setVisibleMonth(new Date(now.getFullYear(), now.getMonth(), 1));
    setSelectedDate(now);
  }

  function openNewEvent(date = selectedDate) {
    const start = new Date(date);
    start.setHours(10, 0, 0, 0);
    const application = applications[0];

    setDraftApplicationId(application?.id ?? "calendar-standalone");
    setEventDraft({
      type: "interview",
      status: "scheduled",
      outcome: "",
      title: application ? `${application.job.company} interview` : "New event",
      startsAt: toDateTimeLocalValue(start),
      durationMinutes: "30",
      timezone: getLocalTimezone(),
      location: "",
      notes: "",
    });
  }

  function openEvent(event: ApplicationEvent) {
    setDraftApplicationId(event.applicationId || "calendar-standalone");
    setEventDraft(createEventDraftFromEvent(event));
  }

  function updateDraft<Field extends keyof ApplicationEventDraft>(field: Field, value: ApplicationEventDraft[Field]) {
    setEventDraft((current) => current ? { ...current, [field]: value } : current);
  }

  function saveDraft() {
    if (!eventDraft?.title.trim() || !eventDraft.startsAt) return;
    onSaveEvent(createApplicationEvent(draftApplicationId || "calendar-standalone", eventDraft));
    setEventDraft(null);
  }

  function deleteDraft() {
    if (!eventDraft?.id) return;
    onDeleteEvent(eventDraft.id);
    setEventDraft(null);
  }

  function renderEventCard(event: ApplicationEvent, compact = false) {
    const theme = calendarEventTheme[event.type];
    return (
      <button
        key={event.id}
        type="button"
        data-calendar-event-density={compact ? "compact" : "full"}
        onClick={(clickEvent) => {
          clickEvent.stopPropagation();
          openEvent(event);
        }}
        className={cn(
          "w-full rounded-md border text-left transition",
          compact ? "px-2 py-1" : "px-2.5 py-2",
          theme.border,
        )}
      >
        <p className="flex items-center gap-1.5 truncate text-[10px] font-medium text-[#4a4a47] 2xl:text-[11px]">
          <span className={cn("h-2 w-2 shrink-0 rounded-full", theme.dot)} />
          {formatApplicationEventTime(event.startsAt)}
          {!compact ? <span className="ml-auto truncate font-semibold text-[#615f5c]">{getApplicationEventTypeLabel(event.type).replace(" deadline", "")}</span> : null}
        </p>
        <p className={cn("truncate font-bold text-foreground", compact ? "mt-0.5 text-[10px] 2xl:text-[11px]" : "mt-1 text-[11px] 2xl:text-xs")}>
          {event.title}
        </p>
        {!compact ? (
          <span className={cn("mt-1.5 inline-flex rounded border px-1.5 py-0.5 text-[9px] font-bold", theme.badge)}>
            {getApplicationEventTypeLabel(event.type).replace(" deadline", "")}
          </span>
        ) : null}
      </button>
    );
  }

  return (
    <section className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
      <header className="flex shrink-0 items-center justify-between gap-4">
        <h1 className="page-title text-[24px] leading-tight text-foreground sm:text-[27px] 2xl:text-[31px]">
          Calendar
        </h1>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            disabled={!nextInterview}
            title={nextInterview ? `Prepare for ${nextInterview.title}` : "No upcoming interview"}
            onClick={prepareForNextInterview}
            className="h-10 rounded-md border border-accent/40 bg-accent/[0.055] px-3 text-[12px] font-bold text-foreground hover:bg-accent/[0.11] disabled:cursor-not-allowed disabled:opacity-45 2xl:h-11 2xl:px-4 2xl:text-[13px]"
          >
            <Sparkles className="h-4 w-4 text-accent" />
            <span className="hidden sm:inline">Prepare next interview</span>
            <span className="sm:hidden">Prepare</span>
          </Button>
          <Button
            onClick={() => openNewEvent()}
            className="h-10 rounded-md bg-gradient-to-r from-[#e95300] to-[#e95300] px-4 text-[13px] font-bold text-foreground shadow-[0_12px_28px_rgba(255,90,0,0.22)] hover:from-[#e95300] hover:to-[#e95300] 2xl:h-11 2xl:px-5"
          >
            <Plus className="h-4 w-4" />
            Add event
          </Button>
        </div>
      </header>

      <div className="mt-3 flex shrink-0 flex-wrap items-center gap-2.5 2xl:mt-4">
        <button type="button" aria-label="Previous month" onClick={() => moveMonth(-1)} className="grid h-10 w-10 place-items-center rounded-md border border-border bg-[#fff8f1] text-muted transition hover:bg-[#fff3e8] hover:text-foreground">
          <ChevronLeft className="h-5 w-5" />
        </button>
        <h2 className="min-w-[118px] text-base font-bold text-foreground 2xl:min-w-[132px] 2xl:text-lg">{monthLabel}</h2>
        <button type="button" aria-label="Next month" onClick={() => moveMonth(1)} className="grid h-10 w-10 place-items-center rounded-md border border-border bg-[#fff8f1] text-muted transition hover:bg-[#fff3e8] hover:text-foreground">
          <ChevronRight className="h-5 w-5" />
        </button>
        <button type="button" onClick={goToToday} className="ml-1 h-10 rounded-md border border-border bg-[#fff8f1] px-4 text-[12px] font-bold text-[#4a4a47] transition hover:bg-[#fff3e8] hover:text-foreground">Today</button>

        <div className="ml-auto flex h-10 items-center rounded-md border border-border bg-[#fff8f1] p-1">
          {(["month", "week", "agenda"] as CalendarMode[]).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setMode(item)}
              className={cn(
                "h-8 rounded px-4 text-[11px] font-bold capitalize transition 2xl:text-xs",
                mode === item ? "border border-accent/75 bg-accent/[0.08] text-[#e95300]" : "text-muted hover:text-foreground",
              )}
            >
              {item}
            </button>
          ))}
        </div>

        <div className="relative">
          <button type="button" onClick={() => setIsFilterOpen((open) => !open)} className={cn("flex h-10 items-center gap-2 rounded-md border px-3.5 text-[12px] font-bold transition", activeType === "all" ? "border-border bg-[#fff8f1] text-[#1d1e1c]" : "border-accent/45 bg-accent/[0.07] text-accent") }>
            <SlidersHorizontal className="h-4 w-4" />
            Filter
          </button>
          {isFilterOpen ? (
            <div className="absolute right-0 top-12 z-30 w-52 rounded-lg border border-border bg-white p-2 shadow-[6px_8px_28px_rgba(227,214,197,0.72)]">
              <button type="button" onClick={() => { setActiveType("all"); setIsFilterOpen(false); }} className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-xs font-semibold text-[#1d1e1c] hover:bg-[#fff3e8]">
                All events {activeType === "all" ? <Check className="h-4 w-4 text-accent" /> : null}
              </button>
              {applicationEventTypes.map((item) => (
                <button key={item.type} type="button" onClick={() => { setActiveType(item.type); setIsFilterOpen(false); }} className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-xs font-semibold text-[#4a4a47] hover:bg-[#fff3e8] hover:text-foreground">
                  {item.label} {activeType === item.type ? <Check className="h-4 w-4 text-accent" /> : null}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <div className="mt-3 grid min-h-0 flex-1 gap-3 xl:grid-cols-[minmax(0,1fr)_290px] 2xl:mt-4 2xl:gap-4 2xl:grid-cols-[minmax(0,1fr)_318px]">
        <div className="panel min-h-0 overflow-hidden">
          {mode === "month" ? (
            <div className="grid h-full grid-cols-7" style={{ gridTemplateRows: `42px repeat(${monthRowCount}, minmax(0, 1fr))` }}>
              {calendarWeekdays.map((day) => (
                <div key={day} className="grid place-items-center border-b border-r border-border text-[10px] font-bold text-[#4a4a47] last:border-r-0 2xl:text-xs">{day}</div>
              ))}
              {monthDays.map((date) => {
                const dateKey = getCalendarDateKey(date);
                const dayEvents = calendarEvents.filter((event) => getCalendarDateKey(new Date(event.startsAt)) === dateKey);
                const isCurrentMonth = date.getMonth() === visibleMonth.getMonth();
                const isToday = dateKey === todayKey;

                return (
                  <div
                    key={dateKey}
                    onClick={() => { setSelectedDate(date); openNewEvent(date); }}
                    className={cn(
                      "group relative min-h-0 overflow-hidden border-b border-r border-border p-2 text-left transition hover:bg-[#fff3e8] [&:nth-last-child(-n+7)]:border-b-0 [&:nth-child(7n)]:border-r-0 2xl:p-2.5",
                      !isCurrentMonth && "bg-black/[0.08] text-[#615f5c]",
                      isToday && "bg-accent/[0.025] shadow-[inset_0_0_0_1px_rgba(255,90,0,0.8)]",
                    )}
                  >
                    <span className={cn("inline-grid h-5 min-w-5 place-items-center rounded-full text-[11px] font-bold 2xl:h-6 2xl:min-w-6 2xl:text-xs", isToday ? "bg-accent text-foreground" : isCurrentMonth ? "text-[#1d1e1c]" : "text-[#615f5c]")}>{date.getDate()}</span>
                    <Plus className="absolute right-2 top-2 h-3.5 w-3.5 text-muted opacity-0 transition group-hover:opacity-100" />
                    {dayEvents.length > 0 ? <div className="mt-1 min-h-0 space-y-1 overflow-hidden">{dayEvents.slice(0, 1).map((event) => renderEventCard(event, true))}</div> : null}
                    {dayEvents.length > 1 ? <p className="mt-1 text-[9px] font-bold text-muted">+{dayEvents.length - 1} more</p> : null}
                  </div>
                );
              })}
            </div>
          ) : mode === "week" ? (
            <div className="grid h-full grid-cols-7 divide-x divide-border">
              {weekDays.map((date, index) => {
                const dateKey = getCalendarDateKey(date);
                const dayEvents = filteredEvents.filter((event) => getCalendarDateKey(new Date(event.startsAt)) === dateKey);
                return (
                  <div key={dateKey} onClick={() => openNewEvent(date)} className="min-w-0 overflow-hidden p-2 text-left hover:bg-[#fff3e8] 2xl:p-3">
                    <div className="border-b border-border pb-3 text-center">
                      <p className="text-[10px] font-bold uppercase tracking-wide text-muted">{calendarWeekdays[index].slice(0, 3)}</p>
                      <span className={cn("mt-1 inline-grid h-8 w-8 place-items-center rounded-full text-sm font-bold", dateKey === todayKey ? "bg-accent text-foreground" : "text-foreground")}>{date.getDate()}</span>
                    </div>
                    <div className="mt-3 space-y-2">{dayEvents.map((event) => renderEventCard(event))}</div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="h-full overflow-y-auto p-3 2xl:p-4">
              {calendarEvents.length > 0 ? sortApplicationEvents(calendarEvents).map((event) => {
                const date = new Date(event.startsAt);
                const theme = calendarEventTheme[event.type];
                return (
                  <button key={event.id} type="button" onClick={() => openEvent(event)} className="mb-2 grid w-full grid-cols-[58px_minmax(0,1fr)_auto] items-center gap-3 rounded-lg border border-border bg-[#fff8f1] p-3 text-left transition hover:bg-[#fff3e8]">
                    <div className="rounded-md border border-border bg-black/10 py-2 text-center"><p className="text-[9px] font-black uppercase text-muted">{date.toLocaleDateString("en-US", { month: "short" })}</p><p className="text-xl font-bold leading-none text-foreground">{date.getDate()}</p></div>
                    <div className="min-w-0"><p className="truncate text-sm font-bold text-foreground">{event.title}</p><p className="mt-1 truncate text-xs text-muted">{formatApplicationEventTime(event.startsAt)} • {getCalendarEventCompany(applications, event)}</p></div>
                    <span className={cn("rounded border px-2 py-1 text-[10px] font-bold", theme.badge)}>{getApplicationEventTypeLabel(event.type).replace(" deadline", "")}</span>
                  </button>
                );
              }) : <div className="grid h-full place-items-center text-sm text-muted">No events this month.</div>}
            </div>
          )}
        </div>

        <aside className="hidden min-h-0 h-full xl:block">
          <section className="panel h-full min-h-0 overflow-hidden p-3 2xl:p-4">
            <div className="flex items-center justify-between gap-3"><h2 className="text-sm font-bold text-foreground 2xl:text-base">Upcoming</h2><button type="button" onClick={() => setMode("agenda")} className="text-[10px] font-bold text-accent 2xl:text-xs">View calendar</button></div>
            <div className="mt-3 space-y-2 overflow-y-auto 2xl:mt-4">
              {upcomingEvents.length > 0 ? upcomingEvents.map((event) => {
                const date = new Date(event.startsAt);
                const theme = calendarEventTheme[event.type];
                return (
                  <button key={event.id} type="button" onClick={() => openEvent(event)} className="grid w-full grid-cols-[42px_minmax(0,1fr)_auto] items-center gap-2 rounded-md border border-border bg-[#fff8f1] p-2 text-left transition hover:bg-[#fff3e8] 2xl:grid-cols-[46px_minmax(0,1fr)_auto] 2xl:p-2.5">
                    <div className={cn("rounded-md border py-1 text-center", theme.badge)}><p className="text-[8px] font-black uppercase">{date.toLocaleDateString("en-US", { month: "short" })}</p><p className="text-lg font-bold leading-none text-foreground">{date.getDate()}</p></div>
                    <div className="min-w-0"><p className="truncate text-[10px] font-semibold text-[#4a4a47] 2xl:text-[11px]">{formatApplicationEventTime(event.startsAt)} • {getCalendarEventCompany(applications, event)}</p><p className="mt-1 truncate text-[10px] text-muted 2xl:text-[11px]">{event.notes || getApplicationEventTypeLabel(event.type)}</p></div>
                    <span className={cn("rounded border px-1.5 py-1 text-[8px] font-bold 2xl:text-[9px]", theme.badge)}>{getApplicationEventTypeLabel(event.type).replace(" deadline", "")}</span>
                  </button>
                );
              }) : <p className="rounded-md border border-dashed border-border p-4 text-xs leading-5 text-muted">No upcoming events.</p>}
            </div>
          </section>
        </aside>
      </div>

      {eventDraft ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur-sm" onMouseDown={(event) => { if (event.target === event.currentTarget) setEventDraft(null); }}>
          <div className="w-full max-w-[560px] rounded-xl border border-border bg-[#ffffff] shadow-[0_28px_90px_rgba(0,0,0,0.65)]">
            <div className="flex items-center justify-between border-b border-border px-5 py-4"><div><p className="text-xs font-bold uppercase tracking-[0.14em] text-accent">Calendar event</p><h2 className="mt-1 text-xl font-bold text-foreground">{eventDraft.id ? "Edit event" : "Add event"}</h2></div><button type="button" onClick={() => setEventDraft(null)} className="grid h-9 w-9 place-items-center rounded-md text-muted hover:bg-[#fff3e8] hover:text-foreground"><X className="h-5 w-5" /></button></div>
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <label className="sm:col-span-2"><span className="mb-1.5 block text-xs font-bold text-[#4a4a47]">Event title</span><input value={eventDraft.title} onChange={(event) => updateDraft("title", event.target.value)} autoFocus className="h-10 w-full rounded-md border border-border bg-[#fff8f1] px-3 text-sm text-foreground outline-none transition focus:border-accent/60" /></label>
              <label><span className="mb-1.5 block text-xs font-bold text-[#4a4a47]">Type</span><select value={eventDraft.type} onChange={(event) => updateDraft("type", event.target.value as ApplicationEventType)} className="h-10 w-full rounded-md border border-border bg-[#ffffff] px-3 text-sm text-foreground outline-none focus:border-accent/60">{applicationEventTypes.map((item) => <option key={item.type} value={item.type}>{item.label}</option>)}</select></label>
              <label><span className="mb-1.5 block text-xs font-bold text-[#4a4a47]">Application</span><select value={draftApplicationId} onChange={(event) => setDraftApplicationId(event.target.value)} className="h-10 w-full rounded-md border border-border bg-[#ffffff] px-3 text-sm text-foreground outline-none focus:border-accent/60"><option value="calendar-standalone">Personal event</option>{applications.map((application) => <option key={application.id} value={application.id}>{application.job.company} — {application.job.title}</option>)}</select></label>
              <label><span className="mb-1.5 block text-xs font-bold text-[#4a4a47]">Date &amp; time</span><input type="datetime-local" value={eventDraft.startsAt} onChange={(event) => updateDraft("startsAt", event.target.value)} className="h-10 w-full rounded-md border border-border bg-[#fff8f1] px-3 text-sm text-foreground outline-none focus:border-accent/60 [color-scheme:light]" /></label>
              <label><span className="mb-1.5 block text-xs font-bold text-[#4a4a47]">Duration</span><select value={eventDraft.durationMinutes} onChange={(event) => updateDraft("durationMinutes", event.target.value)} className="h-10 w-full rounded-md border border-border bg-[#ffffff] px-3 text-sm text-foreground outline-none focus:border-accent/60">{[15, 30, 45, 60, 90].map((minutes) => <option key={minutes} value={minutes}>{minutes} minutes</option>)}</select></label>
              <label className="sm:col-span-2"><span className="mb-1.5 block text-xs font-bold text-[#4a4a47]">Location or link</span><input value={eventDraft.location} onChange={(event) => updateDraft("location", event.target.value)} placeholder="Google Meet, office, phone..." className="h-10 w-full rounded-md border border-border bg-[#fff8f1] px-3 text-sm text-foreground outline-none placeholder:text-muted focus:border-accent/60" /></label>
              <label className="sm:col-span-2"><span className="mb-1.5 block text-xs font-bold text-[#4a4a47]">Notes</span><textarea value={eventDraft.notes} onChange={(event) => updateDraft("notes", event.target.value)} rows={3} className="w-full resize-none rounded-md border border-border bg-[#fff8f1] px-3 py-2 text-sm text-foreground outline-none focus:border-accent/60" /></label>
            </div>
            <div className="flex items-center justify-between border-t border-border px-5 py-4">
              <div>{eventDraft.id ? <button type="button" onClick={deleteDraft} className="flex h-9 items-center gap-2 rounded-md px-3 text-xs font-bold text-accent hover:bg-[#fa5d00]/10"><Trash2 className="h-4 w-4" />Delete</button> : null}</div>
              <div className="flex gap-2"><button type="button" onClick={() => setEventDraft(null)} className="h-9 rounded-md border border-border px-4 text-xs font-bold text-[#1d1e1c] hover:bg-[#fff3e8]">Cancel</button><button type="button" onClick={saveDraft} disabled={!eventDraft.title.trim() || !eventDraft.startsAt} className="h-9 rounded-md bg-gradient-to-r from-[#e95300] to-[#e95300] px-5 text-xs font-bold text-foreground disabled:cursor-not-allowed disabled:opacity-40">Save event</button></div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}


