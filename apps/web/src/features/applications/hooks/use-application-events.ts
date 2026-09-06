import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { ApiResponseError } from "@/shared/api/client";
import { ownerQueryKey } from "@/shared/api/query-key";
import type { ApplicationEvent } from "@/shared/types/application";

import {
  createApplicationEvent,
  deleteApplicationEvent,
  fetchApplicationEvents,
  patchApplicationEvent,
} from "../api/events-client";
import type { StoredApplicationEventPayload } from "../api/dto";
import { normalizeStoredApplicationEvents } from "../api/mappers";
import { sortApplicationEvents } from "../model/selectors";

const applicationEventsQueryKey = ownerQueryKey(["application-events"] as const);

type VersionedApplicationEvent = {
  event: ApplicationEvent;
  revision: number;
};

type ApplicationEventsSnapshot = {
  items: VersionedApplicationEvent[];
};

function normalizePayload(payload: StoredApplicationEventPayload) {
  const event = normalizeStoredApplicationEvents([payload.data])[0];
  return event ? { event, revision: payload.revision ?? 0 } : null;
}

async function loadSnapshot(signal: AbortSignal): Promise<ApplicationEventsSnapshot> {
  const payloads = await fetchApplicationEvents(signal);
  return {
    items: payloads
      .map(normalizePayload)
      .filter((item): item is VersionedApplicationEvent => item !== null),
  };
}

export function useApplicationEvents() {
  const queryClient = useQueryClient();
  const controllerRef = useRef<AbortController | null>(null);
  const cacheRevisionRef = useRef(0);
  const hydrationPromiseRef = useRef<Promise<ApplicationEventsSnapshot> | null>(null);
  const query = useQuery<ApplicationEventsSnapshot>({
    queryKey: applicationEventsQueryKey,
    queryFn: ({ signal }) => {
      const cacheRevision = cacheRevisionRef.current;
      const promise = loadSnapshot(signal).then((snapshot) => {
        if (cacheRevisionRef.current === cacheRevision) return snapshot;
        const current = queryClient.getQueryData<ApplicationEventsSnapshot>(applicationEventsQueryKey);
        if (!current) return snapshot;
        const revisions = new Map(snapshot.items.map((item) => [item.event.id, item.revision]));
        return {
          items: current.items.map((item) => ({
            ...item,
            revision: revisions.get(item.event.id) ?? item.revision,
          })),
        };
      });
      hydrationPromiseRef.current = promise;
      return promise;
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

  type UpsertVariables = { event: ApplicationEvent; existed: boolean };
  const upsertMutation = useMutation({
    scope: { id: "application-events" },
    mutationFn: ({ event, existed }: UpsertVariables) => withSignal(async (signal) => {
      await hydrationPromiseRef.current?.catch(() => undefined);
      const current = queryClient.getQueryData<ApplicationEventsSnapshot>(applicationEventsQueryKey);
      const existing = current?.items.find((item) => item.event.id === event.id);
      let payload: StoredApplicationEventPayload;
      if (!existed) {
        payload = await createApplicationEvent(event, signal);
      } else if (existing && existing.revision > 0) {
        payload = await patchApplicationEvent(event, existing.revision, signal);
      } else {
        throw new Error("Authoritative application event revision is not loaded");
      }
      const normalized = normalizePayload(payload);
      if (!normalized) throw new Error("Application event API returned an invalid payload");
      return normalized;
    }),
    onMutate({ event }: UpsertVariables) {
      cacheRevisionRef.current += 1;
      const previous = queryClient.getQueryData<ApplicationEventsSnapshot>(applicationEventsQueryKey);
      queryClient.setQueryData<ApplicationEventsSnapshot>(applicationEventsQueryKey, (current) => {
        const items = current?.items ?? [];
        const existing = items.some((item) => item.event.id === event.id);
        return {
          items: sortApplicationEvents(
            existing
              ? items.map((item) => item.event.id === event.id ? event : item.event)
              : [event, ...items.map((item) => item.event)],
          ).map((nextEvent) => ({
            event: nextEvent,
            revision: items.find((item) => item.event.id === nextEvent.id)?.revision ?? 0,
          })),
        };
      });
      return { previous };
    },
    onSuccess(saved) {
      queryClient.setQueryData<ApplicationEventsSnapshot>(applicationEventsQueryKey, (current) => ({
        items: (current?.items ?? []).map((item) => item.event.id === saved.event.id ? saved : item),
      }));
    },
    onError(error, _variables, context) {
      if (context?.previous) queryClient.setQueryData(applicationEventsQueryKey, context.previous);
      if (error instanceof ApiResponseError && error.status === 412) {
        void queryClient.invalidateQueries({ queryKey: applicationEventsQueryKey });
      }
    },
  });

  const removeMutation = useMutation({
    scope: { id: "application-events" },
    mutationFn: ({ eventId, revision }: { eventId: string; revision: number }) => withSignal(async (signal) => {
      await deleteApplicationEvent(eventId, revision, signal);
      return eventId;
    }),
    onMutate({ eventId }) {
      cacheRevisionRef.current += 1;
      const previous = queryClient.getQueryData<ApplicationEventsSnapshot>(applicationEventsQueryKey);
      queryClient.setQueryData<ApplicationEventsSnapshot>(applicationEventsQueryKey, (current) => ({
        items: (current?.items ?? []).filter((item) => item.event.id !== eventId),
      }));
      return { previous };
    },
    onSuccess(eventId) {
      queryClient.setQueryData<ApplicationEventsSnapshot>(applicationEventsQueryKey, (current) => ({
        items: (current?.items ?? []).filter((item) => item.event.id !== eventId),
      }));
    },
    onError(error, _variables, context) {
      if (context?.previous) queryClient.setQueryData(applicationEventsQueryKey, context.previous);
      if (error instanceof ApiResponseError && error.status === 412) {
        void queryClient.invalidateQueries({ queryKey: applicationEventsQueryKey });
      }
    },
  });

  const updateCached = useCallback((
    update: ApplicationEvent[] | ((current: ApplicationEvent[]) => ApplicationEvent[]),
  ) => {
    cacheRevisionRef.current += 1;
    queryClient.setQueryData<ApplicationEventsSnapshot>(applicationEventsQueryKey, (current) => {
      const events = current?.items.map((item) => item.event) ?? [];
      const next = sortApplicationEvents(typeof update === "function" ? update(events) : update);
      const revisions = new Map((current?.items ?? []).map((item) => [item.event.id, item.revision]));
      return {
        items: next.map((event) => ({ event, revision: revisions.get(event.id) ?? 0 })),
      };
    });
  }, [queryClient]);

  const events = useMemo(
    () => query.data?.items.map((item) => item.event) ?? [],
    [query.data?.items],
  );
  const upsert = useCallback((event: ApplicationEvent) => upsertMutation.mutateAsync({
    event,
    existed: Boolean(query.data?.items.some((item) => item.event.id === event.id)),
  }), [query.data?.items, upsertMutation]);
  const remove = useCallback((eventId: string) => {
    const current = queryClient.getQueryData<ApplicationEventsSnapshot>(applicationEventsQueryKey);
    const existing = current?.items.find((item) => item.event.id === eventId);
    if (!existing) {
      return Promise.reject(new Error("Authoritative application event revision is not loaded"));
    }
    return removeMutation.mutateAsync({ eventId, revision: existing.revision });
  }, [queryClient, removeMutation]);

  return {
    events,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error : null,
    refetch: query.refetch,
    upsert,
    remove,
    updateCached,
    removeForApplication: (applicationId: string) => updateCached((current) =>
      current.filter((event) => event.applicationId !== applicationId)),
    isMutating: upsertMutation.isPending || removeMutation.isPending,
    mutationError: (upsertMutation.error ?? removeMutation.error) instanceof Error
      ? upsertMutation.error ?? removeMutation.error as Error
      : null,
    cancel: () => controllerRef.current?.abort(),
  };
}
