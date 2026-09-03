import { apiClient } from "@/shared/api/client";

import type { AppSettings, AppSettingsUpdate } from "../model/types";

export async function fetchAppSettings(signal?: AbortSignal) {
  return (await apiClient.json<AppSettings>({
    path: "/settings",
    cache: "no-store",
    signal,
    errorMessage: "Settings could not be loaded",
  })).data;
}

export async function putAppSettings(
  update: AppSettingsUpdate,
  signal?: AbortSignal,
) {
  return (await apiClient.json<AppSettings>({
    path: "/settings",
    method: "PUT",
    json: update,
    signal,
    errorMessage: "Settings could not be saved",
  })).data;
}
