import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { ApiResponseError } from "@/shared/api/client";
import { ownerQueryKey } from "@/shared/api/query-key";
import type { ApplicationDocument, TrackedApplication } from "@/shared/types/application";

import {
  createApplication,
  deleteApplication,
  deleteApplicationAttachment,
  fetchApplicationDocuments,
  fetchApplicationAnalysis,
  fetchApplications,
  patchApplication,
  uploadApplicationAttachment,
} from "../api/client";
import type { StoredApplicationPayload } from "../api/dto";
import { normalizeStoredApplications } from "../api/mappers";

const applicationsQueryKey = ownerQueryKey(["applications"] as const);

type VersionedApplication = {
  application: TrackedApplication;
  revision: number;
};

type ApplicationsSnapshot = {
  items: VersionedApplication[];
};

function normalizePayload(payload: StoredApplicationPayload) {
  const application = normalizeStoredApplications([payload.data])[0];
  return application ? { application, revision: payload.revision ?? 0 } : null;
}

async function loadApplicationsSnapshot(signal: AbortSignal): Promise<ApplicationsSnapshot> {
  const payloads = await fetchApplications(signal);
  const items = (await Promise.all(payloads.map(async (payload) => {
    const normalized = normalizePayload(payload);
    if (!normalized) return null;
    let documents: ApplicationDocument[] = [];
    try {
      documents = [
        ...await fetchApplicationDocuments(normalized.application.id, signal),
        ...documents,
      ];
    } catch {
      // Application text remains usable if document metadata is temporarily unavailable.
    }
    return {
      ...normalized,
      application: { ...normalized.application, documents },
    };
  }))).filter((item): item is VersionedApplication => item !== null);
  return { items };
}

export function useApplications() {
  const queryClient = useQueryClient();
  const controllerRef = useRef<AbortController | null>(null);
  const cacheRevisionRef = useRef(0);
  const hydrationPromiseRef = useRef<Promise<ApplicationsSnapshot> | null>(null);
  const query = useQuery<ApplicationsSnapshot>({
    queryKey: applicationsQueryKey,
    queryFn: ({ signal }) => {
      const cacheRevision = cacheRevisionRef.current;
      const promise = loadApplicationsSnapshot(signal).then((snapshot) => {
        if (cacheRevisionRef.current === cacheRevision) return snapshot;
        const current = queryClient.getQueryData<ApplicationsSnapshot>(applicationsQueryKey);
        if (!current) return snapshot;
        const serverRevisions = new Map(
          snapshot.items.map((item) => [item.application.id, item.revision]),
        );
        return {
          items: current.items.map((item) => ({
            ...item,
            revision: serverRevisions.get(item.application.id) ?? item.revision,
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

  type UpsertVariables = {
    application: TrackedApplication;
    existed: boolean;
  };

  const upsertMutation = useMutation({
    scope: { id: "applications" },
    mutationFn: ({ application, existed }: UpsertVariables) => withSignal(async (signal) => {
      await hydrationPromiseRef.current?.catch(() => undefined);
      const current = queryClient.getQueryData<ApplicationsSnapshot>(applicationsQueryKey);
      const existing = current?.items.find((item) => item.application.id === application.id);
      let payload: StoredApplicationPayload;
      if (!existed) {
        payload = await createApplication(application, signal);
      } else if (existing && existing.revision > 0) {
        payload = await patchApplication(application, existing.revision, signal);
      } else {
        throw new Error("Authoritative application revision is not loaded");
      }
      const normalized = normalizePayload(payload);
      if (!normalized) throw new Error("Application API returned an invalid payload");
      return {
        ...normalized,
        application: { ...normalized.application, documents: application.documents },
      };
    }),
    onMutate({ application }: UpsertVariables) {
      cacheRevisionRef.current += 1;
      const previous = queryClient.getQueryData<ApplicationsSnapshot>(applicationsQueryKey);
      queryClient.setQueryData<ApplicationsSnapshot>(applicationsQueryKey, (current) => {
        const items = current?.items ?? [];
        const existing = items.find((item) => item.application.id === application.id);
        return {
          items: existing
            ? items.map((item) => item.application.id === application.id
              ? { ...item, application }
              : item)
            : [{ application, revision: 0 }, ...items],
        };
      });
      return { previous };
    },
    onSuccess(saved) {
      queryClient.setQueryData<ApplicationsSnapshot>(applicationsQueryKey, (current) => ({
        items: (current?.items ?? []).map((item) =>
          item.application.id === saved.application.id ? saved : item),
      }));
    },
    onError(error, _variables, context) {
      if (context?.previous) queryClient.setQueryData(applicationsQueryKey, context.previous);
      if (error instanceof ApiResponseError && error.status === 412) {
        void queryClient.invalidateQueries({ queryKey: applicationsQueryKey });
      }
    },
  });

  const removeMutation = useMutation({
    scope: { id: "applications" },
    mutationFn: ({ applicationId, revision }: { applicationId: string; revision: number }) => withSignal(async (signal) => {
      await deleteApplication(applicationId, revision, signal);
      return applicationId;
    }),
    onMutate({ applicationId }) {
      cacheRevisionRef.current += 1;
      const previous = queryClient.getQueryData<ApplicationsSnapshot>(applicationsQueryKey);
      queryClient.setQueryData<ApplicationsSnapshot>(applicationsQueryKey, (current) => ({
        items: (current?.items ?? []).filter((item) => item.application.id !== applicationId),
      }));
      return { previous };
    },
    onSuccess(applicationId) {
      queryClient.setQueryData<ApplicationsSnapshot>(applicationsQueryKey, (current) => ({
        items: (current?.items ?? []).filter(
          (item) => item.application.id !== applicationId,
        ),
      }));
    },
    onError(error, _variables, context) {
      if (context?.previous) queryClient.setQueryData(applicationsQueryKey, context.previous);
      if (error instanceof ApiResponseError && error.status === 412) {
        void queryClient.invalidateQueries({ queryKey: applicationsQueryKey });
      }
    },
  });

  const updateCached = useCallback((
    update: TrackedApplication[] | ((current: TrackedApplication[]) => TrackedApplication[]),
  ) => {
    cacheRevisionRef.current += 1;
    queryClient.setQueryData<ApplicationsSnapshot>(applicationsQueryKey, (current) => {
      const applications = current?.items.map((item) => item.application) ?? [];
      const next = typeof update === "function" ? update(applications) : update;
      const revisions = new Map((current?.items ?? []).map((item) => [item.application.id, item.revision]));
      return {
        items: next.map((application) => ({
          application,
          revision: revisions.get(application.id) ?? 0,
        })),
      };
    });
  }, [queryClient]);

  const refreshAnalysis = useCallback((applicationId: string) => withSignal(async (signal) => {
    const payload = await fetchApplicationAnalysis(applicationId, signal);
    const normalized = normalizePayload(payload);
    if (!normalized || normalized.application.id !== applicationId) {
      throw new Error("Authoritative application analysis returned an invalid payload");
    }
    const current = queryClient.getQueryData<ApplicationsSnapshot>(applicationsQueryKey);
    const existing = current?.items.find((item) => item.application.id === applicationId);
    const saved = {
      ...normalized,
      application: {
        ...normalized.application,
        documents: existing?.application.documents ?? normalized.application.documents,
      },
    };
    queryClient.setQueryData<ApplicationsSnapshot>(applicationsQueryKey, (snapshot) => ({
      items: (snapshot?.items ?? []).map((item) =>
        item.application.id === applicationId ? saved : item),
    }));
    return saved.application;
  }), [queryClient, withSignal]);

  const applications = useMemo(
    () => query.data?.items.map((item) => item.application) ?? [],
    [query.data?.items],
  );

  const upsert = useCallback((application: TrackedApplication) => {
    return upsertMutation.mutateAsync({
      application,
      existed: Boolean(query.data?.items.some((item) => item.application.id === application.id)),
    });
  }, [query.data?.items, upsertMutation]);
  const remove = useCallback((applicationId: string) => {
    const current = queryClient.getQueryData<ApplicationsSnapshot>(applicationsQueryKey);
    const existing = current?.items.find((item) => item.application.id === applicationId);
    if (!existing) {
      return Promise.reject(new Error("Authoritative application revision is not loaded"));
    }
    return removeMutation.mutateAsync({ applicationId, revision: existing.revision });
  }, [queryClient, removeMutation]);

  return {
    applications,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error : null,
    refetch: query.refetch,
    upsert,
    remove,
    isMutating: upsertMutation.isPending || removeMutation.isPending,
    mutationError: (upsertMutation.error ?? removeMutation.error) instanceof Error
      ? upsertMutation.error ?? removeMutation.error as Error
      : null,
    cancel: () => controllerRef.current?.abort(),
    updateCached,
    uploadAttachment: (applicationId: string, file: Blob, metadata: { fileName: string; title: string }) =>
      withSignal((signal) => uploadApplicationAttachment(applicationId, file, metadata, signal)),
    deleteAttachment: (applicationId: string, document: ApplicationDocument) =>
      withSignal((signal) => deleteApplicationAttachment(applicationId, document, signal)),
    refreshAnalysis,
  };
}
