import {
  BriefcaseBusiness,
  CalendarDays,
  Home,
  Mail,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { View } from "@/lib/app-route";

export type AppNavigationItem = {
  label: string;
  icon: LucideIcon;
  href: string;
  view?: View;
};

export const navItems: AppNavigationItem[] = [
  { label: "Dashboard", icon: Home, href: "#dashboard", view: "Dashboard" },
  { label: "Jobs", icon: BriefcaseBusiness, href: "#jobs", view: "Jobs" },
  { label: "Applications", icon: Mail, href: "#applications", view: "Applications" },
  { label: "Calendar", icon: CalendarDays, href: "#calendar", view: "Calendar" },
  { label: "AI Assistant", icon: Sparkles, href: "#assistant", view: "Assistant" },
];
