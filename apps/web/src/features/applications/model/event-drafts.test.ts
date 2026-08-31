import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createApplicationEvent,
  createDefaultEventDraft,
  createEventDraftFromEvent,
  getLocalTimezone,
  toDateTimeLocalValue,
} from "@/features/applications/model/event-drafts";
import type {
  ApplicationEvent,
  ApplicationEventDraft,
  TrackedApplication,
} from "@/shared/types/application";
import type { Job } from "@/shared/types/job";

const job = {
  id: "job-1",
  company: "Acme",
  title: "Product Engineer",
} as Job;

const application: TrackedApplication = {
  id: "application-1",
  job,
  status: "applied",
  appliedAt: "2026-08-01T08:00:00.000Z",
  nextStep: "",
  notes: "",
  documents: [],
};

describe("application event drafts", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 7, 31, 8, 15));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("creates a default screening five days ahead in the local timezone", () => {
    const draft = createDefaultEventDraft(application);

    expect(draft).toEqual({
      type: "screening",
      status: "scheduled",
      outcome: "",
      title: "Acme screening",
      startsAt: toDateTimeLocalValue(new Date(2026, 8, 5, 10)),
      durationMinutes: "30",
      timezone: getLocalTimezone(),
      location: "",
      notes: "",
    });
  });

  it("round-trips an existing event into an editable draft", () => {
    const event: ApplicationEvent = {
      id: "event-1",
      applicationId: application.id,
      type: "interview",
      status: "completed",
      outcome: "positive",
      title: "Technical interview",
      startsAt: "2026-09-02T08:30:00.000Z",
      durationMinutes: 60,
      timezone: "Europe/Zurich",
      location: "Meet",
      notes: "Bring questions",
    };

    expect(createEventDraftFromEvent(event)).toEqual({
      id: "event-1",
      type: "interview",
      status: "completed",
      outcome: "positive",
      title: "Technical interview",
      startsAt: toDateTimeLocalValue(new Date(event.startsAt)),
      durationMinutes: "60",
      timezone: "Europe/Zurich",
      location: "Meet",
      notes: "Bring questions",
    });
  });

  it("normalizes a draft and keeps outcomes only for completed events", () => {
    const draft: ApplicationEventDraft = {
      id: "event-2",
      type: "offer_deadline",
      status: "scheduled",
      outcome: "positive",
      title: "   ",
      startsAt: "2026-09-03T11:45",
      durationMinutes: "not-a-number",
      timezone: "  ",
      location: "  Zurich  ",
      notes: "  Review package  ",
    };

    const event = createApplicationEvent(application.id, draft);

    expect(event).toMatchObject({
      id: "event-2",
      applicationId: application.id,
      type: "offer_deadline",
      status: "scheduled",
      outcome: undefined,
      title: "Offer deadline",
      startsAt: new Date(draft.startsAt).toISOString(),
      durationMinutes: 30,
      timezone: getLocalTimezone(),
      location: "Zurich",
      notes: "Review package",
    });
  });
});
