import { requestJson } from "@/lib/api-client";
import { apiBaseUrl } from "@/shared/api/config";
import type { ApplicationEvent } from "@/shared/types/application";

import type { StoredApplicationEventPayload } from "./dto";
import { applicationEventToApiPayload } from "./mappers";

export async function fetchApplicationEvents(signal?: AbortSignal) {
  return (await requestJson<StoredApplicationEventPayload[]>(
    `${apiBaseUrl}/applications/events`,
    { cache: "no-store", signal },
    { errorMessage: "Application events could not be loaded" },
  )).data;
}

export async function importLegacyApplicationEvents(
  events: ApplicationEvent[],
  signal?: AbortSignal,
) {
  return (await requestJson<StoredApplicationEventPayload[]>(
    `${apiBaseUrl}/applications/events`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events: events.map(applicationEventToApiPayload) }),
      signal,
    },
    { errorMessage: "Legacy application events could not be imported" },
  )).data;
}

export async function createApplicationEvent(
  event: ApplicationEvent,
  signal?: AbortSignal,
) {
  return (await requestJson<StoredApplicationEventPayload>(
    `${apiBaseUrl}/applications/events`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(applicationEventToApiPayload(event)),
      signal,
    },
    { errorMessage: "Application event could not be created" },
  )).data;
}

export async function patchApplicationEvent(
  event: ApplicationEvent,
  revision: number,
  signal?: AbortSignal,
) {
  return (await requestJson<StoredApplicationEventPayload>(
    `${apiBaseUrl}/applications/events/${encodeURIComponent(event.id)}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "If-Match": `"${revision}"`,
      },
      body: JSON.stringify({ ...applicationEventToApiPayload(event), revision }),
      signal,
    },
    { errorMessage: "Application event could not be saved" },
  )).data;
}

export async function deleteApplicationEvent(
  eventId: string,
  revision: number | null,
  signal?: AbortSignal,
) {
  await requestJson<null>(
    `${apiBaseUrl}/applications/events/${encodeURIComponent(eventId)}`,
    {
      method: "DELETE",
      headers: revision === null ? undefined : { "If-Match": `"${revision}"` },
      signal,
    },
    { errorMessage: "Application event could not be deleted" },
  );
}
