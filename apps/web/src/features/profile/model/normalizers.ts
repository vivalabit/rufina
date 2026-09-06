import type { CandidateProfile } from "@/shared/types/profile";

import { defaultCandidateProfile } from "./defaults";

export function normalizeCandidateProfile(profile: Partial<CandidateProfile>): CandidateProfile {
  const normalizedProfile = { ...defaultCandidateProfile };
  for (const field of Object.keys(defaultCandidateProfile) as Array<keyof CandidateProfile>) {
    const value = profile[field];
    if (typeof value === "string") normalizedProfile[field] = value;
  }
  if (!normalizedProfile.avatar_url || normalizedProfile.avatar_url === "/avatars/pug.svg") {
    normalizedProfile.avatar_url = defaultCandidateProfile.avatar_url;
  }
  return normalizedProfile;
}

export function hasProfileValue(value: string | undefined) {
  return Boolean(value?.trim());
}
