import { apiClient } from "@/shared/api/client";
import type { ApplicationEvent } from "@/shared/types/application";

import type { StoredApplicationEventPayload } from "./dto";
import { applicationEventToApiPayload } from "./mappers";

export async function fetchApplicationEvents(signal?: AbortSignal) {
  return (await apiClient.json<StoredApplicationEventPayload[]>({
    path: "/applications/events",
    cache: "no-store",
    signal,
    errorMessage: "Application events could not be loaded",
  })).data;
}

export async function createApplicationEvent(
  event: ApplicationEvent,
  signal?: AbortSignal,
) {
  return (await apiClient.json<StoredApplicationEventPayload>({
    path: "/applications/events",
    method: "POST",
    json: applicationEventToApiPayload(event),
    signal,
    errorMessage: "Application event could not be created",
  })).data;
}

export async function patchApplicationEvent(
  event: ApplicationEvent,
  revision: number,
  signal?: AbortSignal,
) {
  return (await apiClient.json<StoredApplicationEventPayload>({
    path: `/applications/events/${encodeURIComponent(event.id)}`,
    method: "PATCH",
    ifMatch: revision,
    json: { ...applicationEventToApiPayload(event), revision },
    signal,
    errorMessage: "Application event could not be saved",
  })).data;
}

export async function deleteApplicationEvent(
  eventId: string,
  revision: number | null,
  signal?: AbortSignal,
) {
  await apiClient.empty({
    path: `/applications/events/${encodeURIComponent(eventId)}`,
    method: "DELETE",
    ifMatch: revision,
    signal,
    errorMessage: "Application event could not be deleted",
  });
}
