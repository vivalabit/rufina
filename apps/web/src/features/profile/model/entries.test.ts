import { expect, it } from "vitest";

import { parseDocumentEntries, parseExperienceEntries, serializeDocumentEntries } from "./entries";

const ids = (prefix: string) => `${prefix}-test`;

it("uses a supplied id factory for id-less stored entries", () => {
  expect(parseExperienceEntries('[{"title":" Engineer "}]', ids)).toEqual([
    expect.objectContaining({ id: "experience-test", title: "Engineer" }),
  ]);
});

it("uses stable legacy document ids and strips pending files on serialization", () => {
  const documents = parseDocumentEntries('[{"title":"Certificate"}]', ids);
  expect(documents[0]?.id).toBe("legacy-document-0");
  expect(JSON.parse(serializeDocumentEntries([{ ...documents[0]!, pending_file: new File(["x"], "x.pdf") }], ids))[0].pending_file).toBeUndefined();
});

it("merges imported details only into their employer and preserves manual corrections across repeated imports", async () => {
  const { mergeExperienceEntries, normalizeExperienceEntry } = await import("./entries");
  const current = [normalizeExperienceEntry({ id: "manual-a", company: "Alpha", title: "Engineer", start_date: "2020-01", end_date: "2021-01",
    description: "Manual achievement", stack: [{ id: "tech-source-a", technology: "Python", context: "Manually corrected context", source_ids: ["cv"] }],
    projects: [{ id: "manual-project", name: "Manual project", description: "", project_type: "", team: "", systems: "", users: "", load: "" }],
  }, ids)];
  const imported = [normalizeExperienceEntry({ id: "import-a", company: "Alpha", title: "Engineer", start_date: "2020-01", end_date: "2021-01",
    description: "Imported achievement", stack: [{ id: "tech-source-a", technology: "Python", context: "Old imported context", source_ids: ["cv"] }],
    responsibilities: [{ id: "responsibility-a", responsibility: "Billing", decisions: "Queues" }],
  }, ids), normalizeExperienceEntry({ id: "import-b", company: "Beta", title: "Engineer", start_date: "2022-01", end_date: "2023-01",
    stack: [{ id: "tech-source-b", technology: "Go", context: "Search" }],
  }, ids)];
  const merged = mergeExperienceEntries(current, imported);
  const repeated = mergeExperienceEntries(merged, imported);
  expect(repeated).toEqual(merged);
  expect(merged[0].id).toBe("manual-a");
  expect(merged[0].stack?.[0].context).toBe("Manually corrected context");
  expect(merged[0].responsibilities).toEqual(imported[0].responsibilities);
  expect(merged[0].projects).toEqual(current[0].projects);
  expect(merged[1].stack?.[0].technology).toBe("Go");
  expect(current[0].description).toBe("Manual achievement");
});

it("does not match roles with unknown dates or ambiguous identities when importing work details", async () => {
  const { mergeExperienceEntries, normalizeExperienceEntry } = await import("./entries");
  const first = normalizeExperienceEntry({ id: "one", company: "Alpha", title: "Engineer" }, ids);
  const incoming = normalizeExperienceEntry({ id: "incoming", company: "Alpha", title: "Engineer",
    stack: [{ id: "stack", technology: "Python", context: "Imported context" }],
  }, ids);
  expect(mergeExperienceEntries([first], [incoming])).toHaveLength(2);
  const dated = { ...first, start_date: "2020-01", end_date: "2021-01" };
  const merged = mergeExperienceEntries([dated, { ...dated, id: "two" }], [{ ...incoming, start_date: "2020-01", end_date: "2021-01" }]);
  expect(merged).toHaveLength(3);
  expect(merged[0].stack).toBeUndefined();
  expect(merged[1].stack).toBeUndefined();
});
