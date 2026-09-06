import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { ApiResponseError } from "@/shared/api/client";
import { ownerQueryKey } from "@/shared/api/query-key";
import type { Job } from "@/shared/types/job";

import {
  deleteJob,
  fetchAiMatchStatus,
  fetchJobs,
  fetchJobStates,
  matchJobs,
  patchJobState,
  startAiMatch,
  upsertJobs,
} from "../api/client";
import type { JobStatePatch, JobStatePayload } from "../api/dto";
import { normalizeStoredJobs } from "../api/mappers";
import { keepStoredUserJobs, mergeJobs } from "../model/selectors";

const jobsQueryKey = ownerQueryKey(["jobs"] as const);

type JobsSnapshot = {
  jobs: Job[];
  states: Record<string, JobStatePayload>;
};

function mergeInitialJobs(serverJobs: Job[], initialJobs: Job[]) {
  return mergeJobs(serverJobs, initialJobs);
}

export function useJobs(initialJobs: Job[] = []) {
  const queryClient = useQueryClient();
  const controllerRef = useRef<AbortController | null>(null);
  const placeholder = useMemo<JobsSnapshot>(() => ({
    jobs: initialJobs,
    states: {},
  }), [initialJobs]);

  const query = useQuery<JobsSnapshot>({
    queryKey: jobsQueryKey,
    placeholderData: placeholder,
    queryFn: async ({ signal }) => {
      const [storedJobs, states] = await Promise.all([
        fetchJobs(signal),
        fetchJobStates(signal),
      ]);
      const normalizedJobs = normalizeStoredJobs(storedJobs.map((job) => job.data));
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
      const states = await fetchJobStates(signal);
      return {
        jobs: mergeInitialJobs(normalizeStoredJobs(stored.map((job) => job.data)), initialJobs),
        states: Object.fromEntries(states.map((state) => [state.jobId, state])),
      } satisfies JobsSnapshot;
    }),
    onMutate(jobs) {
      const previous = queryClient.getQueryData<JobsSnapshot>(jobsQueryKey);
      queryClient.setQueryData<JobsSnapshot>(jobsQueryKey, (current) => ({
        jobs,
        states: current?.states ?? {},
      }));
      return { previous };
    },
    onSuccess(snapshot) {
      queryClient.setQueryData<JobsSnapshot>(jobsQueryKey, snapshot);
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
      if (!state) throw new Error("Authoritative job state is not loaded");
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

  const states = query.data?.states ?? placeholder.states;
  const jobs = useMemo(
    () => (query.data?.jobs ?? placeholder.jobs).map((job) => {
      const state = states[job.id];
      if (!state) return job;
      return {
        ...job,
        archived: state.archived,
        archivedAt: state.archivedAt ?? undefined,
      };
    }),
    [placeholder.jobs, query.data?.jobs, states],
  );
  const savedJobIds = Object.values(states).filter((state) => state.saved).map((state) => state.jobId);
  const archivedJobIds = Object.values(states).filter((state) => state.archived).map((state) => state.jobId);
  const deletedJobIds = Object.values(states).filter((state) => state.dismissed).map((state) => state.jobId);

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
