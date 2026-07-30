import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import HomePage from "@/app/page";
import { installApplicationWorkspaceApiMock } from "@/test/application-workspace-harness";

const configuredAppSettings = {
  has_brightdata_api_key: true,
  brightdata_api_key_preview: "brig****-key",
  ai_backend: "openclaw_codex",
  openai_api_key_configured: true,
  openai_api_key_preview: "sk-e****-key",
  openai_api_model: "gpt-5.6-terra",
  openai_api_reasoning_effort: "medium",
  openai_api_timeout_seconds: 120,
  openai_api_max_attempts: 2,
  openai_api_retry_backoff_seconds: 0.8,
  ai_match_model: "openai/gpt-5.6-terra",
  ai_match_reasoning: "low",
  ai_match_batch_size: 1,
  ai_match_timeout_seconds: 120,
  ai_match_max_attempts: 2,
  job_screening_model: "openai/gpt-5-mini",
  job_screening_reasoning: "off",
  job_screening_batch_size: 10,
  job_screening_timeout_seconds: 60,
  job_screening_max_attempts: 2,
  job_screening_max_description_chars: 12_000,
};

function importedJobData({
  id,
  title,
  source = "linkedin",
}: {
  id: string;
  title: string;
  source?: "linkedin" | "indeed" | "jobs_ch";
}) {
  const sourceLabel =
    source === "indeed" ? "Indeed" : source === "jobs_ch" ? "jobs.ch" : "LinkedIn";
  return {
    id,
    company: "Example AG",
    title,
    location: "Zurich",
    type: "Full-time",
    salary: "Not specified",
    posted: sourceLabel,
    experience: "Entry level",
    department: `${sourceLabel} import`,
    match: 50,
    logo: source,
    overview: `Imported ${title}`,
    responsibilities: ["Review vacancy"],
    requirements: ["Entry level"],
    skills: [sourceLabel],
    recommendations: [],
    companyInfo: "Example vacancy",
    reviews: [],
    similarJobs: [],
    addedAt: new Date().toISOString(),
  };
}

it("deletes a legacy supporting document and hides stored cover letters", async () => {
  window.history.replaceState(null, "", "#profile");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const profileUpdates: Array<Record<string, unknown>> = [];
  let storedProfile: Record<string, unknown> = {
    name: "Eduard Ishchenko",
    documents: JSON.stringify([
      {
        title: "Legacy CV",
        category: "CV / Resume",
        language: "English",
        file_name: "legacy-cv.docx",
        file_size: "60 KB",
        file_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        uploaded_at: "2026-07-20T10:00:00.000Z",
        data_url: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cv",
      },
      {
        title: "Legacy Cover Letter",
        category: "Cover Letter",
        language: "German",
        file_name: "legacy-cover.docx",
        file_size: "37 KB",
        file_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        uploaded_at: "2026-07-20T10:00:00.000Z",
        data_url: "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cover",
      },
    ]),
  };
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";

    if (url.pathname === "/job-search/configs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET") return Response.json([]);
    if (url.pathname === "/profile" && method === "GET") return Response.json(storedProfile);
    if (url.pathname === "/profile" && method === "PUT") {
      storedProfile = JSON.parse(String(init?.body)) as Record<string, unknown>;
      profileUpdates.push(storedProfile);
      return Response.json(storedProfile);
    }
    if (url.pathname === "/settings" && method === "GET") return Response.json(configuredAppSettings);
    if ((url.pathname === "/applications" || url.pathname === "/applications/events") && method === "PUT") {
      return Response.json([]);
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  const legacyCv = await screen.findByText("Legacy CV");
  const legacyCvCard = legacyCv.closest("article");
  expect(legacyCvCard).not.toBeNull();
  fireEvent.click(within(legacyCvCard!).getByRole("button", { name: "Delete document" }));

  await waitFor(() => expect(screen.queryByText("Legacy CV")).not.toBeInTheDocument());
  expect(screen.queryByText("Legacy Cover Letter")).not.toBeInTheDocument();
  expect(profileUpdates).toHaveLength(1);
  const savedDocuments = JSON.parse(String(profileUpdates[0].documents)) as Array<{ id: string; title: string }>;
  expect(savedDocuments).toEqual([
    expect.objectContaining({ id: "legacy-document-1", title: "Legacy Cover Letter" }),
  ]);
});

it("offers CV / Resume as a supporting document type", async () => {
  window.history.replaceState(null, "", "#profile");
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";

    if (url.pathname === "/job-search/configs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET") return Response.json([]);
    if (url.pathname === "/profile" && method === "GET") {
      return Response.json({ name: "Eduard Ishchenko", documents: "" });
    }
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json(configuredAppSettings);
    }
    if (
      (url.pathname === "/applications" ||
        url.pathname === "/applications/events" ||
        url.pathname === "/jobs/dismissed-ids") &&
      method === "PUT"
    ) {
      return Response.json([]);
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  fireEvent.click(
    await screen.findByRole("button", { name: "Add document" }),
  );
  const typeSelect = screen.getByRole("combobox", { name: "Type" });
  expect(
    within(typeSelect).getByRole("option", { name: "CV / Resume" }),
  ).toBeInTheDocument();
  expect(
    within(typeSelect).queryByRole("option", { name: "Cover Letter" }),
  ).not.toBeInTheDocument();

  fireEvent.change(typeSelect, { target: { value: "CV / Resume" } });
  const languageLabel = screen
    .getByText("Document language", { exact: true })
    .closest("label");
  expect(languageLabel).not.toBeNull();
  expect(
    within(languageLabel!).getByRole("combobox"),
  ).toBeInTheDocument();
  expect(screen.getByText(/DOCX under 5MB/)).toBeInTheDocument();
});

it("saves a selectable AI backend without overwriting unrelated settings", async () => {
  window.history.replaceState(null, "", "#settings");
  const requests: Array<{ path: string; method: string; body?: Record<string, unknown> }> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl = typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined;
    requests.push({ path: url.pathname, method, body });

    if (url.pathname === "/job-search/configs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET") return Response.json([]);
    if (url.pathname === "/profile" && method === "GET") return Response.json({});
    if (url.pathname === "/settings" && method === "GET") return Response.json(configuredAppSettings);
    if (url.pathname === "/settings" && method === "PUT") {
      return Response.json({ ...configuredAppSettings, ...body });
    }

    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  expect(await screen.findByText("OpenAI API key saved but not in use")).toBeInTheDocument();
  expect(screen.getByText(/sk-e\*\*\*\*-key remains stored/)).toBeInTheDocument();
  const openAiMode = screen.getByRole("radio", { name: /OpenAI API/ });
  const openClawMode = screen.getByRole("radio", { name: /Codex credits via OpenClaw/ });
  expect(openClawMode).toBeChecked();
  fireEvent.click(openAiMode);
  expect(openAiMode).toBeChecked();
  expect(screen.getByText("Saved key: sk-e****-key. Leave blank to keep it.")).toBeInTheDocument();
  fireEvent.click(openClawMode);
  expect(screen.queryByLabelText("OpenAI API key")).not.toBeInTheDocument();
  expect(screen.getByText("OpenAI API key saved but not in use")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Vacancy pre-screening model"), {
    target: { value: "openai/gpt-5-mini-fast" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Vacancy pre-screening reasoning" }), {
    target: { value: "low" },
  });
  fireEvent.change(screen.getByLabelText("Full AI Match model"), {
    target: { value: "openai/gpt-5.6-sol" },
  });
  fireEvent.change(screen.getByRole("spinbutton", { name: "Full AI Match batch size" }), {
    target: { value: "4" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save AI settings" }));
  await waitFor(() => {
    expect(requests.filter((request) => request.path === "/settings" && request.method === "PUT")).toHaveLength(1);
  });
  const openClawUpdate = requests.filter((request) => request.path === "/settings" && request.method === "PUT").at(-1)?.body;
  expect(openClawUpdate).toMatchObject({
    ai_backend: "openclaw_codex",
    ai_match_model: "openai/gpt-5.6-sol",
    ai_match_batch_size: 4,
    job_screening_model: "openai/gpt-5-mini-fast",
    job_screening_reasoning: "low",
  });
  expect(openClawUpdate).not.toHaveProperty("openai_api_key");
  await screen.findByText("AI backend settings saved and activated");
  fireEvent.click(screen.getByRole("radio", { name: /OpenAI API/ }));
  fireEvent.change(screen.getByRole("combobox", { name: "OpenAI reasoning effort" }), {
    target: { value: "high" },
  });
  fireEvent.change(screen.getByRole("spinbutton", { name: "OpenAI timeout seconds" }), {
    target: { value: "90" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save AI settings" }));

  await waitFor(() => {
    expect(requests.filter((request) => request.path === "/settings" && request.method === "PUT")).toHaveLength(2);
  });
  const update = requests.filter((request) => request.path === "/settings" && request.method === "PUT").at(-1)?.body;
  expect(update).toMatchObject({
    ai_backend: "openai_api",
    openai_api_model: "gpt-5.6-terra",
    openai_api_reasoning_effort: "high",
    openai_api_timeout_seconds: 90,
    openai_api_max_attempts: 2,
    openai_api_retry_backoff_seconds: 0.8,
    ai_match_model: "openai/gpt-5.6-sol",
    ai_match_reasoning: "low",
    ai_match_batch_size: 4,
    ai_match_timeout_seconds: 120,
    ai_match_max_attempts: 2,
    job_screening_model: "openai/gpt-5-mini-fast",
    job_screening_reasoning: "low",
    job_screening_batch_size: 10,
    job_screening_timeout_seconds: 60,
    job_screening_max_attempts: 2,
    job_screening_max_description_chars: 12_000,
  });
  expect(update).not.toHaveProperty("openai_api_key");
  expect(update).not.toHaveProperty("brightdata_api_key");

  fireEvent.click(screen.getByRole("button", { name: "Delete saved OpenAI API key" }));
  await waitFor(() => {
    expect(requests.filter((request) => request.path === "/settings" && request.method === "PUT")).toHaveLength(3);
  });
  const deleteUpdate = requests.filter((request) => request.path === "/settings" && request.method === "PUT").at(-1)?.body;
  expect(deleteUpdate).toEqual({
    ai_backend: "openclaw_codex",
    openai_api_key: "",
  });
});

it("validates OpenAI API mode before saving", async () => {
  window.history.replaceState(null, "", "#settings");
  const requests: Array<{ path: string; method: string; body?: Record<string, unknown> }> = [];
  const unconfiguredSettings = {
    ...configuredAppSettings,
    openai_api_key_configured: false,
    openai_api_key_preview: "",
  };
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined;
    requests.push({ path: url.pathname, method, body });

    if (url.pathname === "/job-search/configs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET") return Response.json([]);
    if (url.pathname === "/profile" && method === "GET") return Response.json({});
    if (url.pathname === "/settings" && method === "GET") return Response.json(unconfiguredSettings);
    if (url.pathname === "/settings" && method === "PUT") return Response.json({ ...unconfiguredSettings, ...body, openai_api_key_configured: true, openai_api_key_preview: "sk-t****-key" });
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  fireEvent.click(await screen.findByRole("radio", { name: /OpenAI API/ }));
  const saveButton = screen.getByRole("button", { name: "Save AI settings" });
  expect(screen.getByRole("alert")).toHaveTextContent("Add an OpenAI API key before enabling this mode.");
  expect(saveButton).toBeDisabled();

  fireEvent.change(screen.getByLabelText("OpenAI API key"), { target: { value: "sk-test-key" } });
  fireEvent.change(screen.getByRole("spinbutton", { name: "OpenAI timeout seconds" }), { target: { value: "5" } });
  expect(screen.getByRole("alert")).toHaveTextContent("OpenAI timeout must be between 10 and 600 seconds.");
  expect(saveButton).toBeDisabled();

  fireEvent.change(screen.getByRole("spinbutton", { name: "OpenAI timeout seconds" }), { target: { value: "90" } });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(saveButton).toBeEnabled();
  fireEvent.click(saveButton);

  await waitFor(() => expect(requests.some((request) => request.path === "/settings" && request.method === "PUT")).toBe(true));
  const update = requests.find((request) => request.path === "/settings" && request.method === "PUT")?.body;
  expect(update).toMatchObject({
    ai_backend: "openai_api",
    openai_api_key: "sk-test-key",
    openai_api_timeout_seconds: 90,
  });
});

it("adds a manual vacancy to Jobs, persists it, and starts AI analysis", async () => {
  window.history.replaceState(null, "", "#jobs");
  const requests: Array<{ path: string; method: string; body?: unknown }> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl = typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) as unknown : undefined;
    requests.push({ path: url.pathname, method, body });

    if (url.pathname === "/job-search/configs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs" && method === "PUT") return Response.json([]);
    if (url.pathname === "/applications" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET") return Response.json([]);
    if (url.pathname === "/profile" && method === "GET") return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json({ has_brightdata_api_key: false, brightdata_api_key_preview: "" });
    }
    if (url.pathname === "/jobs/ai-match/run" && method === "POST") {
      return Response.json({
        runId: "manual-match-run",
        status: "queued",
        total: 1,
        processed: 0,
        updatedJobs: [],
      }, { status: 202 });
    }

    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  fireEvent.click(await screen.findByRole("button", { name: "Add vacancy" }));
  const dialog = screen.getByRole("dialog", { name: "Add vacancy" });
  expect(dialog).toBeInTheDocument();

  fireEvent.change(within(dialog).getByLabelText("Role title *"), {
    target: { value: "Backend Engineer" },
  });
  fireEvent.change(within(dialog).getByLabelText("Company *"), {
    target: { value: "Acme" },
  });
  fireEvent.change(within(dialog).getByLabelText("Location"), {
    target: { value: "Zurich / Remote" },
  });
  fireEvent.change(within(dialog).getByLabelText("Vacancy description *"), {
    target: { value: "Build Python services and maintain PostgreSQL systems. Five years of backend experience required." },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Add and analyze" }));

  expect(await screen.findAllByText("Backend Engineer")).not.toHaveLength(0);
  expect(screen.getByRole("button", { name: "Force AI match rerun" })).toBeDisabled();

  await waitFor(() => {
    expect(requests.some((request) => request.path === "/jobs" && request.method === "PUT")).toBe(true);
    expect(requests.some((request) => request.path === "/jobs/ai-match/run" && request.method === "POST")).toBe(true);
  });
  expect(
    requests.some((request) => request.path === "/job-search/run"),
  ).toBe(false);

  const persistedRequest = requests.find((request) => request.path === "/jobs" && request.method === "PUT");
  const persistedJob = (persistedRequest?.body as { jobs: Array<{ data: { title: string; logo: string } }> }).jobs[0].data;
  expect(persistedJob).toMatchObject({ title: "Backend Engineer", logo: "manual" });

  const analysisRequest = requests.find((request) => request.path === "/jobs/ai-match/run" && request.method === "POST");
  expect((analysisRequest?.body as { jobs: Array<{ data: { overview: string } }> }).jobs[0].data.overview).toContain("Python services");

  const locallyStoredJobs = JSON.parse(window.localStorage.getItem("tasko.importedJobs.v1") ?? "[]") as Array<{ title: string }>;
  expect(locallyStoredJobs.some((job) => job.title === "Backend Engineer")).toBe(true);
});

it("searches LinkedIn, Indeed, and jobs.ch together when all sources are selected", async () => {
  window.history.replaceState(null, "", "#jobs");
  const requests: Array<{ path: string; method: string }> = [];
  const requestUrls: string[] = [];
  const runBodies: Array<Record<string, unknown>> = [];
  let storedJobs: Array<{ id: string; data: unknown }> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl = typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";
    requests.push({ path: url.pathname, method });
    requestUrls.push(`${url.pathname}${url.search}`);

    if (url.pathname === "/job-search/configs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET") return Response.json(storedJobs);
    if (url.pathname === "/applications" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET") return Response.json([]);
    if (url.pathname === "/profile" && method === "GET") return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json({ has_brightdata_api_key: true, brightdata_api_key_preview: "test...key" });
    }
    if (url.pathname === "/job-search/run" && method === "POST") {
      runBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      const job = importedJobData({
        id: "indeed-example",
        title: "Junior Data Engineer",
        source: "indeed",
      });
      storedJobs = [{ id: job.id, data: job }];
      return Response.json({
        status: "completed",
        jobsFound: 1,
        jobsAdded: 1,
        sourceErrors: {},
        warning: null,
      });
    }
    if (url.pathname === "/jobs/ai-match/run" && method === "POST") {
      return Response.json({ detail: "AI match disabled in test" }, { status: 403 });
    }

    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  fireEvent.click(await screen.findByRole("button", { name: "Search vacancies" }));
  const linkedinSource = screen.getByRole("button", { name: /LinkedIn/ });
  const indeedSource = screen.getByRole("button", { name: /Indeed/ });
  const jobsChSource = screen.getByRole("button", { name: /jobs\.ch/ });
  expect(linkedinSource).toHaveAttribute("aria-pressed", "true");
  expect(indeedSource).toHaveAttribute("aria-pressed", "false");
  expect(jobsChSource).toHaveAttribute("aria-pressed", "false");

  fireEvent.click(indeedSource);
  fireEvent.click(jobsChSource);
  expect(linkedinSource).toHaveAttribute("aria-pressed", "true");
  expect(indeedSource).toHaveAttribute("aria-pressed", "true");
  expect(jobsChSource).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Start search" }));

  await waitFor(() => {
    expect(requests).toContainEqual({ path: "/job-search/run", method: "POST" });
  });
  expect(runBodies[0]).toMatchObject({
    sources: ["linkedin", "indeed", "jobs_ch"],
    aiAnalysisEnabled: true,
    config: {
      filters: {
        schemaVersion: 2,
        screening: {
          enabled: true,
          targetRoles: [],
        },
      },
    },
  });
  expect(runBodies[0]).toHaveProperty("config");
  expect(
    await screen.findByText(
      "Added 1 of 1 vacancies from LinkedIn + Indeed + jobs.ch",
    ),
  ).toBeInTheDocument();
  expect(
    requests.filter(
      (request) => request.path === "/jobs" && request.method === "GET",
    ).length,
  ).toBeGreaterThanOrEqual(2);
  expect(screen.getAllByRole("img", { name: "Data Engineering role · Indeed" })).toHaveLength(2);
  expect(screen.getAllByText("Source: Indeed")).toHaveLength(2);

  fireEvent.click(screen.getByRole("button", { name: "Analysis" }));
  const analysisMenu = screen.getByRole("menu", { name: "Bulk AI analysis" });
  expect(within(analysisMenu).getByRole("menuitem", { name: /Vacancies added in the last 24 hours/ })).toBeEnabled();
  fireEvent.click(within(analysisMenu).getByRole("menuitem", { name: /Vacancies without current analysis/ }));
  await waitFor(() => expect(requestUrls).toContain("/jobs/ai-match/run?force=true"));
});

it("does not re-add a vacancy whose deleted id was synchronized with the server", async () => {
  window.history.replaceState(null, "", "#jobs");
  const dismissedId = "linkedin-https-www-linkedin-com-jobs-view-123";
  window.localStorage.setItem("tasko.deletedJobIds.v1", JSON.stringify([dismissedId]));
  const requests: Array<{ path: string; method: string }> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl = typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";
    requests.push({ path: url.pathname, method });

    if (url.pathname === "/job-search/configs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs/dismissed-ids" && method === "PUT") {
      return Response.json([dismissedId]);
    }
    if (url.pathname === "/applications" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET") return Response.json([]);
    if (url.pathname === "/profile" && method === "GET") return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json({ has_brightdata_api_key: true, brightdata_api_key_preview: "test...key" });
    }
    if (url.pathname === "/job-search/run" && method === "POST") {
      return Response.json({
        status: "completed",
        jobsFound: 1,
        jobsAdded: 0,
        sourceErrors: {},
        warning: null,
      });
    }

    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  await waitFor(() => {
    expect(requests).toContainEqual({ path: "/jobs/dismissed-ids", method: "PUT" });
  });
  fireEvent.click(await screen.findByRole("button", { name: "Search vacancies" }));
  fireEvent.click(screen.getByRole("button", { name: "Start search" }));

  expect(
    await screen.findByText(
      "Found 1 vacancies; all were already saved or deleted",
    ),
  ).toBeInTheDocument();
  expect(requests).toContainEqual({ path: "/job-search/run", method: "POST" });
  expect(requests).not.toContainEqual({ path: "/jobs", method: "PUT" });
  expect(requests).not.toContainEqual({ path: "/jobs/ai-match/run", method: "POST" });
});

it("loads a server config and refreshes backend-persisted search results", async () => {
  window.history.replaceState(null, "", "#jobs");
  const runBodies: Array<Record<string, unknown>> = [];
  let storedJobs: Array<{ id: string; data: unknown }> = [];
  const entryItConfig = {
    id: "entry-it",
    name: "Entry IT",
    createdAt: "2026-07-21T00:00:00.000Z",
    updatedAt: "2026-07-21T00:00:00.000Z",
    filters: {
      schemaVersion: 2,
      search: {
        sources: ["linkedin"],
        keywords: "entry IT",
        location: "Zurich, Switzerland",
        remote: "Any",
        experienceLevel: "Any",
        jobType: "Any",
        datePosted: "Past 24 hours",
        resultsLimit: 50,
        country: "Switzerland",
        deduplicate: true,
        searchName: "Entry IT",
        folder: "",
      },
      screening: {
        enabled: true,
        targetRoles: ["entry IT"],
        excludedRoles: ["Cashier"],
        allowedSeniority: ["entry", "junior"],
        excludedSeniority: ["senior"],
        hardRules: [],
      },
    },
  };
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl = typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";

    if (url.pathname === "/job-search/configs" && method === "GET") {
      return Response.json([entryItConfig]);
    }
    if (url.pathname === "/jobs" && method === "GET") return Response.json(storedJobs);
    if (url.pathname === "/applications" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET") return Response.json([]);
    if (url.pathname === "/profile" && method === "GET") return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json({ has_brightdata_api_key: true, brightdata_api_key_preview: "test...key" });
    }
    if (url.pathname === "/job-search/run" && method === "POST") {
      runBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      const junior = importedJobData({
        id: "linkedin-junior-python",
        title: "Junior Python Developer",
      });
      const embedded = importedJobData({
        id: "linkedin-werkstudent-embedded",
        title: "Werkstudent Embedded-Software-Entwicklung",
      });
      storedJobs = [
        { id: junior.id, data: junior },
        { id: embedded.id, data: embedded },
      ];
      return Response.json({
        status: "completed",
        jobsFound: 2,
        jobsAdded: 2,
        sourceErrors: {},
        warning: null,
      });
    }

    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  fireEvent.click(await screen.findByRole("button", { name: "Search vacancies" }));
  fireEvent.change(await screen.findByLabelText("Existing configs"), { target: { value: "entry-it" } });
  fireEvent.click(screen.getByRole("button", { name: "Start search" }));

  expect(
    await screen.findByText("Added 2 of 2 vacancies from LinkedIn"),
  ).toBeInTheDocument();
  expect(runBodies[0]).toMatchObject({
    sources: ["linkedin"],
    configId: "entry-it",
  });
  expect(runBodies[0]).not.toHaveProperty("config");
  expect(screen.getAllByText("Junior Python Developer").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Werkstudent Embedded-Software-Entwicklung").length,
  ).toBeGreaterThan(0);
});

it("imports legacy local search configs to the server only once", async () => {
  window.history.replaceState(null, "", "#jobs");
  window.localStorage.setItem(
    "tasko.parserSearchConfigs.v2",
    JSON.stringify([
      {
        id: "legacy-zurich",
        name: "Legacy Zurich",
        updatedAt: "2026-07-20T09:00:00.000Z",
        form: {
          parsers: ["linkedin", "indeed"],
          keywords: "Platform Engineer",
          location: "Zurich",
          remote: "Any",
          experienceLevel: "Any",
          jobType: "Full-time",
          datePosted: "Past week",
          resultsLimit: "25",
          country: "Switzerland",
          deduplicate: true,
          searchName: "Legacy Zurich",
          folder: "",
        },
      },
    ]),
  );
  const configWrites: Array<Record<string, unknown>> = [];
  const serverConfigs: Array<Record<string, unknown>> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";

    if (url.pathname === "/job-search/configs" && method === "GET") {
      return Response.json(serverConfigs);
    }
    if (url.pathname === "/job-search/configs" && method === "POST") {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      configWrites.push(body);
      const saved = {
        id: "server-config-1",
        ...body,
        createdAt: "2026-07-23T10:00:00.000Z",
        updatedAt: "2026-07-23T10:00:00.000Z",
      };
      serverConfigs.push(saved);
      return Response.json(saved, { status: 201 });
    }
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs/dismissed-ids" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/applications" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/applications/events" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/profile" && method === "GET") return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json(configuredAppSettings);
    }
    if (
      (url.pathname === "/applications" ||
        url.pathname === "/applications/events") &&
      method === "PUT"
    ) {
      return Response.json([]);
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  const firstRender = render(<HomePage />);
  await waitFor(() => expect(configWrites).toHaveLength(1));
  expect(configWrites[0]).toMatchObject({
    name: "Legacy Zurich",
    filters: {
      schemaVersion: 2,
      search: {
        sources: ["linkedin", "indeed"],
        keywords: "Platform Engineer",
        location: "Zurich",
        resultsLimit: 25,
        deduplicate: true,
      },
      screening: {
        enabled: true,
        targetRoles: ["Platform Engineer"],
      },
    },
  });
  expect(
    window.localStorage.getItem("tasko.parserSearchConfigs.v2"),
  ).toBeNull();

  firstRender.unmount();
  render(<HomePage />);
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.filter(([input, init]) => {
        const requestUrl =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url;
        return (
          new URL(requestUrl, "http://localhost").pathname ===
            "/job-search/configs" &&
          (init?.method ?? "GET") === "GET"
        );
      }).length,
    ).toBeGreaterThanOrEqual(2);
  });
  expect(configWrites).toHaveLength(1);
});

it("saves and deletes manual-search configs through the API", async () => {
  window.history.replaceState(null, "", "#jobs");
  const configRequests: Array<{
    path: string;
    method: string;
    body?: Record<string, unknown>;
  }> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";

    if (url.pathname === "/job-search/configs" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/job-search/configs" && method === "POST") {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      configRequests.push({ path: url.pathname, method, body });
      return Response.json(
        {
          id: "manual-config-1",
          ...body,
          createdAt: "2026-07-23T10:00:00.000Z",
          updatedAt: "2026-07-23T10:00:00.000Z",
        },
        { status: 201 },
      );
    }
    if (
      url.pathname === "/job-search/configs/manual-config-1" &&
      method === "DELETE"
    ) {
      configRequests.push({ path: url.pathname, method });
      return new Response(null, { status: 204 });
    }
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs/dismissed-ids" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/applications" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/applications/events" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/profile" && method === "GET") return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json(configuredAppSettings);
    }
    if (
      (url.pathname === "/applications" ||
        url.pathname === "/applications/events") &&
      method === "PUT"
    ) {
      return Response.json([]);
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);
  fireEvent.click(await screen.findByRole("button", { name: "Search vacancies" }));
  fireEvent.change(
    screen.getByPlaceholderText("e.g. Product Designer Remote Jobs"),
    {
    target: { value: "Remote platform roles" },
    },
  );
  fireEvent.change(
    screen.getByPlaceholderText(
      "e.g. Product Designer, UX Designer, Design System",
    ),
    {
    target: { value: "Platform Engineer" },
    },
  );
  fireEvent.click(screen.getByRole("button", { name: "Save config" }));

  expect(
    await screen.findByText("Saved config: Remote platform roles"),
  ).toBeInTheDocument();
  expect(configRequests[0]).toMatchObject({
    path: "/job-search/configs",
    method: "POST",
    body: {
      name: "Remote platform roles",
      filters: {
        schemaVersion: 2,
        search: {
          keywords: "Platform Engineer",
          sources: ["linkedin"],
          resultsLimit: 10,
          deduplicate: true,
        },
        screening: {
          enabled: true,
          targetRoles: ["Platform Engineer"],
        },
      },
    },
  });

  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  expect(
    await screen.findByText("Deleted config: Remote platform roles"),
  ).toBeInTheDocument();
  expect(configRequests[1]).toEqual({
    path: "/job-search/configs/manual-config-1",
    method: "DELETE",
  });
  expect(
    window.localStorage.getItem("tasko.parserSearchConfigs.v2"),
  ).toBeNull();
});

it("shows seeded vacancies and calendar events only in demo mode", async () => {
  window.history.replaceState(null, "", "#jobs");
  installApplicationWorkspaceApiMock({
    requestHandler: async (url, method) => {
      if (url.pathname === "/job-search/configs" && method === "GET") return Response.json([]);
      if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
      if (url.pathname === "/jobs/dismissed-ids" && method === "GET") return Response.json([]);
      if (url.pathname === "/applications" && method === "GET") return Response.json([]);
      if (url.pathname === "/applications/events" && method === "GET") return Response.json([]);
      if (url.pathname === "/profile" && method === "GET") return Response.json({});
      if (url.pathname === "/settings" && method === "GET") return Response.json(configuredAppSettings);
      if ((url.pathname === "/applications" || url.pathname === "/applications/events") && method === "PUT") {
        return Response.json([]);
      }
      return undefined;
    },
  });

  vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "0");
  const regularMode = render(<HomePage />);

  expect(await screen.findByText("0 jobs found")).toBeInTheDocument();
  expect(screen.queryByText("Stripe")).not.toBeInTheDocument();
  expect(screen.queryByText("Figma")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("link", { name: "Calendar" }));
  expect(await screen.findByRole("heading", { name: "Calendar" })).toBeInTheDocument();
  expect(screen.queryByText("Technical Assessment")).not.toBeInTheDocument();
  expect(screen.queryByText("Future Wealth Group")).not.toBeInTheDocument();

  regularMode.unmount();
  window.history.replaceState(null, "", "#jobs");
  vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "1");
  render(<HomePage />);

  expect(await screen.findByText("2 jobs found")).toBeInTheDocument();
  expect(screen.getAllByText("Stripe").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Figma").length).toBeGreaterThan(0);

  fireEvent.click(screen.getByRole("link", { name: "Calendar" }));
  expect(await screen.findByRole("heading", { name: "Calendar" })).toBeInTheDocument();
  expect(screen.getAllByText("Technical Assessment").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Future Wealth Group").length).toBeGreaterThan(0);
});

it("keeps preparation drafts out of Applications until they are marked as applied", async () => {
  window.history.replaceState(null, "", "#jobs");
  vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "1");
  const savedApplicationStatuses: string[] = [];

  installApplicationWorkspaceApiMock({
    requestHandler: async (url, method, init) => {
      if (url.pathname === "/job-search/configs" && method === "GET") return Response.json([]);
      if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
      if (url.pathname === "/applications" && method === "GET") return Response.json([]);
      if (url.pathname === "/applications/events" && method === "GET") return Response.json([]);
      if (url.pathname === "/profile" && method === "GET") return Response.json({});
      if (url.pathname === "/settings" && method === "GET") {
        return Response.json({ has_brightdata_api_key: false, brightdata_api_key_preview: "" });
      }
      if (url.pathname === "/applications" && method === "PUT") {
        const payload = JSON.parse(String(init?.body)) as {
          applications: Array<{ data: { status: string } }>;
        };
        savedApplicationStatuses.push(...payload.applications.map((application) => application.data.status));
        return Response.json(payload.applications);
      }
      if (url.pathname === "/applications/events" && method === "PUT") return Response.json([]);
      return undefined;
    },
  });

  render(<HomePage />);

  fireEvent.click(await screen.findByRole("button", { name: "Prepare application" }));
  expect(await screen.findByText("Application prep")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "Jobs" })).toBeInTheDocument();
  await waitFor(() => expect(savedApplicationStatuses).toContain("draft"));

  fireEvent.click(screen.getByRole("button", { name: "Jobs" }));
  fireEvent.click(screen.getByRole("link", { name: "Applications" }));
  expect(await screen.findByText("No applications yet")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("link", { name: "Jobs" }));
  const continuePreparation = await screen.findByRole("button", { name: "Continue preparation" });
  fireEvent.click(continuePreparation);
  fireEvent.click(await screen.findByRole("button", { name: "Mark as applied" }));
  fireEvent.click(await screen.findByRole("button", { name: "Applications" }));

  expect(await screen.findByText("Applications (1)")).toBeInTheDocument();
  await waitFor(() => expect(savedApplicationStatuses).toContain("applied"));
});

it("offers decision-focused assistant questions on the Jobs page", async () => {
  window.history.replaceState(null, "", "#jobs");
  vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "1");
  const assistantRequests: Array<Record<string, unknown>> = [];
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
  installApplicationWorkspaceApiMock({
    aiPrivacySettings: {
      consentVersion: "2026-07-18.v2",
      consentBackend: "openclaw_codex",
      hasCurrentConsent: true,
    },
    requestHandler: async (url, method, init) => {
      if (url.pathname === "/job-search/configs" && method === "GET") return Response.json([]);
      if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
      if (url.pathname === "/applications" && method === "GET") return Response.json([]);
      if (url.pathname === "/applications/events" && method === "GET") return Response.json([]);
      if (url.pathname === "/profile" && method === "GET") return Response.json({});
      if (url.pathname === "/assistant/conversations" && method === "GET") {
        return Response.json([]);
      }
      if (url.pathname === "/assistant/chat/stream" && method === "POST") {
        assistantRequests.push(
          JSON.parse(String(init?.body)) as Record<string, unknown>,
        );
        return new Response(
          [
            "event: connected\ndata: {}",
            "event: delta\ndata: {\"text\":\"Why 92% explanation\",\"offset\":19}",
            "event: done\ndata: {\"metadata\":{\"backend\":\"openclaw_codex\"}}",
            "",
          ].join("\n\n"),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      }
      if (url.pathname === "/settings" && method === "GET") {
        return Response.json({
          has_brightdata_api_key: false,
          brightdata_api_key_preview: "",
        });
      }
      return undefined;
    },
  });

  render(<HomePage />);

  expect(
    await screen.findByRole("button", { name: "Why 92%?" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "What to know before applying" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Analyze" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Write cover letter" }),
  ).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Why 92%?" }));
  expect(await screen.findByText("Why 92% explanation")).toBeInTheDocument();
  expect(assistantRequests).toHaveLength(1);
  expect(assistantRequests[0]).toMatchObject({
    contextKind: "job",
    contextId: "stripe-senior-product-designer",
    job: {
      id: "stripe-senior-product-designer",
      title: "Senior Product Designer",
      match: 92,
      requirements: [
        "5+ years of product design experience",
        "Strong portfolio demonstrating design thinking",
        "Experience with design systems",
        "Excellent communication skills",
      ],
    },
  });
  expect(String(assistantRequests[0].message)).toContain("Why 92%?");
  expect(String(assistantRequests[0].message)).toContain(
    "How to improve the match",
  );
});
