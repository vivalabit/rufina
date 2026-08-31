"use client";

import { FileText, Github, Settings } from "lucide-react";

import { CriticalNotificationsBell } from "@/components/critical-notifications-bell";
import { navItems } from "@/features/app-shell/model/navigation";
import { defaultCandidateProfile } from "@/features/profile/model/defaults";
import {
  displayProfileFirstName,
  displayProfileValue,
} from "@/features/profile/formatting";
import type { View } from "@/lib/app-route";
import { cn } from "@/lib/utils";
import { apiBaseUrl } from "@/shared/api/config";
import type { CandidateProfile } from "@/shared/types/profile";

type AppSidebarProps = {
  activeView: View;
  onChangeView: (view: View) => void;
  profile: CandidateProfile;
  showLogs: boolean;
};

export function AppSidebar({
  activeView,
  onChangeView,
  profile,
  showLogs,
}: AppSidebarProps) {
  const visibleNavItems = showLogs
    ? [
        ...navItems,
        {
          label: "Logs",
          icon: FileText,
          href: "#logs",
          view: "Logs" as const,
        },
      ]
    : navItems;

  return (
    <header className="app-sidebar z-40 flex shrink-0 flex-wrap items-center gap-2 bg-background/90 px-3 py-2.5 backdrop-blur-xl sm:gap-3 sm:px-4 xl:flex-nowrap xl:px-5 2xl:gap-5 2xl:px-7 2xl:py-3.5">
      <div className="app-sidebar-brand flex shrink-0 items-center gap-2 pr-1 2xl:gap-2.5 2xl:pr-3">
        <img
          src="/brand/rufina-mark.png"
          alt=""
          className="app-sidebar-mark h-10 w-10 object-contain 2xl:h-11 2xl:w-11"
          aria-hidden="true"
        />
      </div>

      <nav className="app-sidebar-nav order-last flex w-full items-center gap-1 overflow-x-auto pb-0.5 xl:order-none xl:w-auto xl:min-w-0 xl:flex-1 2xl:gap-1.5">
        {visibleNavItems.map((item) => (
          <a
            href={item.href}
            key={item.label}
            onClick={() => {
              if (item.view) {
                onChangeView(item.view);
              }
            }}
            className={cn(
              "app-sidebar-nav-item group relative flex h-9 shrink-0 items-center gap-2 px-3 text-left text-[12px] font-semibold transition after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:origin-center after:scale-x-0 after:bg-accent after:transition-transform 2xl:h-10 2xl:px-3.5 2xl:text-[13px] 2xl:after:inset-x-3.5",
              item.view === activeView ||
                (activeView === "ApplicationWorkspace" &&
                  item.view === "Applications")
                ? "text-accent after:scale-x-100"
                : item.view
                  ? "text-[#4a4a47] hover:text-foreground"
                  : "cursor-default text-muted opacity-65",
            )}
          >
            <item.icon className="h-4 w-4 2xl:h-[18px] 2xl:w-[18px]" />
            <span>{item.label}</span>
          </a>
        ))}
      </nav>

      <div className="app-sidebar-footer ml-auto flex shrink-0 items-center gap-1.5">
        <CriticalNotificationsBell apiBaseUrl={apiBaseUrl} />
        <a
          href="#profile"
          onClick={() => onChangeView("Profile")}
          className={cn(
            "app-sidebar-profile flex h-10 items-center gap-2 rounded-md border border-transparent bg-white px-1.5 pr-2.5 text-left shadow-[0_4px_16px_rgba(227,214,197,0.55)] transition hover:border-[#e3d6c5]",
            activeView === "Profile" && "border-accent/45",
          )}
        >
          <img
            src={profile.avatar_url || defaultCandidateProfile.avatar_url}
            alt=""
            className="h-8 w-8 shrink-0 rounded-full object-cover 2xl:h-8 2xl:w-8"
            aria-hidden="true"
          />
          <div className="hidden min-w-0 flex-1 2xl:block">
            <p className="max-w-[110px] truncate text-xs font-semibold leading-tight text-foreground">
              {displayProfileFirstName(profile.name, "Set up profile")}
            </p>
            <p className="max-w-[110px] truncate text-[10px] leading-tight text-muted">
              {displayProfileValue(profile.current_role, "Add your role")}
            </p>
          </div>
        </a>
        <a
          href="#settings"
          aria-label="Settings"
          title="Settings"
          onClick={() => onChangeView("Settings")}
          className={cn(
            "app-sidebar-settings grid h-10 w-10 place-items-center rounded-md border border-transparent text-muted transition hover:border-[#e3d6c5] hover:bg-white hover:text-foreground",
            activeView === "Settings" &&
              "border-accent/45 bg-white text-accent",
          )}
        >
          <Settings className="h-[18px] w-[18px]" />
        </a>
        <a
          href="https://github.com/vivalabit/rufina"
          target="_blank"
          rel="noreferrer"
          aria-label="Source code"
          title="Source code"
          className="app-sidebar-source hidden h-10 w-10 place-items-center rounded-md border border-transparent text-muted transition hover:border-[#e3d6c5] hover:bg-white hover:text-foreground sm:grid"
        >
          <Github className="h-[18px] w-[18px]" />
        </a>
      </div>
    </header>
  );
}
