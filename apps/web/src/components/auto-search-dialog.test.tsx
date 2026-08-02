import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AutoSearchDialog,
  type JobScreeningAuditEntry,
  type JobSearchConfig,
  type JobSearchSchedule,
} from "@/components/auto-search-dialog";

const config: JobSearchConfig = {
  id: "config-1",
  name: "Zurich engineering",
  filters: {
    keywords: "Software Engineer",
    location: "Zurich",
    resultsLimit: 40,
    deduplicate: true,
  },
  createdAt: "2026-07-23T08:00:00Z",
  updatedAt: "2026-07-23T08:00:00Z",
};

const schedule: JobSearchSchedule = {
  id: "schedule-1",
  name: "LinkedIn · 13:00",
  configId: config.id,
  sources: ["linkedin"],
  frequency: "weekdays",
  weekdays: [],
  localTime: "13:00:00",
  timezone: "Europe/Zurich",
  aiAnalysisEnabled: true,
  enabled: true,
  nextRunAt: "2026-07-24T11:00:00Z",
  lastRunAt: null,
  createdAt: "2026-07-23T08:00:00Z",
  updatedAt: "2026-07-23T08:00:00Z",
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("AutoSearchDialog", () => {
  it("shows persisted rules and runs one immediately", async () => {
    const requests: Array<{ path: string; method: string }> = [];
    const onVacanciesChanged = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input)).pathname;
        const method = init?.method ?? "GET";
        requests.push({ path, method });

        if (path === "/job-search/configs") return response([config]);
        if (path === "/job-search/schedules" && method === "GET") {
          return response([schedule]);
        }
        if (path === `/job-search/schedules/${schedule.id}/run`) {
          return response({
            status: "completed",
            jobsFound: 12,
            jobsAdded: 7,
            warning: null,
          });
        }
        throw new Error(`Unexpected request: ${method} ${path}`);
      }),
    );

    render(
      <AutoSearchDialog
        open
        onClose={vi.fn()}
        onVacanciesChanged={onVacanciesChanged}
      />,
    );

    expect(await screen.findByText(schedule.name)).toBeInTheDocument();
    expect(screen.getByText("LinkedIn")).toBeInTheDocument();
    expect(screen.getByText(config.name)).toBeInTheDocument();
    expect(screen.getByText("Screening off")).toBeInTheDocument();
    expect(screen.getByText("Weekdays · 13:00")).toBeInTheDocument();
    expect(screen.getByText("Enabled")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: `Run ${schedule.name} now` }),
    );

    await waitFor(() => {
      expect(requests).toContainEqual({
        path: `/job-search/schedules/${schedule.id}/run`,
        method: "POST",
      });
    });
    expect(onVacanciesChanged).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText(/12 found · 7 added/),
    ).toBeInTheDocument();
  });

  it("keeps rejected vacancies in a separate actionable screening audit", async () => {
    const requests: Array<{ path: string; method: string }> = [];
    const onVacanciesChanged = vi.fn();
    let auditEntry: JobScreeningAuditEntry = {
      id: "decision-salesperson",
      jobId: "linkedin-salesperson",
      decision: "reject",
      reasonCode: "excluded_role",
      reason: "Salesperson conflicts with the target Product Manager role",
      matchedRuleIds: ["rule-1"],
      configHash: "a".repeat(64),
      configId: config.id,
      model: "gpt-5-nano",
      promptVersion: "job-screening-prompt-v1",
      title: "Salesperson",
      company: "Retail AG",
      sourceUrl: "https://example.test/salesperson",
      checkedAt: "2026-07-24T10:00:00Z",
      invalidatedAt: null,
      manuallyAllowedAt: null,
      canRecheck: true,
      canAllowManually: true,
    };
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input)).pathname;
        const method = init?.method ?? "GET";
        requests.push({ path, method });
        if (path === "/job-search/configs") return response([config]);
        if (path === "/job-search/schedules") return response([schedule]);
        if (path === "/job-search/screening-audit" && method === "GET") {
          return response([auditEntry]);
        }
        if (
          path ===
            `/job-search/screening-audit/${auditEntry.id}/allow` &&
          method === "POST"
        ) {
          auditEntry = {
            ...auditEntry,
            invalidatedAt: "2026-07-24T10:05:00Z",
            manuallyAllowedAt: "2026-07-24T10:05:00Z",
            canRecheck: false,
            canAllowManually: false,
          };
          return response(auditEntry);
        }
        throw new Error(`Unexpected request: ${method} ${path}`);
      }),
    );

    render(
      <AutoSearchDialog
        open
        onClose={vi.fn()}
        onVacanciesChanged={onVacanciesChanged}
      />,
    );
    await screen.findByText(schedule.name);
    expect(screen.queryByText("Salesperson")).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Screening audit" }),
    );

    expect(
      await screen.findByRole("dialog", { name: "Screening audit" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Salesperson")).toBeInTheDocument();
    expect(screen.getByText("Retail AG")).toBeInTheDocument();
    expect(screen.getByText("excluded_role")).toBeInTheDocument();
    expect(screen.getByText("Matched rules: rule-1")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Recheck" }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Allow manually" }),
    );

    await waitFor(() => {
      expect(requests).toContainEqual({
        path: `/job-search/screening-audit/${auditEntry.id}/allow`,
        method: "POST",
      });
    });
    expect(onVacanciesChanged).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText(
        "Vacancy allowed manually and added to the client list",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Allowed manually")).toBeInTheDocument();
  });

  it("duplicates a rule with a different source and time", async () => {
    const schedulePayloads: Array<Record<string, unknown>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input)).pathname;
        const method = init?.method ?? "GET";

        if (path === "/job-search/configs") return response([config]);
        if (path === "/job-search/schedules" && method === "GET") {
          return response([schedule]);
        }
        if (path === "/job-search/schedules" && method === "POST") {
          schedulePayloads.push(JSON.parse(String(init?.body)));
          return response({
            ...schedule,
            ...schedulePayloads.at(-1),
            id: "schedule-2",
          });
        }
        throw new Error(`Unexpected request: ${method} ${path}`);
      }),
    );

    render(<AutoSearchDialog open onClose={vi.fn()} />);
    await screen.findByText(schedule.name);

    fireEvent.click(
      screen.getByRole("button", { name: `Duplicate ${schedule.name}` }),
    );
    expect(
      screen.getByRole("dialog", { name: "Duplicate auto-search" }),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Rule name"), {
      target: { value: "Indeed · 15:00" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "LinkedIn" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Indeed" }),
    );
    fireEvent.change(screen.getByLabelText("Local time"), {
      target: { value: "15:00" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Create duplicate" }),
    );

    await waitFor(() => expect(schedulePayloads).toHaveLength(1));
    expect(schedulePayloads[0]).toMatchObject({
      name: "Indeed · 15:00",
      configId: config.id,
      sources: ["indeed"],
      frequency: "weekdays",
      localTime: "15:00:00",
      timezone: "Europe/Zurich",
      aiAnalysisEnabled: true,
      enabled: true,
    });
  });

  it("creates a reusable config together with a new rule", async () => {
    const writes: Array<{
      path: string;
      body: Record<string, unknown>;
    }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input)).pathname;
        const method = init?.method ?? "GET";

        if (method === "GET" && path === "/job-search/configs") {
          return response([]);
        }
        if (method === "GET" && path === "/job-search/schedules") {
          return response([]);
        }
        if (method === "POST" && path === "/job-search/configs") {
          const body = JSON.parse(String(init?.body));
          writes.push({ path, body });
          return response({ ...config, ...body });
        }
        if (method === "POST" && path === "/job-search/schedules") {
          const body = JSON.parse(String(init?.body));
          writes.push({ path, body });
          return response({ ...schedule, ...body });
        }
        throw new Error(`Unexpected request: ${method} ${path}`);
      }),
    );

    render(<AutoSearchDialog open onClose={vi.fn()} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Create first rule" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Indeed" }));

    fireEvent.change(screen.getByLabelText("Rule name"), {
      target: { value: "Daily backend roles" },
    });
    fireEvent.change(screen.getByLabelText("Config name"), {
      target: { value: "Backend roles" },
    });
    fireEvent.change(screen.getByLabelText("Keywords"), {
      target: { value: "Backend Engineer" },
    });
    fireEvent.change(screen.getByLabelText("Location"), {
      target: { value: "Remote" },
    });
    fireEvent.click(screen.getByRole("switch", { name: "Pre-screening" }));
    fireEvent.change(screen.getByLabelText("Target professions"), {
      target: { value: "Backend Engineer\nSoftware Engineer" },
    });
    fireEvent.change(screen.getByLabelText("Excluded professions"), {
      target: { value: "Sales Manager, Recruiter" },
    });
    fireEvent.click(
      within(screen.getByRole("group", { name: "Allowed seniority" }))
        .getByRole("button", { name: "Mid" }),
    );
    fireEvent.click(
      within(screen.getByRole("group", { name: "Excluded seniority" }))
        .getByRole("button", { name: "Director" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Add hard rule" }));
    fireEvent.change(screen.getByLabelText("Hard rule 1 field"), {
      target: { value: "location" },
    });
    fireEvent.change(screen.getByLabelText("Hard rule 1 operator"), {
      target: { value: "equals" },
    });
    fireEvent.change(screen.getByLabelText("Hard rule 1 value"), {
      target: { value: "Remote" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Create auto-search" }),
    );

    await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes[0]).toEqual({
      path: "/job-search/configs",
      body: {
        name: "Backend roles",
        filters: {
          schemaVersion: 2,
          search: {
            keywords: "Backend Engineer",
            location: "Remote",
            resultsLimit: 50,
            deduplicate: true,
          },
          screening: {
            enabled: true,
            targetRoles: ["Backend Engineer", "Software Engineer"],
            excludedRoles: ["Sales Manager", "Recruiter"],
            allowedSeniority: ["mid"],
            excludedSeniority: ["director"],
            hardRules: [
              {
                field: "location",
                operator: "equals",
                value: "Remote",
                enabled: true,
              },
            ],
          },
        },
      },
    });
    expect(writes[1]).toMatchObject({
      path: "/job-search/schedules",
      body: {
        name: "Daily backend roles",
        configId: config.id,
        sources: ["linkedin", "indeed"],
      },
    });
  });

  it("reads versioned screening, summarizes it, and preserves unknown JSON", async () => {
    const versionedConfig: JobSearchConfig = {
      ...config,
      id: "versioned-config",
      filters: {
        schemaVersion: 2,
        futureRoot: { mode: "preview" },
        search: {
          keywords: "Platform Engineer",
          location: "Zurich",
          resultsLimit: 30,
          deduplicate: true,
          futureSearch: ["keep"],
        },
        screening: {
          enabled: true,
          targetRoles: ["Platform Engineer"],
          excludedRoles: ["Sales Manager"],
          allowedSeniority: ["mid", "senior"],
          excludedSeniority: ["director"],
          futureScreening: { threshold: 0.8 },
          hardRules: [
            {
              field: "location",
              operator: "equals",
              value: "Zurich",
              enabled: true,
              futureRule: "keep",
            },
          ],
        },
      },
    };
    const versionedSchedule = {
      ...schedule,
      configId: versionedConfig.id,
    };
    const configWrites: Array<Record<string, unknown>> = [];

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input)).pathname;
        const method = init?.method ?? "GET";
        if (path === "/job-search/configs" && method === "GET") {
          return response([versionedConfig]);
        }
        if (path === "/job-search/schedules" && method === "GET") {
          return response([versionedSchedule]);
        }
        if (
          path === `/job-search/configs/${versionedConfig.id}` &&
          method === "GET"
        ) {
          return response(versionedConfig);
        }
        if (
          path === `/job-search/configs/${versionedConfig.id}` &&
          method === "PATCH"
        ) {
          const body = JSON.parse(String(init?.body));
          configWrites.push(body);
          return response({ ...versionedConfig, ...body });
        }
        if (
          path === `/job-search/schedules/${versionedSchedule.id}` &&
          method === "PATCH"
        ) {
          return response({
            ...versionedSchedule,
            ...JSON.parse(String(init?.body)),
          });
        }
        throw new Error(`Unexpected request: ${method} ${path}`);
      }),
    );

    render(<AutoSearchDialog open onClose={vi.fn()} />);

    expect(
      await screen.findByText(
        "Screening on · 1 target role · 1 excluded role · 3 seniority filters · 1 hard rule",
      ),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: `Edit ${schedule.name}` }),
    );
    expect(screen.getByLabelText("Target professions")).toHaveValue(
      "Platform Engineer",
    );
    expect(screen.getByLabelText("Excluded professions")).toHaveValue(
      "Sales Manager",
    );
    fireEvent.change(screen.getByLabelText("Target professions"), {
      target: { value: "Platform Engineer\nBackend Engineer" },
    });
    fireEvent.change(screen.getByLabelText("Results limit"), {
      target: { value: "35" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(configWrites).toHaveLength(1));
    const filters = configWrites[0].filters as Record<string, unknown>;
    expect(filters.futureRoot).toEqual({ mode: "preview" });
    expect(filters.search).toMatchObject({
      resultsLimit: 35,
      futureSearch: ["keep"],
    });
    expect(filters.screening).toMatchObject({
      targetRoles: ["Platform Engineer", "Backend Engineer"],
      futureScreening: { threshold: 0.8 },
      hardRules: [
        expect.objectContaining({
          futureRule: "keep",
        }),
      ],
    });
  });

  it("preserves current screening when only search settings are edited from a partial config", async () => {
    const screening = {
      enabled: true,
      targetRoles: ["Product Manager"],
      excludedRoles: ["Cashier", "Salesperson"],
      allowedSeniority: ["entry"],
      excludedSeniority: ["senior"],
      futureScreening: { policy: "strict" },
      hardRules: [
        {
          id: "rule-location",
          field: "location",
          operator: "equals",
          value: "Zurich",
          enabled: true,
          futureRule: { source: "admin" },
        },
      ],
    };
    const partialConfig: JobSearchConfig = {
      ...config,
      id: "partial-config",
      filters: {
        schemaVersion: 2,
        search: {
          keywords: "Product Manager",
          location: "Zurich",
          resultsLimit: 30,
          deduplicate: true,
        },
      },
    };
    const currentConfig: JobSearchConfig = {
      ...partialConfig,
      filters: {
        schemaVersion: 2,
        futureRoot: "keep",
        search: {
          ...(partialConfig.filters.search as Record<string, unknown>),
          futureSearch: { locale: "de-CH" },
        },
        screening,
      },
    };
    const partialSchedule = {
      ...schedule,
      configId: partialConfig.id,
    };
    let savedFilters: Record<string, unknown> | null = null;
    const requests: Array<{ path: string; method: string }> = [];

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input)).pathname;
        const method = init?.method ?? "GET";
        requests.push({ path, method });
        if (path === "/job-search/configs" && method === "GET") {
          return response([partialConfig]);
        }
        if (path === "/job-search/schedules" && method === "GET") {
          return response([partialSchedule]);
        }
        if (
          path === `/job-search/configs/${partialConfig.id}` &&
          method === "GET"
        ) {
          return response(currentConfig);
        }
        if (
          path === `/job-search/configs/${partialConfig.id}` &&
          method === "PATCH"
        ) {
          const body = JSON.parse(String(init?.body));
          savedFilters = body.filters;
          return response({ ...currentConfig, ...body });
        }
        if (
          path === `/job-search/schedules/${partialSchedule.id}` &&
          method === "PATCH"
        ) {
          return response({
            ...partialSchedule,
            ...JSON.parse(String(init?.body)),
          });
        }
        throw new Error(`Unexpected request: ${method} ${path}`);
      }),
    );

    render(<AutoSearchDialog open onClose={vi.fn()} />);
    await screen.findByText("Screening off");
    fireEvent.click(
      screen.getByRole("button", { name: `Edit ${schedule.name}` }),
    );
    fireEvent.change(screen.getByLabelText("Results limit"), {
      target: { value: "45" },
    });
    fireEvent.click(screen.getByRole("switch", { name: "Deduplication" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(savedFilters).not.toBeNull());
    expect(requests).toContainEqual({
      path: `/job-search/configs/${partialConfig.id}`,
      method: "GET",
    });
    expect(savedFilters).toMatchObject({
      schemaVersion: 2,
      futureRoot: "keep",
      search: {
        resultsLimit: 45,
        deduplicate: false,
        futureSearch: { locale: "de-CH" },
      },
    });
    expect(
      (savedFilters as Record<string, unknown> | null)?.screening,
    ).toEqual(screening);
  });

  it("upgrades a legacy config only when screening is edited", async () => {
    const legacyConfig: JobSearchConfig = {
      ...config,
      id: "legacy-config",
      filters: {
        ...config.filters,
        futureLegacySearch: { keep: true },
      },
    };
    const legacySchedule = { ...schedule, configId: legacyConfig.id };
    let savedFilters: Record<string, unknown> | null = null;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input)).pathname;
        const method = init?.method ?? "GET";
        if (path === "/job-search/configs" && method === "GET") {
          return response([legacyConfig]);
        }
        if (path === "/job-search/schedules" && method === "GET") {
          return response([legacySchedule]);
        }
        if (
          path === `/job-search/configs/${legacyConfig.id}` &&
          method === "GET"
        ) {
          return response(legacyConfig);
        }
        if (
          path === `/job-search/configs/${legacyConfig.id}` &&
          method === "PATCH"
        ) {
          const body = JSON.parse(String(init?.body));
          savedFilters = body.filters;
          return response({ ...legacyConfig, ...body });
        }
        if (
          path === `/job-search/schedules/${legacySchedule.id}` &&
          method === "PATCH"
        ) {
          return response({
            ...legacySchedule,
            ...JSON.parse(String(init?.body)),
          });
        }
        throw new Error(`Unexpected request: ${method} ${path}`);
      }),
    );

    render(<AutoSearchDialog open onClose={vi.fn()} />);
    await screen.findByText("Screening off");
    fireEvent.click(
      screen.getByRole("button", { name: `Edit ${schedule.name}` }),
    );
    expect(screen.getByLabelText("Results limit")).toHaveValue(40);
    fireEvent.click(screen.getByRole("switch", { name: "Pre-screening" }));
    fireEvent.change(screen.getByLabelText("Target professions"), {
      target: { value: "Software Engineer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(savedFilters).not.toBeNull());
    expect(savedFilters).toMatchObject({
      schemaVersion: 2,
      search: {
        keywords: "Software Engineer",
        location: "Zurich",
        resultsLimit: 40,
        deduplicate: true,
        futureLegacySearch: { keep: true },
      },
      screening: {
        enabled: true,
        targetRoles: ["Software Engineer"],
      },
    });
  });
});

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}
