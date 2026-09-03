import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const pageSource = readFileSync(
  resolve(process.cwd(), "src/app/page.tsx"),
  "utf8",
);
const workspaceSource = readFileSync(
  resolve(process.cwd(), "src/components/app-workspace-root.tsx"),
  "utf8",
);

describe("page state ownership boundaries", () => {
  it("composes each server-state domain through its feature hook", () => {
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
    expect(directFetches).toEqual([]);
  });

  it("keeps only route and global assistant launch state in page.tsx", () => {
    const pageStateNames = [...pageSource.matchAll(
      /const \[([\w]+),\s*[\w]+\] = useState/g,
    )].map((match) => match[1]);

    expect(pageStateNames).toEqual(["route", "assistantLaunch"]);
    expect(pageSource).toContain("<AppShell");
    expect(pageSource).not.toMatch(/DialogOpen|Draft|Filter|selectedJobId|selectedApplicationId/);
  });

  it("derives selected entities from the URL route instead of local state", () => {
    expect(workspaceSource).toContain('const selectedJobId = route.jobId ?? "";');
    expect(workspaceSource).toContain('const selectedApplicationId = route.applicationId ?? "";');
    expect(workspaceSource).not.toMatch(/useState\([^\n]*selected(Job|Application)/);
  });
});
