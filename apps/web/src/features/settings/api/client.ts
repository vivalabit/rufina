import { requestJson } from "@/lib/api-client";
import { apiBaseUrl } from "@/shared/api/config";

import type { AppSettings, AppSettingsUpdate } from "../model/types";

export async function fetchAppSettings(signal?: AbortSignal) {
  return (await requestJson<AppSettings>(`${apiBaseUrl}/settings`, {
    cache: "no-store",
    signal,
  }, { errorMessage: "Settings could not be loaded" })).data;
}

export async function putAppSettings(
  update: AppSettingsUpdate,
  signal?: AbortSignal,
) {
  return (await requestJson<AppSettings>(`${apiBaseUrl}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
    signal,
  }, { errorMessage: "Settings could not be saved" })).data;
}
