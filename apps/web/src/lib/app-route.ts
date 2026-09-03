export type View =
  | "Dashboard"
  | "Jobs"
  | "ApplicationWorkspace"
  | "Applications"
  | "Calendar"
  | "Assistant"
  | "Profile"
  | "Settings"
  | "Logs";

export type AppRoute = {
  view: View;
  jobId?: string;
  applicationId?: string;
};

const jobsHash = "#jobs";
const jobsPrefix = `${jobsHash}/`;
const applicationsHash = "#applications";
const applicationsPrefix = `${applicationsHash}/`;
const applicationWorkspaceHash = "#application-workspace";
const applicationWorkspacePrefix = `${applicationWorkspaceHash}/`;

const viewByHash: Record<string, View> = {
  "#profile": "Profile",
  "#settings": "Settings",
  "#logs": "Logs",
  [applicationsHash]: "Applications",
  [applicationWorkspaceHash]: "ApplicationWorkspace",
  "#calendar": "Calendar",
  "#assistant": "Assistant",
  [jobsHash]: "Jobs",
};

const hashByView: Record<Exclude<View, "ApplicationWorkspace">, string> = {
  Dashboard: "#dashboard",
  Jobs: jobsHash,
  Applications: applicationsHash,
  Calendar: "#calendar",
  Assistant: "#assistant",
  Profile: "#profile",
  Settings: "#settings",
  Logs: "#logs",
};

export function getRouteFromHash(hash: string): AppRoute {
  const entityRoutes: Array<{
    prefix: string;
    view: View;
    key: "jobId" | "applicationId";
  }> = [
    { prefix: jobsPrefix, view: "Jobs", key: "jobId" },
    { prefix: applicationsPrefix, view: "Applications", key: "applicationId" },
    {
      prefix: applicationWorkspacePrefix,
      view: "ApplicationWorkspace",
      key: "applicationId",
    },
  ];

  for (const route of entityRoutes) {
    if (!hash.startsWith(route.prefix)) continue;
    const encodedId = hash.slice(route.prefix.length);
    if (!encodedId) return { view: route.view };

    let id = encodedId;
    try {
      id = decodeURIComponent(encodedId);
    } catch {
      // Keep malformed legacy hashes navigable instead of dropping the selection.
    }
    return { view: route.view, [route.key]: id };
  }

  return { view: viewByHash[hash] ?? "Dashboard" };
}

export function getHashForView(view: View, selectedEntityId?: string) {
  if (view === "Jobs") {
    return selectedEntityId
      ? `${jobsPrefix}${encodeURIComponent(selectedEntityId)}`
      : jobsHash;
  }

  if (view === "Applications") {
    return selectedEntityId
      ? `${applicationsPrefix}${encodeURIComponent(selectedEntityId)}`
      : applicationsHash;
  }

  if (view === "ApplicationWorkspace") {
    return selectedEntityId
      ? `${applicationWorkspacePrefix}${encodeURIComponent(selectedEntityId)}`
      : applicationWorkspaceHash;
  }

  return hashByView[view];
}

export function findWorkspaceApplication<T extends { id: string }>(
  applications: readonly T[],
  applicationId: string | null | undefined,
) {
  if (!applicationId) return null;
  return (
    applications.find((application) => application.id === applicationId) ?? null
  );
}
