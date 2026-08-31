import type { CandidateProfile } from "@/shared/types/profile";

import { defaultCandidateProfile } from "./defaults";

const legacyCandidateProfileValues: Partial<CandidateProfile> = {
  name: "Alex Johnson", current_role: "Senior Product Designer", desired_role: "Design Manager",
  location: "San Francisco, CA, USA", work_format: "Remote, open to hybrid",
  headline: "Product designer with 7+ years of experience crafting intuitive B2B and B2C digital experiences. Combines user empathy with data-driven design to ship impactful products.",
  linkedin: "linkedin.com/in/alexjohnson", github: "github.com/alexjohnson",
  portfolio: "alexjohnson.design", personal_site: "alexjohnson.com",
};

export function normalizeCandidateProfile(profile: Partial<CandidateProfile>): CandidateProfile {
  const normalizedProfile = { ...defaultCandidateProfile };
  for (const field of Object.keys(defaultCandidateProfile) as Array<keyof CandidateProfile>) {
    const value = profile[field];
    if (typeof value === "string") normalizedProfile[field] = value;
  }
  if (!normalizedProfile.avatar_url || normalizedProfile.avatar_url === "/avatars/pug.svg") {
    normalizedProfile.avatar_url = defaultCandidateProfile.avatar_url;
  }
  for (const [field, legacyValue] of Object.entries(legacyCandidateProfileValues) as Array<[keyof CandidateProfile, string]>) {
    if (normalizedProfile[field] === legacyValue) normalizedProfile[field] = "";
  }
  return normalizedProfile;
}

export function hasProfileValue(value: string | undefined) {
  return Boolean(value?.trim());
}
