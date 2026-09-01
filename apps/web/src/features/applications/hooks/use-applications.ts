import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { ApiResponseError } from "@/lib/api-client";
import { completedBrowserStorageMigrationValue } from "@/shared/browser-storage/constants";
import type { ApplicationDocument, TrackedApplication } from "@/shared/types/application";

import {
  createApplication,
  deleteApplication,
  deleteApplicationAttachment,
  fetchApplicationDocuments,
  fetchApplications,
  importLegacyApplications,
  patchApplication,
  uploadApplicationAttachment,
} from "../api/client";
import type { StoredApplicationPayload } from "../api/dto";
import {
  applicationFileStorageMigrationKey,
  applicationsStorageMigrationKey,
  applicationsStorageKey,
} from "../browser-storage/keys";
import {
  extractLegacyApplicationDocuments,
  migrateLegacyApplicationDocuments,
} from "../browser-storage/migrations";
import {
  normalizeStoredApplications,
  removeLegacyDemoApplications,
} from "../browser-storage/normalizers";
import { applicationPayloadForStorage } from "../browser-storage/serialization";

const applicationsQueryKey = ["applications"] as const;

type VersionedApplication = {
  application: TrackedApplication;
  revision: number;
};

type ApplicationsSnapshot = {
  items: VersionedApplication[];
  warnings: string[];
};

function normalizePayload(payload: StoredApplicationPayload) {
  const application = normalizeStoredApplications([payload.data])[0];
  return application ? { application, revision: payload.revision ?? 0 } : null;
}

function readLocalApplications() {
  let parsedLocal: unknown = [];
  try {
    const raw = window.localStorage.getItem(applicationsStorageKey);
    parsedLocal = raw ? JSON.parse(raw) as unknown : [];
  } catch {
    window.localStorage.removeItem(applicationsStorageKey);
  }
  return {
    applications: removeLegacyDemoApplications(normalizeStoredApplications(parsedLocal)),
    legacyDocuments: extractLegacyApplicationDocuments(parsedLocal),
  };
}

function localApplicationsSnapshot(): ApplicationsSnapshot {
  const { applications } = readLocalApplications();
  return {
    items: applications.map((application) => ({ application, revision: 0 })),
    warnings: [],
  };
}

async function loadApplicationsSnapshot(signal: AbortSignal): Promise<ApplicationsSnapshot> {
  const { applications: localApplications, legacyDocuments } = readLocalApplications();
  const localSignature = JSON.stringify(
    localApplications.map((application) => application.id).sort(),
  );
  const shouldImportLocal = localApplications.length > 0
    && window.localStorage.getItem(applicationsStorageMigrationKey) !== localSignature;
  const payloads = shouldImportLocal
    ? await importLegacyApplications(localApplications, signal)
    : await fetchApplications(signal);
  if (shouldImportLocal) {
    window.localStorage.setItem(applicationsStorageMigrationKey, localSignature);
  }
  const warnings: string[] = [];
  let migratedDocuments = new Map<string, ApplicationDocument[]>();
  if (legacyDocuments.size > 0) {
    const migration = await migrateLegacyApplicationDocuments(legacyDocuments, {
      uploadAttachment: (applicationId, file, metadata) =>
        uploadApplicationAttachment(applicationId, file, metadata, signal),
      isPermanentUploadError: (error) =>
        error instanceof ApiResponseError && [400, 413, 415, 422].includes(error.status),
    });
    migratedDocuments = migration.documents;
    warnings.push(...migration.warnings);
  }
  const items = (await Promise.all(payloads.map(async (payload) => {
    const normalized = normalizePayload(payload);
    if (!normalized) return null;
    let documents = migratedDocuments.get(normalized.application.id) ?? [];
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

  window.localStorage.setItem(
    applicationFileStorageMigrationKey,
    completedBrowserStorageMigrationValue,
  );
  return { items, warnings };
}

export function useApplications() {
  const queryClient = useQueryClient();
  const controllerRef = useRef<AbortController | null>(null);
  const cacheRevisionRef = useRef(0);
  const hydrationPromiseRef = useRef<Promise<ApplicationsSnapshot> | null>(null);
  const query = useQuery<ApplicationsSnapshot>({
    queryKey: applicationsQueryKey,
    placeholderData: localApplicationsSnapshot(),
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
          warnings: snapshot.warnings,
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
        const applications = (current?.items ?? [])
          .map((item) => item.application)
          .filter((item) => item.id !== application.id);
        const imported = await importLegacyApplications([application, ...applications], signal);
        payload = imported.find((item) => item.id === application.id) ?? {
          id: application.id,
          data: application,
        };
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
          warnings: current?.warnings ?? [],
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
        warnings: current?.warnings ?? [],
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
    mutationFn: (applicationId: string) => withSignal(async (signal) => {
      await hydrationPromiseRef.current?.catch(() => undefined);
      const current = queryClient.getQueryData<ApplicationsSnapshot>(applicationsQueryKey);
      const existing = current?.items.find((item) => item.application.id === applicationId);
      await deleteApplication(
        applicationId,
        existing && existing.revision > 0 ? existing.revision : null,
        signal,
      );
      return applicationId;
    }),
    onMutate(applicationId) {
      cacheRevisionRef.current += 1;
      const previous = queryClient.getQueryData<ApplicationsSnapshot>(applicationsQueryKey);
      queryClient.setQueryData<ApplicationsSnapshot>(applicationsQueryKey, (current) => ({
        warnings: current?.warnings ?? [],
        items: (current?.items ?? []).filter((item) => item.application.id !== applicationId),
      }));
      return { previous };
    },
    onError(error, _applicationId, context) {
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
        warnings: current?.warnings ?? [],
        items: next.map((application) => ({
          application,
          revision: revisions.get(application.id) ?? 0,
        })),
      };
    });
  }, [queryClient]);

  const applications = useMemo(
    () => query.data?.items.map((item) => item.application) ?? [],
    [query.data?.items],
  );

  useEffect(() => {
    if (query.isPlaceholderData && applications.length === 0) return;
    window.localStorage.setItem(
      applicationsStorageKey,
      JSON.stringify(applications.map(applicationPayloadForStorage)),
    );
  }, [applications, query.isPlaceholderData]);

  const upsert = useCallback((application: TrackedApplication) => {
    return upsertMutation.mutateAsync({
      application,
      existed: Boolean(query.data?.items.some((item) => item.application.id === application.id)),
    });
  }, [query.data?.items, upsertMutation]);

  return {
    applications,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error : null,
    warnings: query.data?.warnings ?? [],
    refetch: query.refetch,
    upsert,
    remove: removeMutation.mutateAsync,
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
  };
}
