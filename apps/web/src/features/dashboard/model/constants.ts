import type { ApplicationStatus } from "@/shared/types/application";

export const dashboardActiveApplicationStatuses: ApplicationStatus[] = [
  "applied",
  "interview",
  "assessment",
];

export const dashboardApplicationStatusColors: Record<
  ApplicationStatus,
  string
> = {
  draft: "#c0bbb6",
  applied: "#2563eb",
  interview: "#0891b2",
  assessment: "#7c3aed",
  offer: "#16a34a",
  rejected: "#dc2626",
};
