import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import {
  VacancyFilterDialog,
  type VacancyFilterSettings,
} from "@/components/vacancy-filter-dialog";

const initialSettings: VacancyFilterSettings = {
  schemaVersion: 1,
  enabled: true,
  seniorityEnabled: true,
  allowedSeniority: ["mid", "senior"],
  excludedSeniority: ["director"],
  postingAgeEnabled: true,
  maxPostingAgeDays: 7,
  technologyStackEnabled: true,
  targetTechnologies: ["Python", "Django"],
  excludedTechnologies: ["C#", ".NET"],
  updatedAt: "2026-08-20T08:00:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

it("loads the global filter and preserves its criteria when it is disabled", async () => {
  const writes: Array<Record<string, unknown>> = [];
  const onClose = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input)).pathname;
      const method = init?.method ?? "GET";
      if (path === "/job-search/filter-settings" && method === "GET") {
        return response(initialSettings);
      }
      if (path === "/job-search/filter-settings" && method === "PUT") {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        writes.push(body);
        return response({
          ...initialSettings,
          ...body,
          updatedAt: "2026-08-20T09:00:00Z",
        });
      }
      throw new Error(`Unexpected request: ${method} ${path}`);
    }),
  );

  render(<VacancyFilterDialog open onClose={onClose} />);

  const enabledSwitch = await screen.findByRole("switch", {
    name: "Filter incoming vacancies",
  });
  expect(enabledSwitch).toHaveAttribute("aria-checked", "true");
  expect(screen.getByLabelText("Target technologies")).toHaveValue(
    "Python\nDjango",
  );
  expect(screen.getByLabelText("Excluded technologies")).toHaveValue(
    "C#\n.NET",
  );
  expect(
    within(screen.getByRole("group", { name: "Allowed seniority" })).getByRole(
      "button",
      { name: "Senior" },
    ),
  ).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(enabledSwitch);
  expect(enabledSwitch).toHaveAttribute("aria-checked", "false");
  expect(
    screen.getByText(/search-specific screening still applies/i),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Target technologies")).toHaveValue(
    "Python\nDjango",
  );

  fireEvent.click(screen.getByRole("button", { name: "Save filter" }));

  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toEqual({
    schemaVersion: 1,
    enabled: false,
    seniorityEnabled: true,
    allowedSeniority: ["mid", "senior"],
    excludedSeniority: ["director"],
    postingAgeEnabled: true,
    maxPostingAgeDays: 7,
    technologyStackEnabled: true,
    targetTechnologies: ["Python", "Django"],
    excludedTechnologies: ["C#", ".NET"],
  });
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("lets each criterion be disabled without losing its configured values", async () => {
  let savedBody: Record<string, unknown> | null = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") {
        savedBody = JSON.parse(String(init.body)) as Record<string, unknown>;
        return response({ ...initialSettings, ...savedBody });
      }
      return response(initialSettings);
    }),
  );

  render(<VacancyFilterDialog open onClose={vi.fn()} />);
  await screen.findByRole("switch", { name: "Filter incoming vacancies" });

  const senioritySwitch = screen.getByRole("switch", {
    name: "Enable seniority filter",
  });
  const postingAgeSwitch = screen.getByRole("switch", {
    name: "Enable date posted filter",
  });
  const technologySwitch = screen.getByRole("switch", {
    name: "Enable technology stack filter",
  });

  fireEvent.click(senioritySwitch);
  fireEvent.click(postingAgeSwitch);
  fireEvent.click(technologySwitch);

  expect(senioritySwitch).toHaveAttribute("aria-checked", "false");
  expect(postingAgeSwitch).toHaveAttribute("aria-checked", "false");
  expect(technologySwitch).toHaveAttribute("aria-checked", "false");
  expect(screen.getByLabelText("Target technologies")).toHaveValue(
    "Python\nDjango",
  );
  expect(screen.getByRole("button", { name: "Past week" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  fireEvent.click(screen.getByRole("button", { name: "Save filter" }));

  await waitFor(() => expect(savedBody).not.toBeNull());
  expect(savedBody).toMatchObject({
    seniorityEnabled: false,
    allowedSeniority: ["mid", "senior"],
    postingAgeEnabled: false,
    maxPostingAgeDays: 7,
    technologyStackEnabled: false,
    targetTechnologies: ["Python", "Django"],
  });
});

it("keeps seniority groups exclusive and normalizes technology entries", async () => {
  let savedBody: Record<string, unknown> | null = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input)).pathname;
      const method = init?.method ?? "GET";
      if (path === "/job-search/filter-settings" && method === "GET") {
        return response({
          ...initialSettings,
          enabled: false,
          allowedSeniority: [],
          excludedSeniority: [],
          targetTechnologies: [],
          excludedTechnologies: [],
        });
      }
      if (path === "/job-search/filter-settings" && method === "PUT") {
        savedBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
        return response({
          ...initialSettings,
          ...savedBody,
          updatedAt: "2026-08-20T09:00:00Z",
        });
      }
      throw new Error(`Unexpected request: ${method} ${path}`);
    }),
  );

  render(<VacancyFilterDialog open onClose={vi.fn()} />);
  await screen.findByRole("switch", { name: "Filter incoming vacancies" });

  const allowedGroup = screen.getByRole("group", {
    name: "Allowed seniority",
  });
  const excludedGroup = screen.getByRole("group", {
    name: "Excluded seniority",
  });
  const allowedSenior = within(allowedGroup).getByRole("button", {
    name: "Senior",
  });
  const excludedSenior = within(excludedGroup).getByRole("button", {
    name: "Senior",
  });

  fireEvent.click(allowedSenior);
  expect(allowedSenior).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(excludedSenior);
  expect(allowedSenior).toHaveAttribute("aria-pressed", "false");
  expect(excludedSenior).toHaveAttribute("aria-pressed", "true");

  fireEvent.change(screen.getByLabelText("Target technologies"), {
    target: { value: "Python\nDjango   REST, python" },
  });
  fireEvent.change(screen.getByLabelText("Excluded technologies"), {
    target: { value: "C#, .NET" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save filter" }));

  await waitFor(() => expect(savedBody).not.toBeNull());
  expect(savedBody).toMatchObject({
    allowedSeniority: [],
    excludedSeniority: ["senior"],
    targetTechnologies: ["Python", "Django REST"],
    excludedTechnologies: ["C#", ".NET"],
  });
});

it("shows load failures, retries, and lets the user cancel without saving", async () => {
  let getAttempts = 0;
  const onClose = vi.fn();
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input)).pathname;
      const method = init?.method ?? "GET";
      if (path !== "/job-search/filter-settings" || method !== "GET") {
        throw new Error(`Unexpected request: ${method} ${path}`);
      }
      getAttempts += 1;
      return getAttempts === 1
        ? response({ detail: "Filter service is unavailable" }, 503)
        : response(initialSettings);
    },
  );
  vi.stubGlobal("fetch", fetchMock);

  render(<VacancyFilterDialog open onClose={onClose} />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Filter service is unavailable",
  );
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByRole("switch", { name: "Filter incoming vacancies" });

  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(
    fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    ),
  ).toHaveLength(0);
});

it("keeps keyboard focus inside the dialog and restores it after closing", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response(initialSettings)));
  const onClose = vi.fn();
  const dialog = (open: boolean) => (
    <>
      <button type="button">Open filter</button>
      <VacancyFilterDialog open={open} onClose={onClose} />
    </>
  );
  const { rerender } = render(dialog(false));
  const trigger = screen.getByRole("button", { name: "Open filter" });
  trigger.focus();

  rerender(dialog(true));
  await screen.findByRole("switch", { name: "Filter incoming vacancies" });
  const close = screen.getByRole("button", { name: "Close vacancy filter" });
  const save = screen.getByRole("button", { name: "Save filter" });
  expect(close).toHaveFocus();

  fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
  expect(save).toHaveFocus();
  fireEvent.keyDown(save, { key: "Tab" });
  expect(close).toHaveFocus();

  rerender(dialog(false));
  await waitFor(() => expect(trigger).toHaveFocus());
});

it("shows FastAPI validation details when saving fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      init?.method === "PUT"
        ? response(
            {
              detail: [
                {
                  loc: ["body", "targetTechnologies"],
                  msg: "Technology names must be at most 80 characters",
                  type: "value_error",
                },
              ],
            },
            422,
          )
        : response(initialSettings),
    ),
  );

  render(<VacancyFilterDialog open onClose={vi.fn()} />);
  await screen.findByRole("switch", { name: "Filter incoming vacancies" });
  fireEvent.click(screen.getByRole("button", { name: "Save filter" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Technology names must be at most 80 characters",
  );
});

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}
