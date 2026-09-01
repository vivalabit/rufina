import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { fetchAppSettings, putAppSettings } from "../api/client";
import { defaultAppSettings } from "../model/defaults";
import type { AppSettings, AppSettingsUpdate } from "../model/types";

const appSettingsQueryKey = ["app-settings"] as const;

type MutationStatus = "idle" | "loading" | "ready" | "error";

function statusForMutation({
  isPending,
  isError,
  isSuccess,
}: {
  isPending: boolean;
  isError: boolean;
  isSuccess: boolean;
}): MutationStatus {
  if (isPending) return "loading";
  if (isError) return "error";
  if (isSuccess) return "ready";
  return "idle";
}

function useSettingsMutation() {
  const queryClient = useQueryClient();
  const controllerRef = useRef<AbortController | null>(null);
  const mutation = useMutation({
    mutationFn: async (update: AppSettingsUpdate) => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      try {
        return await putAppSettings(update, controller.signal);
      } finally {
        if (controllerRef.current === controller) controllerRef.current = null;
      }
    },
    onSuccess(settings) {
      queryClient.setQueryData(appSettingsQueryKey, settings);
    },
  });

  useEffect(() => () => controllerRef.current?.abort(), []);

  return {
    save: mutation.mutateAsync,
    cancel: () => controllerRef.current?.abort(),
    reset: mutation.reset,
    status: statusForMutation(mutation),
    error: mutation.error instanceof Error ? mutation.error : null,
    data: mutation.data,
  };
}

export function useAppSettings() {
  const query = useQuery({
    queryKey: appSettingsQueryKey,
    queryFn: ({ signal }) => fetchAppSettings(signal),
  });
  const connection = useSettingsMutation();
  const ai = useSettingsMutation();

  return {
    settings: {
      ...defaultAppSettings,
      ...(query.data ?? {} as Partial<AppSettings>),
    },
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error : null,
    refetch: query.refetch,
    connection,
    ai,
  };
}
