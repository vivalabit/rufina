"use client";

import { useEffect, useState } from "react";

import { AppProviders } from "@/app/providers";
import { AppShell } from "@/components/app-shell";
import { AppSidebar } from "@/components/app-sidebar";
import type { AssistantLaunch } from "@/components/assistant-view";
import { AppWorkspaceRoot } from "@/components/app-workspace-root";
import { useActivityFeed } from "@/features/activity/hooks/use-activity-feed";
import { useApplicationEvents } from "@/features/applications/hooks/use-application-events";
import { useApplications } from "@/features/applications/hooks/use-applications";
import { useJobSearch } from "@/features/job-search/hooks/use-job-search";
import { useJobs } from "@/features/jobs/hooks/use-jobs";
import { demoJobs } from "@/features/jobs/model/demo-jobs";
import { useProfile } from "@/features/profile/hooks/use-profile";
import { useAppSettings } from "@/features/settings/hooks/use-app-settings";
import {
  UiSettingsProvider,
  useUiSettings,
} from "@/features/settings/components/ui-settings-provider";
import { createClientId } from "@/lib/client-id";
import {
  getHashForView,
  getRouteFromHash,
  type AppRoute,
  type View,
} from "@/lib/app-route";

function HomePageContent() {
  const demoMode = process.env.NEXT_PUBLIC_DEMO_MODE === "1";
  const initialJobs = demoMode ? demoJobs : [];
  const [route, setRoute] = useState<AppRoute>({ view: "Dashboard" });
  const [assistantLaunch, setAssistantLaunch] = useState<AssistantLaunch | null>(null);
  const jobsState = useJobs(initialJobs);
  const jobSearchState = useJobSearch();
  const applicationState = useApplications();
  const applicationEventState = useApplicationEvents();
  const profileState = useProfile();
  const appSettingsState = useAppSettings();
  const activityFeed = useActivityFeed();
  const { settings: uiSettings } = useUiSettings();

  useEffect(() => {
    const syncRouteFromUrl = () => setRoute(getRouteFromHash(window.location.hash));
    syncRouteFromUrl();
    window.addEventListener("hashchange", syncRouteFromUrl);
    return () => window.removeEventListener("hashchange", syncRouteFromUrl);
  }, []);

  function navigate(view: View, selectedEntityId?: string) {
    const hash = getHashForView(view, selectedEntityId);
    window.history.replaceState(null, "", hash);
    setRoute(getRouteFromHash(hash));
  }

  function openAssistant(
    prompt = "",
    contextKind: AssistantLaunch["contextKind"] = "profile",
    contextId = "",
    autoSubmit = false,
  ) {
    setAssistantLaunch(prompt ? {
      id: createClientId("assistant-launch"),
      prompt,
      contextKind,
      contextId,
      autoSubmit,
    } : null);
    navigate("Assistant");
  }

  return (
    <AppShell
      sidebar={(
        <AppSidebar
          activeView={route.view}
          onChangeView={navigate}
          profile={profileState.profile}
          showLogs={uiSettings.showLogs}
        />
      )}
    >
      <AppWorkspaceRoot
        route={route}
        demoMode={demoMode}
        jobsState={jobsState}
        jobSearchState={jobSearchState}
        applicationState={applicationState}
        applicationEventState={applicationEventState}
        profileState={profileState}
        appSettingsState={appSettingsState}
        activityFeed={activityFeed}
        assistantLaunch={assistantLaunch}
        onAssistantLaunchHandled={() => setAssistantLaunch(null)}
        onNavigate={navigate}
        onOpenAssistant={openAssistant}
      />
    </AppShell>
  );
}

export default function HomePage() {
  return (
    <AppProviders>
      <UiSettingsProvider>
        <HomePageContent />
      </UiSettingsProvider>
    </AppProviders>
  );
}
