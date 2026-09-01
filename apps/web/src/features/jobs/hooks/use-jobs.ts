import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { ApiResponseError } from "@/lib/api-client";
import type { Job } from "@/shared/types/job";

import {
  deleteJob,
  fetchAiMatchStatus,
  fetchJobs,
  fetchJobStates,
  importLegacyJobStates,
  matchJobs,
  patchJobState,
  startAiMatch,
  upsertJobs,
} from "../api/client";
import type { JobStatePatch, JobStatePayload } from "../api/dto";
import {
  archivedJobIdsStorageKey,
  deletedJobIdsStorageKey,
  importedJobsStorageKey,
  jobsStorageMigrationKey,
  jobStateStorageMigrationKey,
  savedJobIdsStorageKey,
} from "../browser-storage/keys";
import { normalizeStoredJobIds, normalizeStoredJobs } from "../browser-storage/normalizers";
import { keepStoredUserJobs, mergeJobs } from "../model/selectors";

const jobsQueryKey = ["jobs"] as const;

type JobsSnapshot = {
  jobs: Job[];
  states: Record<string, JobStatePayload>;
};

function readIds(key: string) {
  try {
    const raw = window.localStorage.getItem(key);
    return normalizeStoredJobIds(raw ? JSON.parse(raw) : []);
  } catch {
    window.localStorage.removeItem(key);
    return [];
  }
}

function readLocalJobs() {
  try {
    const raw = window.localStorage.getItem(importedJobsStorageKey);
    return keepStoredUserJobs(normalizeStoredJobs(raw ? JSON.parse(raw) : []));
  } catch {
    window.localStorage.removeItem(importedJobsStorageKey);
    return [];
  }
}

function localStates() {
  const saved = new Set(readIds(savedJobIdsStorageKey));
  const archived = new Set(readIds(archivedJobIdsStorageKey));
  const dismissed = new Set(readIds(deletedJobIdsStorageKey));
  return Object.fromEntries(
    Array.from(new Set([...saved, ...archived, ...dismissed])).map((jobId) => [jobId, {
      jobId,
      saved: saved.has(jobId),
      archived: archived.has(jobId),
      dismissed: dismissed.has(jobId),
      savedAt: null,
      archivedAt: null,
      dismissedAt: null,
      updatedAt: "",
      revision: 0,
    } satisfies JobStatePayload]),
  );
}

function mergeInitialJobs(serverJobs: Job[], initialJobs: Job[]) {
  return mergeJobs(serverJobs, initialJobs);
}

export function useJobs(initialJobs: Job[] = []) {
  const queryClient = useQueryClient();
  const controllerRef = useRef<AbortController | null>(null);
  const localJobs = useMemo(() => readLocalJobs(), []);
  const localState = useMemo(() => localStates(), []);
  const placeholder = useMemo<JobsSnapshot>(() => ({
    jobs: mergeInitialJobs(localJobs, initialJobs),
    states: localState,
  }), [initialJobs, localJobs, localState]);

  const query = useQuery<JobsSnapshot>({
    queryKey: jobsQueryKey,
    placeholderData: placeholder,
    queryFn: async ({ signal }) => {
      let storedJobs = await fetchJobs(signal);
      const jobsSignature = JSON.stringify(localJobs.map((job) => job.id).sort());
      if (localJobs.length > 0 && window.localStorage.getItem(jobsStorageMigrationKey) !== jobsSignature) {
        storedJobs = await upsertJobs(localJobs, signal);
        window.localStorage.setItem(jobsStorageMigrationKey, jobsSignature);
      }
      const normalizedJobs = normalizeStoredJobs(storedJobs.map((job) => job.data));
      let states: JobStatePayload[] = Object.values(localState);
      try {
        const stateSignature = JSON.stringify(Object.keys(localState).sort());
        states = Object.keys(localState).length > 0
          && window.localStorage.getItem(jobStateStorageMigrationKey) !== stateSignature
          ? await importLegacyJobStates(Object.values(localState), signal)
          : await fetchJobStates(signal);
        if (Object.keys(localState).length > 0) {
          window.localStorage.setItem(jobStateStorageMigrationKey, stateSignature);
        }
      } catch {
        // Older/offline APIs still render the browser snapshot until state can be synchronized.
      }
      return {
        jobs: mergeInitialJobs(normalizedJobs, initialJobs),
        states: Object.fromEntries(states.map((state) => [state.jobId, state])),
      };
    },
  });

  useEffect(() => () => controllerRef.current?.abort(), []);
  const withSignal = useCallback(async <T,>(operation: (signal: AbortSignal) => Promise<T>) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      return await operation(controller.signal);
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }, []);

  const jobsMutation = useMutation({
    scope: { id: "jobs" },
    mutationFn: (jobs: Job[]) => withSignal(async (signal) => {
      const stored = await upsertJobs(keepStoredUserJobs(jobs), signal);
      return mergeInitialJobs(normalizeStoredJobs(stored.map((job) => job.data)), initialJobs);
    }),
    onMutate(jobs) {
      const previous = queryClient.getQueryData<JobsSnapshot>(jobsQueryKey);
      queryClient.setQueryData<JobsSnapshot>(jobsQueryKey, (current) => ({
        jobs,
        states: current?.states ?? {},
      }));
      return { previous };
    },
    onSuccess(jobs) {
      if (jobs.length === 0) return;
      queryClient.setQueryData<JobsSnapshot>(jobsQueryKey, (current) => ({
        jobs,
        states: current?.states ?? {},
      }));
    },
    onError(_error, _jobs, context) {
      if (context?.previous) queryClient.setQueryData(jobsQueryKey, context.previous);
    },
  });

  const stateMutation = useMutation({
    scope: { id: "job-state" },
    mutationFn: ({ jobId, patch }: { jobId: string; patch: JobStatePatch }) => withSignal(async (signal) => {
      const current = queryClient.getQueryData<JobsSnapshot>(jobsQueryKey);
      const state = current?.states[jobId];
      if (!state || state.revision < 1) {
        const imported = await importLegacyJobStates([{
          jobId,
          saved: patch.saved ?? state?.saved ?? false,
          archived: patch.archived ?? state?.archived ?? false,
          dismissed: patch.dismissed ?? state?.dismissed ?? false,
        }], signal);
        return imported.find((item) => item.jobId === jobId) ?? null;
      }
      return patchJobState(jobId, patch, state.revision, signal);
    }),
    onMutate({ jobId, patch }) {
      const previous = queryClient.getQueryData<JobsSnapshot>(jobsQueryKey);
      queryClient.setQueryData<JobsSnapshot>(jobsQueryKey, (current) => {
        const state = current?.states[jobId];
        return {
          jobs: current?.jobs ?? initialJobs,
          states: {
            ...current?.states,
            [jobId]: {
              jobId,
              saved: false,
              archived: false,
              dismissed: false,
              savedAt: null,
              archivedAt: null,
              dismissedAt: null,
              updatedAt: "",
              revision: 0,
              ...state,
              ...patch,
            },
          },
        };
      });
      return { previous };
    },
    onSuccess(state) {
      if (!state) return;
      queryClient.setQueryData<JobsSnapshot>(jobsQueryKey, (current) => ({
        jobs: current?.jobs ?? initialJobs,
        states: { ...current?.states, [state.jobId]: state },
      }));
    },
    onError(error, _variables, context) {
      if (context?.previous) queryClient.setQueryData(jobsQueryKey, context.previous);
      if (error instanceof ApiResponseError && error.status === 412) {
        void queryClient.invalidateQueries({ queryKey: jobsQueryKey });
      }
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (jobId: string) => withSignal((signal) => deleteJob(jobId, signal)),
    onMutate(jobId) {
      const previous = queryClient.getQueryData<JobsSnapshot>(jobsQueryKey);
      queryClient.setQueryData<JobsSnapshot>(jobsQueryKey, (current) => ({
        jobs: (current?.jobs ?? []).filter((job) => job.id !== jobId),
        states: {
          ...current?.states,
          [jobId]: {
            ...(current?.states[jobId] ?? {
              jobId, savedAt: null, archivedAt: null, dismissedAt: null, updatedAt: "", revision: 0,
            }),
            saved: false,
            archived: false,
            dismissed: true,
          },
        },
      }));
      return { previous };
    },
    onError(_error, _jobId, context) {
      if (context?.previous) queryClient.setQueryData(jobsQueryKey, context.previous);
    },
  });

  const updateCached = useCallback((update: Job[] | ((jobs: Job[]) => Job[])) => {
    queryClient.setQueryData<JobsSnapshot>(jobsQueryKey, (current) => ({
      jobs: typeof update === "function" ? update(current?.jobs ?? initialJobs) : update,
      states: current?.states ?? {},
    }));
  }, [initialJobs, queryClient]);

  const jobs = query.data?.jobs ?? placeholder.jobs;
  const states = query.data?.states ?? placeholder.states;
  const savedJobIds = Object.values(states).filter((state) => state.saved).map((state) => state.jobId);
  const archivedJobIds = Object.values(states).filter((state) => state.archived).map((state) => state.jobId);
  const deletedJobIds = Object.values(states).filter((state) => state.dismissed).map((state) => state.jobId);

  useEffect(() => {
    window.localStorage.setItem(importedJobsStorageKey, JSON.stringify(keepStoredUserJobs(jobs)));
    window.localStorage.setItem(savedJobIdsStorageKey, JSON.stringify(savedJobIds));
    window.localStorage.setItem(archivedJobIdsStorageKey, JSON.stringify(archivedJobIds));
    window.localStorage.setItem(deletedJobIdsStorageKey, JSON.stringify(deletedJobIds));
  }, [archivedJobIds, deletedJobIds, jobs, savedJobIds]);

  return {
    jobs,
    savedJobIds,
    archivedJobIds,
    deletedJobIds,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error : null,
    refetch: query.refetch,
    updateCached,
    saveJobs: jobsMutation.mutateAsync,
    patchState: (jobId: string, patch: JobStatePatch) => stateMutation.mutateAsync({ jobId, patch }),
    remove: deleteMutation.mutateAsync,
    startAiMatch: (jobsToMatch: Job[], force = false) =>
      withSignal((signal) => startAiMatch(jobsToMatch, force, signal)),
    matchNow: (jobsToMatch: Job[], force = false) =>
      withSignal((signal) => matchJobs(jobsToMatch, force, signal)),
    fetchAiMatchStatus: () => withSignal(fetchAiMatchStatus),
    cancel: () => controllerRef.current?.abort(),
  };
}
