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
