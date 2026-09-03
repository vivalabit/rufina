import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";

import { createClientId } from "@/lib/client-id";
import { ApiResponseError } from "@/shared/api/client";
import { ownerQueryKey } from "@/shared/api/query-key";
import { completedBrowserStorageMigrationValue } from "@/shared/browser-storage/constants";
import { isInlineDataUrl } from "@/shared/browser-storage/data-url";
import type { CandidateProfile } from "@/shared/types/profile";

import {
  deleteProfileFile,
  fetchProfile,
  fetchProfileFiles,
  importProfileEducation,
  importProfileExperience,
  importProfileSkills,
  patchProfileFile,
  ProfileFileUploadError,
  putProfile,
  uploadProfileFile,
} from "../api/client";
import {
  hydrateProfileFiles,
  mergeHydratedProfileMetadata,
  profilePayloadForApi,
} from "../api/mappers";
import {
  profileFileStorageMigrationKey,
  profileStorageKey,
} from "../browser-storage/keys";
import {
  hasLegacyProfileInlineFiles,
  migrateLegacyProfileFiles,
  readLegacyStoredCandidateProfile,
  type LegacyProfileFileUploadMetadata,
} from "../browser-storage/migrations";
import { defaultCandidateProfile } from "../model/defaults";
import { normalizeCandidateProfile } from "../model/normalizers";
import { hasCandidateProfileData } from "../model/selectors";

const profileQueryKey = ownerQueryKey(["profile"] as const);
const permanentLegacyFileStatuses = new Set([400, 413, 415, 422]);

type ProfileSnapshot = {
  profile: CandidateProfile;
  etag: string | null;
  warnings: string[];
};

function isPermanentLegacyFileUploadError(error: unknown) {
  return error instanceof ProfileFileUploadError && permanentLegacyFileStatuses.has(error.status);
}

async function loadProfileSnapshot(signal: AbortSignal): Promise<ProfileSnapshot> {
  const legacyProfile = readLegacyStoredCandidateProfile(window.localStorage);
  const storedProfile = legacyProfile
    ? normalizeCandidateProfile({
        ...legacyProfile,
        avatar_url: isInlineDataUrl(legacyProfile.avatar_url)
          ? defaultCandidateProfile.avatar_url
          : legacyProfile.avatar_url,
      } as Partial<CandidateProfile>)
    : null;
  const profileResource = await fetchProfile(signal);
  let initialFiles = null;
  try {
    initialFiles = await fetchProfileFiles(signal);
  } catch {
    // File metadata is independently recoverable; keep the text profile usable.
  }
  let loadedProfile = hydrateProfileFiles(
    normalizeCandidateProfile(profileResource.profile),
    initialFiles ?? [],
    createClientId,
  );
  let etag = profileResource.etag;
  let legacyProfileTextSaved = !storedProfile || hasCandidateProfileData(loadedProfile);
  const warnings: string[] = [];

  if (!hasCandidateProfileData(loadedProfile) && storedProfile) {
    try {
      const saved = await putProfile(profilePayloadForApi(storedProfile), etag, signal);
      etag = saved.etag;
      legacyProfileTextSaved = true;
      loadedProfile = hydrateProfileFiles(
        normalizeCandidateProfile(saved.profile),
        initialFiles ?? [],
        createClientId,
      );
    } catch {
      legacyProfileTextSaved = false;
    }
  }

  const finalizeLegacyStorage = () => {
    window.localStorage.setItem(
      profileFileStorageMigrationKey,
      completedBrowserStorageMigrationValue,
    );
    if (!storedProfile || legacyProfileTextSaved) {
      window.localStorage.removeItem(profileStorageKey);
    } else {
      window.localStorage.setItem(
        profileStorageKey,
        JSON.stringify(profilePayloadForApi(storedProfile)),
      );
      warnings.push("Legacy profile text was kept locally for retry; inline files were removed.");
    }
  };

  const hasLegacyInlineFiles = legacyProfile
    ? hasLegacyProfileInlineFiles(legacyProfile)
    : false;
  if (legacyProfile && hasLegacyInlineFiles && initialFiles !== null) {
    warnings.push(...await migrateLegacyProfileFiles(
      legacyProfile,
      initialFiles,
      {
        uploadFile: (file, metadata) => uploadProfileFile(file, metadata, signal),
        isPermanentUploadError: isPermanentLegacyFileUploadError,
      },
    ));
    loadedProfile = hydrateProfileFiles(
      loadedProfile,
      await fetchProfileFiles(signal),
      createClientId,
    );
    finalizeLegacyStorage();
  } else if (legacyProfile && !hasLegacyInlineFiles) {
    finalizeLegacyStorage();
  }

  return { profile: loadedProfile, etag, warnings };
}

export function useProfile() {
  const queryClient = useQueryClient();
  const mutationControllerRef = useRef<AbortController | null>(null);
  const query = useQuery({
    queryKey: profileQueryKey,
    queryFn: ({ signal }) => loadProfileSnapshot(signal),
  });

  const withMutationSignal = useCallback(async <T,>(operation: (signal: AbortSignal) => Promise<T>) => {
    mutationControllerRef.current?.abort();
    const controller = new AbortController();
    mutationControllerRef.current = controller;
    try {
      return await operation(controller.signal);
    } finally {
      if (mutationControllerRef.current === controller) mutationControllerRef.current = null;
    }
  }, []);

  useEffect(() => () => mutationControllerRef.current?.abort(), []);

  const saveMutation = useMutation({
    mutationFn: (nextProfile: CandidateProfile) => withMutationSignal(async (signal) => {
      const current = queryClient.getQueryData<ProfileSnapshot>(profileQueryKey);
      const saved = await putProfile(
        profilePayloadForApi(nextProfile),
        current?.etag ?? null,
        signal,
      );
      return {
        profile: mergeHydratedProfileMetadata(saved.profile, nextProfile),
        etag: saved.etag,
      };
    }),
    onSuccess(saved) {
      queryClient.setQueryData<ProfileSnapshot>(profileQueryKey, (current) => ({
        profile: saved.profile,
        etag: saved.etag,
        warnings: current?.warnings ?? [],
      }));
    },
    onError(error) {
      if (error instanceof ApiResponseError && error.status === 412) {
        void queryClient.invalidateQueries({ queryKey: profileQueryKey });
      }
    },
  });

  const refreshFiles = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: profileQueryKey });
    const snapshot = await queryClient.fetchQuery({
      queryKey: profileQueryKey,
      queryFn: ({ signal }) => loadProfileSnapshot(signal),
    });
    return snapshot.profile;
  }, [queryClient]);

  const uploadFile = useCallback(
    (file: Blob, metadata: LegacyProfileFileUploadMetadata) =>
      withMutationSignal((signal) => uploadProfileFile(file, metadata, signal)),
    [withMutationSignal],
  );
  const updateFile = useCallback(
    (fileId: string, metadata: Record<string, string>) =>
      withMutationSignal((signal) => patchProfileFile(fileId, metadata, signal)),
    [withMutationSignal],
  );
  const removeFile = useCallback(
    (fileId: string) => withMutationSignal((signal) => deleteProfileFile(fileId, signal)),
    [withMutationSignal],
  );

  const replaceFromServer = useCallback((profile: Partial<CandidateProfile>) => {
    queryClient.setQueryData<ProfileSnapshot>(profileQueryKey, (current) => ({
      profile: mergeHydratedProfileMetadata(profile, current?.profile ?? defaultCandidateProfile),
      etag: current?.etag ?? null,
      warnings: current?.warnings ?? [],
    }));
  }, [queryClient]);

  const updateCachedProfile = useCallback((
    update: CandidateProfile | ((current: CandidateProfile) => CandidateProfile),
  ) => {
    queryClient.setQueryData<ProfileSnapshot>(profileQueryKey, (current) => {
      const currentProfile = current?.profile ?? defaultCandidateProfile;
      return {
        profile: normalizeCandidateProfile(
          typeof update === "function" ? update(currentProfile) : update,
        ),
        etag: current?.etag ?? null,
        warnings: current?.warnings ?? [],
      };
    });
  }, [queryClient]);

  return {
    profile: query.data?.profile ?? defaultCandidateProfile,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error : null,
    warnings: query.data?.warnings ?? [],
    refetch: refreshFiles,
    save: saveMutation.mutateAsync,
    isSaving: saveMutation.isPending,
    saveError: saveMutation.error instanceof Error ? saveMutation.error : null,
    cancel: () => mutationControllerRef.current?.abort(),
    uploadFile,
    updateFile,
    removeFile,
    importExperience: (profileFileId: string) =>
      withMutationSignal((signal) => importProfileExperience(profileFileId, signal)),
    importEducation: (profileFileId: string) =>
      withMutationSignal((signal) => importProfileEducation(profileFileId, signal)),
    importSkills: (profileFileId: string) =>
      withMutationSignal((signal) => importProfileSkills(profileFileId, signal)),
    replaceFromServer,
    updateCachedProfile,
  };
}
