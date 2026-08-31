import type { ApplicationEventType } from "@/shared/types/application";

export const calendarWeekdays = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

export const calendarEventTheme: Record<
  ApplicationEventType,
  { border: string; dot: string; badge: string }
> = {
  screening: {
    border:
      "border-[#fa5d00]/70 bg-[#fa5d00]/[0.055] hover:bg-[#fa5d00]/[0.10]",
    dot: "bg-[#fa5d00]",
    badge: "border-[#fa5d00]/55 bg-[#fa5d00]/10 text-accent",
  },
  interview: {
    border:
      "border-accent/75 bg-accent/[0.045] hover:bg-accent/[0.09]",
    dot: "bg-accent",
    badge: "border-accent/60 bg-accent/10 text-[#e95300]",
  },
  assessment: {
    border:
      "border-[#fa5d00]/75 bg-[#fa5d00]/[0.055] hover:bg-[#fa5d00]/[0.11]",
    dot: "bg-[#fa5d00]",
    badge: "border-[#fa5d00]/60 bg-[#fa5d00]/10 text-[#fa5d00]",
  },
  follow_up: {
    border: "border-border bg-[#fff8f1] hover:bg-[#fff3e8]",
    dot: "bg-[#4a4a47]",
    badge: "border-border bg-[#fff8f1] text-[#4a4a47]",
  },
  offer_deadline: {
    border:
      "border-success/65 bg-success/[0.045] hover:bg-success/[0.09]",
    dot: "bg-success",
    badge: "border-success/55 bg-success/10 text-success",
  },
};
