import type { ApplicationEvent } from "@/shared/types/application";

export function createCalendarDemoEvents(
  month: Date,
  timezone: string,
): ApplicationEvent[] {
  const at = (day: number, hour: number) =>
    new Date(
      month.getFullYear(),
      month.getMonth(),
      day,
      hour,
      0,
      0,
      0,
    ).toISOString();

  return [
    {
      id: "demo-assessment",
      applicationId: "",
      type: "assessment",
      status: "scheduled",
      title: "Technical Assessment",
      startsAt: at(8, 10),
      durationMinutes: 60,
      timezone,
      location: "Online",
      notes: "Assessment",
    },
    {
      id: "demo-interview-wealth",
      applicationId: "",
      type: "interview",
      status: "scheduled",
      title: "Future Wealth Group",
      startsAt: at(15, 13),
      durationMinutes: 45,
      timezone,
      location: "Video call",
      notes: "Interview",
    },
    {
      id: "demo-interview-belimo",
      applicationId: "",
      type: "interview",
      status: "scheduled",
      title: "Belimo",
      startsAt: at(17, 13),
      durationMinutes: 45,
      timezone,
      location: "Video call",
      notes: "Interview",
    },
    {
      id: "demo-follow-up",
      applicationId: "",
      type: "follow_up",
      status: "scheduled",
      title: "Follow-up",
      startsAt: at(21, 10),
      durationMinutes: 15,
      timezone,
      location: "",
      notes: "Send thank you email",
    },
    {
      id: "demo-offer",
      applicationId: "",
      type: "offer_deadline",
      status: "scheduled",
      title: "Offer",
      startsAt: at(23, 15),
      durationMinutes: 30,
      timezone,
      location: "",
      notes: "Company X",
    },
  ];
}
