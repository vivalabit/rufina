import type { JobPreferences, PreferenceAnyField } from "@/shared/types/profile";

import { defaultJobPreferences } from "./defaults";
import { parseProfileLines } from "./entries";
import { hasProfileValue } from "./normalizers";

export function normalizePreferenceList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return Array.from(new Map(value.filter((item): item is string => typeof item === "string")
    .map((item) => item.trim()).filter(Boolean).map((item) => [item.toLowerCase(), item])).values());
}

export function normalizeNoPreferenceFields(value: unknown): PreferenceAnyField[] {
  const allowedFields = new Set<PreferenceAnyField>([
    "desired_roles", "seniority", "locations", "work_formats", "employment_types", "industries",
    "salary", "work_authorization", "languages", "company_sizes", "priorities",
  ]);
  return normalizePreferenceList(value).filter((item): item is PreferenceAnyField => allowedFields.has(item as PreferenceAnyField));
}

export function normalizeJobPreferences(value: Partial<JobPreferences>): JobPreferences {
  return {
    ...defaultJobPreferences, ...value,
    desired_roles: normalizePreferenceList(value.desired_roles), seniority: normalizePreferenceList(value.seniority),
    locations: normalizePreferenceList(value.locations), work_formats: normalizePreferenceList(value.work_formats),
    employment_types: normalizePreferenceList(value.employment_types), industries: normalizePreferenceList(value.industries),
    salary_min: value.salary_min?.trim() ?? "", salary_currency: value.salary_currency?.trim() || "CHF",
    work_authorization: value.work_authorization?.trim() ?? "",
    swiss_permit_status: value.work_authorization?.trim() === "Swiss permit" ? value.swiss_permit_status?.trim() ?? "" : "",
    languages: normalizePreferenceList(value.languages), company_sizes: normalizePreferenceList(value.company_sizes),
    priorities: normalizePreferenceList(value.priorities), notes: value.notes?.trim() ?? "",
    no_preference: normalizeNoPreferenceFields(value.no_preference),
  };
}

export function parseJobPreferences(value: string): JobPreferences {
  if (!value.trim()) return defaultJobPreferences;
  try {
    const parsed = JSON.parse(value) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return normalizeJobPreferences(parsed as Partial<JobPreferences>);
  } catch {
    // Fall back to the previous one-line-per-preference format.
  }
  return normalizeJobPreferences({ notes: parseProfileLines(value).join("\n") });
}

export function serializeJobPreferences(preferences: JobPreferences) {
  const normalizedPreferences = normalizeJobPreferences(preferences);
  const hasValues = normalizedPreferences.desired_roles.length > 0 || normalizedPreferences.seniority.length > 0 ||
    normalizedPreferences.locations.length > 0 || normalizedPreferences.work_formats.length > 0 ||
    normalizedPreferences.employment_types.length > 0 || normalizedPreferences.industries.length > 0 ||
    hasProfileValue(normalizedPreferences.salary_min) || hasProfileValue(normalizedPreferences.work_authorization) ||
    hasProfileValue(normalizedPreferences.swiss_permit_status) || normalizedPreferences.languages.length > 0 ||
    normalizedPreferences.company_sizes.length > 0 || normalizedPreferences.priorities.length > 0 ||
    normalizedPreferences.no_preference.length > 0 || hasProfileValue(normalizedPreferences.notes);
  return hasValues ? JSON.stringify(normalizedPreferences) : "";
}

export function formatPreferenceSummary(preferences: JobPreferences) {
  const preferenceValue = (field: PreferenceAnyField, values: string[]) => preferences.no_preference.includes(field) ? ["No preference"] : values;
  const items: Array<{ label: string; values: string[] }> = [
    { label: "Roles", values: preferenceValue("desired_roles", preferences.desired_roles) },
    { label: "Seniority", values: preferenceValue("seniority", preferences.seniority) },
    { label: "Locations", values: preferenceValue("locations", preferences.locations) },
    { label: "Work format", values: preferenceValue("work_formats", preferences.work_formats) },
    { label: "Employment", values: preferenceValue("employment_types", preferences.employment_types) },
    { label: "Industries", values: preferenceValue("industries", preferences.industries) },
    { label: "Languages", values: preferenceValue("languages", preferences.languages) },
    { label: "Company size", values: preferenceValue("company_sizes", preferences.company_sizes) },
    { label: "Priorities", values: preferenceValue("priorities", preferences.priorities) },
  ].filter((item) => item.values.length > 0);
  if (preferences.no_preference.includes("salary")) items.splice(6, 0, { label: "Salary floor", values: ["No preference"] });
  else if (hasProfileValue(preferences.salary_min)) items.splice(6, 0, { label: "Salary floor", values: [`${preferences.salary_currency} ${preferences.salary_min}`] });
  if (preferences.no_preference.includes("work_authorization")) items.splice(7, 0, { label: "Authorization", values: ["No preference"] });
  else if (hasProfileValue(preferences.work_authorization)) {
    const values = preferences.work_authorization === "Swiss permit" && hasProfileValue(preferences.swiss_permit_status)
      ? [`${preferences.work_authorization} (${preferences.swiss_permit_status})`] : [preferences.work_authorization];
    items.splice(7, 0, { label: "Authorization", values });
  }
  if (hasProfileValue(preferences.notes)) items.push({ label: "Notes", values: [preferences.notes] });
  return items;
}
