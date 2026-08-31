import type { ApplicationEventType } from "@/shared/types/application";

export type CalendarMode = "month" | "week" | "agenda";

export type CalendarEventFilter = ApplicationEventType | "all";
