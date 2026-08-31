import type { DocumentEntry, EducationEntry, ExperienceEntry } from "@/shared/types/profile";

import { defaultDocumentDraft, defaultEducationDraft, defaultExperienceDraft } from "./defaults";

export type ProfileIdFactory = (prefix: string) => string;

export function parseProfileLines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

export function normalizeExperienceEntry(entry: Partial<ExperienceEntry>, createId: ProfileIdFactory): ExperienceEntry {
  return {
    ...defaultExperienceDraft, ...entry, id: entry.id || createId("experience"),
    title: entry.title?.trim() ?? "", company: entry.company?.trim() ?? "",
    employment_type: entry.employment_type?.trim() || "Full-time", location: entry.location?.trim() ?? "",
    start_date: entry.start_date?.trim() ?? "", end_date: entry.is_current ? "" : entry.end_date?.trim() ?? "",
    is_current: Boolean(entry.is_current), description: entry.description?.trim() ?? "",
  };
}

export function parseExperienceEntries(value: string, createId: ProfileIdFactory): ExperienceEntry[] {
  if (!value.trim()) return [];
  try {
    const parsed = JSON.parse(value) as unknown;
    if (Array.isArray(parsed)) return parsed
      .filter((item): item is Partial<ExperienceEntry> => Boolean(item) && typeof item === "object")
      .map((item) => normalizeExperienceEntry(item, createId))
      .filter((item) => item.title || item.company || item.description);
  } catch {
    // Fall back to the previous one-line-per-entry format.
  }
  return parseProfileLines(value).map((item, index) => normalizeExperienceEntry({
    id: `legacy-experience-${index}`, title: item, description: item,
  }, createId));
}

export function serializeExperienceEntries(entries: ExperienceEntry[], createId: ProfileIdFactory) {
  return JSON.stringify(entries.map((entry) => normalizeExperienceEntry(entry, createId)));
}

function getExperienceFingerprint(entry: ExperienceEntry) {
  return [entry.title, entry.company, entry.start_date, entry.end_date].map((value) => value.trim().toLowerCase()).join("|");
}

export function mergeExperienceEntries(currentEntries: ExperienceEntry[], importedEntries: ExperienceEntry[]) {
  const existingFingerprints = new Set(currentEntries.map(getExperienceFingerprint));
  const nextEntries = [...currentEntries];
  for (const entry of importedEntries) {
    const fingerprint = getExperienceFingerprint(entry);
    if (!entry.title || !entry.company || existingFingerprints.has(fingerprint)) continue;
    existingFingerprints.add(fingerprint);
    nextEntries.push(entry);
  }
  return nextEntries;
}

export function normalizeEducationEntry(entry: Partial<EducationEntry>, createId: ProfileIdFactory): EducationEntry {
  return {
    ...defaultEducationDraft, ...entry, id: entry.id || createId("education"),
    institution: entry.institution?.trim() ?? "", credential: entry.credential?.trim() ?? "",
    field_of_study: entry.field_of_study?.trim() ?? "", location: entry.location?.trim() ?? "",
    start_date: entry.start_date?.trim() ?? "", end_date: entry.is_current ? "" : entry.end_date?.trim() ?? "",
    is_current: Boolean(entry.is_current), description: entry.description?.trim() ?? "",
  };
}

export function parseEducationEntries(value: string, createId: ProfileIdFactory): EducationEntry[] {
  if (!value.trim()) return [];
  try {
    const parsed = JSON.parse(value) as unknown;
    if (Array.isArray(parsed)) return parsed
      .filter((item): item is Partial<EducationEntry> => Boolean(item) && typeof item === "object")
      .map((item) => normalizeEducationEntry(item, createId))
      .filter((item) => item.institution || item.credential || item.field_of_study || item.description);
  } catch {
    // Fall back to the previous one-line-per-entry format.
  }
  return parseProfileLines(value).map((item, index) => normalizeEducationEntry({
    id: `legacy-education-${index}`, credential: item, description: item,
  }, createId));
}

export function serializeEducationEntries(entries: EducationEntry[], createId: ProfileIdFactory) {
  return JSON.stringify(entries.map((entry) => normalizeEducationEntry(entry, createId)));
}

function getEducationFingerprint(entry: EducationEntry) {
  return [entry.institution, entry.credential, entry.field_of_study, entry.start_date, entry.end_date]
    .map((value) => value.trim().toLowerCase()).join("|");
}

export function mergeEducationEntries(currentEntries: EducationEntry[], importedEntries: EducationEntry[]) {
  const existingFingerprints = new Set(currentEntries.map(getEducationFingerprint));
  const nextEntries = [...currentEntries];
  for (const entry of importedEntries) {
    const fingerprint = getEducationFingerprint(entry);
    if ((!entry.institution && !entry.credential) || existingFingerprints.has(fingerprint)) continue;
    existingFingerprints.add(fingerprint);
    nextEntries.push(entry);
  }
  return nextEntries;
}

export function inferDocumentLanguage(fileName: string, title = "") {
  const value = `${fileName} ${title}`.toLowerCase();
  if (/(?:^|[\s_.-])(de|deu|ger)(?:[\s_.-]|$)|deutsch|german/.test(value)) return "German";
  if (/(?:^|[\s_.-])(en|eng)(?:[\s_.-]|$)|english/.test(value)) return "English";
  return "";
}

export function normalizeDocumentEntry(entry: Partial<DocumentEntry>, fallbackId: string, createId: ProfileIdFactory): DocumentEntry {
  return {
    ...defaultDocumentDraft, ...entry, id: entry.id || fallbackId || createId("document"),
    title: entry.title?.trim() ?? "", category: entry.category?.trim() || "Other",
    language: entry.language?.trim() || inferDocumentLanguage(entry.file_name ?? "", entry.title ?? ""),
    issuer: entry.issuer?.trim() ?? "", notes: entry.notes?.trim() ?? "",
    file_name: entry.file_name?.trim() ?? "", file_size: entry.file_size?.trim() ?? "",
    file_type: entry.file_type?.trim() ?? "", uploaded_at: entry.uploaded_at?.trim() ?? "",
    download_url: entry.download_url ?? "", pending_file: entry.pending_file,
  };
}

export function parseDocumentEntries(value: string, createId: ProfileIdFactory): DocumentEntry[] {
  if (!value.trim()) return [];
  try {
    const parsed = JSON.parse(value) as unknown;
    if (Array.isArray(parsed)) return parsed
      .filter((item): item is Partial<DocumentEntry> => Boolean(item) && typeof item === "object")
      .map((item, index) => normalizeDocumentEntry(item, `legacy-document-${index}`, createId))
      .filter((item) => item.title || item.file_name || item.download_url);
  } catch {
    return [];
  }
  return [];
}

export function serializeDocumentEntries(entries: DocumentEntry[], createId: ProfileIdFactory) {
  if (entries.length === 0) return "";
  return JSON.stringify(entries.map((entry) => {
    const metadata = normalizeDocumentEntry(entry, "", createId);
    delete metadata.pending_file;
    return metadata;
  }));
}

export function mergeSkillLists(currentSkills: string[], importedSkills: string[]) {
  return Array.from(new Map([...currentSkills, ...importedSkills]
    .map((skill) => skill.trim()).filter(Boolean).map((skill) => [skill.toLowerCase(), skill])).values());
}
