import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import HomePage from "@/app/page";

function installSearchApi() {
  const runs: Array<Record<string, unknown>> = [];
  const config = {
    id: "marketing-profile",
    name: "Marketing",
    filters: {
      schemaVersion: 2,
      search: { keywords: "marketing" },
      screening: {
        enabled: true,
        targetRoles: ["Marketing"],
        targetSpecializations: ["SEO"],
      },
    },
    createdAt: "2026-10-29T00:00:00Z",
    updatedAt: "2026-10-29T00:00:00Z",
  };
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
    const rawUrl = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = new URL(rawUrl, "http://localhost").pathname;
    const method = init?.method ?? "GET";
    if (path === "/job-search/configs" && method === "GET") return Response.json([config]);
    if (path === "/job-search/source-configs" && method === "GET") {
      return Response.json([{
        id: "marketing-linkedin", configId: config.id, name: "Marketing · LinkedIn",
        source: "linkedin", filters: { keywords: "marketing" },
        createdAt: config.createdAt, updatedAt: config.updatedAt,
      }]);
    }
    if (path === "/job-search/run" && method === "POST") {
      runs.push(JSON.parse(String(init?.body)));
      return Response.json({ status: "completed", jobsFound: 0, jobsAdded: 0, sourceErrors: {}, warning: null });
    }
    if (path === "/settings") return Response.json({ auto_ai_match_enabled: false });
    if (path === "/profile") return Response.json({});
    if (method === "GET" && [
      "/jobs", "/jobs/state", "/applications", "/applications/events", "/job-search/runs",
    ].includes(path)) return Response.json([]);
    throw new Error(`Unexpected request: ${method} ${path}`);
  }));
  return runs;
}

async function openDirectCompanySearch() {
  window.history.replaceState(null, "", "#jobs");
  render(<HomePage />);
  fireEvent.click(await screen.findByRole("button", { name: "Search vacancies" }));
  fireEvent.click(screen.getByRole("button", { name: "Configure Direct Companies" }));
}

it("keeps Direct Company specializations through source preset changes and sends them in the manual search", async () => {
  const runs = installSearchApi();
  await openDirectCompanySearch();
  fireEvent.click(screen.getByRole("button", { name: "Include Direct Companies in search" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /SBB CFF FFS/ }));
  fireEvent.click(screen.getByRole("button", { name: "Backend" }));
  fireEvent.click(screen.getByRole("button", { name: "Frontend" }));

  fireEvent.click(screen.getByRole("button", { name: "Configure LinkedIn" }));
  await screen.findByRole("option", { name: "Marketing" });
  fireEvent.change(screen.getByLabelText("LinkedIn query config"), {
    target: { value: "marketing-linkedin" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Configure Direct Companies" }));
  expect(screen.getByLabelText("Direct company direction")).toHaveValue("information_technology");
  expect(screen.getByRole("button", { name: "Backend" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Frontend" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Start search" }));

  await waitFor(() => expect(runs).toHaveLength(1));
  expect(runs[0]).toMatchObject({
    sources: ["sbb"],
    sourceConfigIds: {},
    config: { filters: {
      search: { keywords: "", resultsLimit: 1000 },
      screening: {
        enabled: true,
        targetRoles: ["Information Technology"],
        targetSpecializations: ["Backend", "Frontend"],
      },
    } },
  });
});

it("clears specializations on direction change and reset", async () => {
  installSearchApi();
  await openDirectCompanySearch();
  fireEvent.click(screen.getByRole("button", { name: "Backend" }));
  fireEvent.change(screen.getByLabelText("Direct company direction"), { target: { value: "marketing" } });
  fireEvent.change(screen.getByLabelText("Direct company direction"), { target: { value: "information_technology" } });
  expect(screen.getByRole("button", { name: "Backend" })).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(screen.getByRole("button", { name: "Backend" }));
  fireEvent.click(screen.getByRole("button", { name: "Reset to defaults" }));
  fireEvent.click(screen.getByRole("button", { name: "Configure Direct Companies" }));
  expect(screen.getByRole("button", { name: "Backend" })).toHaveAttribute("aria-pressed", "false");
});
