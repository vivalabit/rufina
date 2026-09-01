import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";

import type { JobSearchRunPayload, JobSourceConfigPayload } from "../api/dto";
import {
  createSearchConfig,
  fetchJobSearchRuns,
  fetchSearchConfigs,
  fetchSourceConfigs,
  runJobSearch,
  saveSourceConfig,
} from "../api/client";
import { parserSearchConfigFromApi } from "../api/mappers";
import {
  hasEquivalentServerSearchConfig,
  normalizeParserSearchConfigs,
} from "../browser-storage/migrations";
import {
  legacyParserSearchConfigsStorageKey,
  parserSearchConfigsStorageKey,
} from "../browser-storage/keys";
import { parserSearchFiltersFromForm } from "../model/form-mappers";
import type { ParserSearchConfig } from "../model/types";

const configsQueryKey = ["job-search", "configs"] as const;
const runsQueryKey = ["job-search", "runs"] as const;

type SearchConfigsSnapshot = {
  configs: ParserSearchConfig[];
  sourceConfigs: JobSourceConfigPayload[];
};

async function loadConfigs(signal: AbortSignal): Promise<SearchConfigsSnapshot> {
  window.localStorage.removeItem(legacyParserSearchConfigsStorageKey);
  const serverConfigs = await fetchSearchConfigs(signal);
  const rawLegacyConfigs = window.localStorage.getItem(parserSearchConfigsStorageKey);
  if (rawLegacyConfigs) {
    let legacyConfigs: ParserSearchConfig[] = [];
    try {
      const parsed = JSON.parse(rawLegacyConfigs) as unknown;
      legacyConfigs = Array.isArray(parsed)
        ? normalizeParserSearchConfigs(parsed as ParserSearchConfig[])
        : [];
    } catch {
      window.localStorage.removeItem(parserSearchConfigsStorageKey);
    }
    for (const legacyConfig of legacyConfigs) {
      if (hasEquivalentServerSearchConfig(legacyConfig, serverConfigs)) continue;
      serverConfigs.push(await createSearchConfig({
        name: legacyConfig.name,
        filters: parserSearchFiltersFromForm(legacyConfig.form),
      }, signal));
    }
    window.localStorage.removeItem(parserSearchConfigsStorageKey);
  }
  let sourceConfigs: JobSourceConfigPayload[] = [];
  try {
    sourceConfigs = await fetchSourceConfigs(signal);
  } catch {
    // Common configs remain useful while source-specific profiles are unavailable.
  }
  return {
    configs: serverConfigs.map(parserSearchConfigFromApi),
    sourceConfigs,
  };
}

export function useJobSearch() {
  const queryClient = useQueryClient();
  const controllersRef = useRef(new Set<AbortController>());
  const query = useQuery({
    queryKey: configsQueryKey,
    queryFn: ({ signal }) => loadConfigs(signal),
  });
  const runsQuery = useQuery({
    queryKey: runsQueryKey,
    queryFn: ({ signal }) => fetchJobSearchRuns(20, signal),
    enabled: false,
    initialData: [] as JobSearchRunPayload[],
  });

  useEffect(() => () => {
    for (const controller of controllersRef.current) controller.abort();
    controllersRef.current.clear();
  }, []);
  const withSignal = useCallback(async <T,>(operation: (signal: AbortSignal) => Promise<T>) => {
    const controller = new AbortController();
    controllersRef.current.add(controller);
    try {
      return await operation(controller.signal);
    } finally {
      controllersRef.current.delete(controller);
    }
  }, []);

  const sourceConfigMutation = useMutation({
    mutationFn: (input: { id?: string; data: Record<string, unknown> }) =>
      withSignal((signal) => saveSourceConfig(input, signal)),
    onMutate(input) {
      const previous = queryClient.getQueryData<SearchConfigsSnapshot>(configsQueryKey);
      if (input.id) {
        queryClient.setQueryData<SearchConfigsSnapshot>(configsQueryKey, (current) => ({
          configs: current?.configs ?? [],
          sourceConfigs: (current?.sourceConfigs ?? []).map((config) =>
            config.id === input.id ? { ...config, ...input.data } : config),
        }));
      }
      return { previous };
    },
    onSuccess(saved) {
      queryClient.setQueryData<SearchConfigsSnapshot>(configsQueryKey, (current) => ({
        configs: current?.configs ?? [],
        sourceConfigs: (current?.sourceConfigs ?? []).some((config) => config.id === saved.id)
          ? (current?.sourceConfigs ?? []).map((config) => config.id === saved.id ? saved : config)
          : [saved, ...(current?.sourceConfigs ?? [])],
      }));
    },
    onError(_error, _input, context) {
      if (context?.previous) queryClient.setQueryData(configsQueryKey, context.previous);
    },
  });

  const runMutation = useMutation({
    mutationFn: (input: Record<string, unknown>) => withSignal((signal) => runJobSearch(input, signal)),
    onSuccess(run) {
      queryClient.setQueryData<JobSearchRunPayload[]>(runsQueryKey, (current = []) => [
        run,
        ...current.filter((item) => item.id !== run.id),
      ]);
    },
  });

  const fetchRuns = useCallback(async () => {
    const runs = await withSignal((signal) => fetchJobSearchRuns(20, signal));
    queryClient.setQueryData(runsQueryKey, runs);
    return runs;
  }, [queryClient, withSignal]);

  return {
    configs: query.data?.configs ?? [],
    sourceConfigs: query.data?.sourceConfigs ?? [],
    runs: runsQuery.data,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error : null,
    mutationError: (sourceConfigMutation.error ?? runMutation.error) instanceof Error
      ? sourceConfigMutation.error ?? runMutation.error as Error
      : null,
    refetch: query.refetch,
    saveSourceConfig: sourceConfigMutation.mutateAsync,
    run: runMutation.mutateAsync,
    fetchRuns,
    isRunning: runMutation.isPending,
    cancel: () => {
      for (const controller of controllersRef.current) controller.abort();
      controllersRef.current.clear();
    },
  };
}
