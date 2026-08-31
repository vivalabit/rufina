import { normalizeExternalUrl } from "@/shared/formatting/urls";
import type { CandidateProfile, ExperienceEntry } from "@/shared/types/profile";

import { candidateProfileDataFields } from "./defaults";
import { parseEducationEntries, parseExperienceEntries, parseProfileLines, type ProfileIdFactory } from "./entries";
import { hasProfileValue } from "./normalizers";
import { parseJobPreferences } from "./preferences";

export function hasCandidateProfileData(profile: CandidateProfile) {
  return candidateProfileDataFields.some((field) => hasProfileValue(profile[field]));
}

export function hasQuantifiedAchievements(entries: ExperienceEntry[]) {
  return entries.some((entry) => /\d|%|\bpercent\b|\busers?\b|\bclients?\b|\brevenue\b|\bcost\b|\bsaved\b|\breduced\b|\bincreased\b/i.test(entry.description));
}

function formatCompactList(values: string[], fallback: string) {
  if (values.length === 0) return fallback;
  if (values.length <= 3) return values.join(", ");
  return `${values.slice(0, 3).join(", ")} +${values.length - 3} more`;
}

function hasProfileContactLink(profile: CandidateProfile) {
  return [profile.linkedin, profile.github, profile.portfolio, profile.personal_site]
    .some((value) => hasProfileValue(value) && Boolean(normalizeExternalUrl(value)));
}

export function getAiMatchProfile(profile: CandidateProfile, createId: ProfileIdFactory) {
  const skills = parseProfileLines(profile.skills);
  const experienceEntries = parseExperienceEntries(profile.experience, createId);
  const educationEntries = parseEducationEntries(profile.education, createId);
  const preferences = parseJobPreferences(profile.job_preferences);
  const hasResume = hasProfileValue(profile.resume_file_name) && hasProfileValue(profile.resume_file_id);
  const hasSalaryPreference = preferences.no_preference.includes("salary") || hasProfileValue(preferences.salary_min);
  const hasAuthorizationPreference = preferences.no_preference.includes("work_authorization") || hasProfileValue(preferences.work_authorization);
  const hasLocationPreference = preferences.no_preference.includes("locations") || preferences.locations.length > 0;
  const hasIndustryPreference = preferences.no_preference.includes("industries") || preferences.industries.length > 0;
  const hasRolePreference = preferences.no_preference.includes("desired_roles") || preferences.desired_roles.length > 0 || hasProfileValue(profile.desired_role);
  const signals = [
    hasProfileValue(profile.current_role) ? `Current role: ${profile.current_role}` : "",
    hasProfileValue(profile.desired_role) ? `Target: ${profile.desired_role}` : "",
    skills.length > 0 ? `${skills.length} skills: ${formatCompactList(skills, "skills added")}` : "",
    experienceEntries.length > 0 ? `${experienceEntries.length} experience entr${experienceEntries.length === 1 ? "y" : "ies"}` : "",
    educationEntries.length > 0 ? `${educationEntries.length} education / certification entr${educationEntries.length === 1 ? "y" : "ies"}` : "",
    hasLocationPreference ? `Locations: ${preferences.no_preference.includes("locations") ? "No preference" : formatCompactList(preferences.locations, "set")}` : "",
    hasAuthorizationPreference ? `Work authorization: ${preferences.no_preference.includes("work_authorization") ? "No preference" : preferences.work_authorization}` : "",
    hasResume ? `Resume attached: ${profile.resume_file_name}` : "",
  ].filter(Boolean);
  const gaps = [
    !hasProfileValue(profile.current_role) ? "Add current role" : "",
    !hasRolePreference ? "Add target role or desired roles" : "",
    skills.length === 0 ? "Add skills" : "",
    experienceEntries.length === 0 ? "Add or import work experience" : "",
    experienceEntries.length > 0 && !hasQuantifiedAchievements(experienceEntries) ? "Add quantified achievements to experience" : "",
    !hasLocationPreference ? "Add preferred locations or mark no preference" : "",
    !hasIndustryPreference ? "Add preferred industries or mark no preference" : "",
    !hasSalaryPreference ? "Add salary preference or mark no preference" : "",
    !hasAuthorizationPreference ? "Add work authorization preference or mark no preference" : "",
    !hasResume ? "Attach resume for imports and matching" : "",
  ].filter(Boolean);
  return { signals, gaps: gaps.slice(0, 5) };
}

export function getProfileCompletionItems(profile: CandidateProfile, createId: ProfileIdFactory) {
  const skills = parseProfileLines(profile.skills);
  const experienceEntries = parseExperienceEntries(profile.experience, createId);
  const educationEntries = parseEducationEntries(profile.education, createId);
  const preferences = parseJobPreferences(profile.job_preferences);
  const hasRolePreference = preferences.no_preference.includes("desired_roles") || preferences.desired_roles.length > 0 || hasProfileValue(profile.desired_role);
  const hasLocationPreference = preferences.no_preference.includes("locations") || preferences.locations.length > 0 || hasProfileValue(profile.location);
  const hasAuthorizationPreference = preferences.no_preference.includes("work_authorization") || hasProfileValue(preferences.work_authorization);
  const hasSalaryPreference = preferences.no_preference.includes("salary") || hasProfileValue(preferences.salary_min);
  return [
    { label: "Name and current role", complete: hasProfileValue(profile.name) && hasProfileValue(profile.current_role), action: "Add name and current role" },
    { label: "Target role", complete: hasRolePreference, action: "Add target role or desired roles" },
    { label: "Location and work format", complete: hasProfileValue(profile.location) && hasProfileValue(profile.work_format), action: "Add location and work format" },
    { label: "Summary", complete: hasProfileValue(profile.headline), action: "Add short professional summary" },
    { label: "Contact link", complete: hasProfileContactLink(profile), action: "Add LinkedIn, GitHub, or portfolio" },
    { label: "Resume", complete: hasProfileValue(profile.resume_file_name) && hasProfileValue(profile.resume_file_id), action: "Attach resume" },
    { label: "Experience", complete: experienceEntries.length > 0, action: "Add or import experience" },
    { label: "Quantified achievements", complete: experienceEntries.length > 0 && hasQuantifiedAchievements(experienceEntries), action: "Add metrics to experience" },
    { label: "Skills", complete: skills.length >= 6, action: skills.length > 0 ? "Add a few more skills" : "Add skills" },
    { label: "Education or certification", complete: educationEntries.length > 0, action: "Add education or certification" },
    { label: "Preferred locations", complete: hasLocationPreference, action: "Add preferred locations or mark no preference" },
    { label: "Work authorization", complete: hasAuthorizationPreference, action: "Add work authorization preference" },
    { label: "Salary preference", complete: hasSalaryPreference, action: "Add salary floor or mark no preference" },
  ];
}

export function getProfileCompletion(profile: CandidateProfile, createId: ProfileIdFactory) {
  const items = getProfileCompletionItems(profile, createId);
  return Math.round((items.filter((item) => item.complete).length / items.length) * 100);
}
