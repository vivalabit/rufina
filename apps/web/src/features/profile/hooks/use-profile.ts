import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";

import { createClientId } from "@/lib/client-id";
import { ApiResponseError } from "@/shared/api/client";
import { ownerQueryKey } from "@/shared/api/query-key";
import type { CandidateProfile } from "@/shared/types/profile";

import {
  deleteProfileFile,
  fetchProfile,
  fetchProfileFiles,
  importProfileEducation,
  importProfileExperience,
  importProfileSkills,
  patchProfileFile,
  putProfile,
  uploadProfileFile,
} from "../api/client";
import type { ProfileFileUploadMetadata } from "../api/dto";
import {
  hydrateProfileFiles,
  mergeHydratedProfileMetadata,
  profilePayloadForApi,
} from "../api/mappers";
import { defaultCandidateProfile } from "../model/defaults";
import { normalizeCandidateProfile } from "../model/normalizers";

const profileQueryKey = ownerQueryKey(["profile"] as const);

type ProfileSnapshot = {
  profile: CandidateProfile;
  etag: string | null;
};

async function loadProfileSnapshot(signal: AbortSignal): Promise<ProfileSnapshot> {
  const profileResource = await fetchProfile(signal);
  let initialFiles = null;
  try {
    initialFiles = await fetchProfileFiles(signal);
  } catch {
    // File metadata is independently recoverable; keep the text profile usable.
  }
  const loadedProfile = hydrateProfileFiles(
    normalizeCandidateProfile(profileResource.profile),
    initialFiles ?? [],
    createClientId,
  );
  return { profile: loadedProfile, etag: profileResource.etag };
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
      queryClient.setQueryData<ProfileSnapshot>(profileQueryKey, () => ({
        profile: saved.profile,
        etag: saved.etag,
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
    (file: Blob, metadata: ProfileFileUploadMetadata) =>
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
      };
    });
  }, [queryClient]);

  return {
    profile: query.data?.profile ?? defaultCandidateProfile,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error : null,
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
