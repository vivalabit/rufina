import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const pageSource = readFileSync(
  resolve(process.cwd(), "src/app/page.tsx"),
  "utf8",
);

describe("page server-state boundaries", () => {
  it("delegates each server-state domain to its feature hook", () => {
    for (const hook of [
      "useJobs",
      "useJobSearch",
      "useApplications",
      "useApplicationEvents",
      "useProfile",
      "useActivityFeed",
      "useAppSettings",
    ]) {
      expect(pageSource).toContain(`${hook}(`);
    }
  });

  it("does not issue domain API requests directly", () => {
    const directFetches = [...pageSource.matchAll(/(?<![\w])fetch\(([^\n]+)/g)]
      .map((match) => match[1].trim());
    expect(directFetches).toEqual([
      "document.downloadUrl, { cache: \"no-store\" });",
    ]);
  });
});
