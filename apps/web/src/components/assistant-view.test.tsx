import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { AssistantView } from "@/components/assistant-view";

it("auto-sends a launched match explanation with the selected job context", async () => {
  const streamBodies: Array<Record<string, unknown>> = [];
  const onLaunchHandled = vi.fn();
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl);
    const method = init?.method ?? "GET";

    if (url.pathname === "/assistant/conversations" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/documents" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/privacy/ai-consent" && method === "GET") {
      return Response.json({
        providerName: "OpenAI via OpenClaw/Codex",
        currentBackend: "openclaw_codex",
        consentBackend: "openclaw_codex",
        currentConsentVersion: "privacy-v1",
        hasCurrentConsent: true,
        retentionDays: 30,
      });
    }
    if (url.pathname === "/assistant/chat/stream" && method === "POST") {
      streamBodies.push(
        JSON.parse(String(init?.body)) as Record<string, unknown>,
      );
      return new Response(
        [
          "event: connected\ndata: {}",
          "event: delta\ndata: {\"text\":\"Match explanation\",\"offset\":17}",
          "event: done\ndata: {\"metadata\":{\"backend\":\"openclaw_codex\"}}",
          "",
        ].join("\n\n"),
        { headers: { "Content-Type": "text/event-stream" } },
      );
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });

  render(
    <AssistantView
      profile={{
        name: "Alex Morgan",
        current_role: "Designer",
        desired_role: "Senior Designer",
        location: "Zurich",
        headline: "Product designer",
        skills: "Research",
        experience: "Six years",
        education: "BA Design",
        resume_file_name: "resume.docx",
      }}
      jobs={[
        {
          id: "job-73",
          title: "Product Designer",
          company: "Example AG",
          location: "Zurich",
          type: "Full-time",
          match: 73,
          overview: "Design enterprise workflows.",
          responsibilities: ["Lead product discovery"],
          requirements: ["Five years of product design experience"],
          skills: ["Research", "Prototyping"],
          aiMatch: {
            reasons: ["Verified research experience"],
            gaps: ["Enterprise portfolio evidence is missing"],
          },
        },
      ]}
      applications={[]}
      launch={{
        id: "launch-job-73",
        prompt:
          'Why 73%? Explain the rating and end with "How to improve the match".',
        contextKind: "job",
        contextId: "job-73",
        autoSubmit: true,
      }}
      onLaunchHandled={onLaunchHandled}
      onDocumentAttached={vi.fn()}
      onActionApplied={vi.fn()}
    />,
  );

  expect(await screen.findByText("Match explanation")).toBeInTheDocument();
  expect(onLaunchHandled).toHaveBeenCalledOnce();
  expect(streamBodies).toHaveLength(1);
  expect(streamBodies[0]).toMatchObject({
    message:
      'Why 73%? Explain the rating and end with "How to improve the match".',
    contextKind: "job",
    contextId: "job-73",
    job: {
      id: "job-73",
      title: "Product Designer",
      company: "Example AG",
      match: 73,
      requirements: ["Five years of product design experience"],
    },
  });
});

it("grants versioned server consent with a user TTL before streaming", async () => {
  const requests: Array<{ path: string; method: string; body?: unknown }> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl = typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
    const url = new URL(requestUrl);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) as unknown : undefined;
    requests.push({ path: url.pathname, method, body });

    if (url.pathname === "/assistant/conversations" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/documents" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/privacy/ai-consent" && method === "GET") {
      return Response.json({
        providerName: "OpenAI via OpenClaw/Codex",
        currentBackend: "openclaw_codex",
        consentBackend: null,
        currentConsentVersion: "privacy-v1",
        hasCurrentConsent: false,
        retentionDays: 30,
      });
    }
    if (url.pathname === "/privacy/ai-consent" && method === "PUT") {
      return Response.json({
        providerName: "OpenAI via OpenClaw/Codex",
        currentBackend: "openclaw_codex",
        consentBackend: "openclaw_codex",
        currentConsentVersion: "privacy-v1",
        hasCurrentConsent: true,
        retentionDays: (body as { retentionDays: number }).retentionDays,
      });
    }
    if (url.pathname === "/assistant/chat/stream" && method === "POST") {
      return new Response([
        "event: connected\ndata: {}",
        "event: delta\ndata: {\"text\":\"AI reply\",\"offset\":8}",
        "event: done\ndata: {\"metadata\":{\"backend\":\"openclaw_codex\"}}",
        "",
      ].join("\n\n"), { headers: { "Content-Type": "text/event-stream" } });
    }
    if (url.pathname === "/privacy/ai-consent" && method === "DELETE") {
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });

  render(
    <AssistantView
      profile={{
        name: "Alex Morgan",
        current_role: "Designer",
        desired_role: "Senior Designer",
        location: "Zurich",
        headline: "Product designer",
        skills: "Research",
        experience: "Six years",
        education: "BA Design",
        resume_file_name: "resume.docx",
      }}
      jobs={[]}
      applications={[]}
      launch={null}
      onLaunchHandled={vi.fn()}
      onDocumentAttached={vi.fn()}
      onActionApplied={vi.fn()}
    />,
  );

  await screen.findByText("AI consent required");
  expect(screen.queryByText("Tailor my resume")).not.toBeInTheDocument();
  fireEvent.change(screen.getByPlaceholderText("Ask anything about your job search…"), {
    target: { value: "Review my profile" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));

  expect(await screen.findByRole("dialog", { name: /Send selected context/ })).toBeInTheDocument();
  fireEvent.change(screen.getByRole("spinbutton", { name: /Keep AI results/ }), {
    target: { value: "7" },
  });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Continue to AI" }));

  expect(await screen.findByText("AI reply")).toBeInTheDocument();
  expect(screen.queryByText("Save tailored resume")).not.toBeInTheDocument();
  expect(screen.getByText("Codex credits via OpenClaw")).toBeInTheDocument();
  expect(requests.find((request) => request.path === "/privacy/ai-consent" && request.method === "PUT")?.body).toEqual({
    version: "privacy-v1",
    backend: "openclaw_codex",
    retentionDays: 7,
  });

  fireEvent.click(screen.getByRole("button", { name: "Revoke AI consent" }));
  await waitFor(() => {
    expect(requests.some((request) => request.path === "/privacy/ai-consent" && request.method === "DELETE")).toBe(true);
    expect(screen.getByText("AI consent required")).toBeInTheDocument();
  });
});

it("resumes a dropped SSE chat from its offset and requires action-preview confirmation", async () => {
  const streamBodies: Array<Record<string, unknown>> = [];
  const onActionApplied = vi.fn();
  let streamAttempt = 0;
  const action = {
    id: "assistant-action-headline",
    type: "update_profile_field",
    title: "Update profile field",
    description: "Change only the profile field headline.",
    contextKind: "profile",
    contextId: "",
    fields: [
      {
        label: "Headline",
        before: "Product designer",
        after: "Senior product designer",
      },
    ],
    payload: {
      field: "headline",
      value: "Senior product designer",
      expectedValue: "Product designer",
    },
    status: "preview",
    resultMessage: "",
  };
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl);
    const method = init?.method ?? "GET";

    if (url.pathname === "/assistant/conversations" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/documents" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/privacy/ai-consent" && method === "GET") {
      return Response.json({
        providerName: "OpenAI via OpenClaw/Codex",
        currentBackend: "openclaw_codex",
        consentBackend: "openclaw_codex",
        currentConsentVersion: "privacy-v1",
        hasCurrentConsent: true,
        retentionDays: 30,
      });
    }
    if (url.pathname === "/assistant/chat/stream" && method === "POST") {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      streamBodies.push(body);
      streamAttempt += 1;
      if (streamAttempt === 1) {
        return new Response(
          [
            'id: 0\nevent: connected\ndata: {"offset":0}',
            'id: 8\nevent: delta\ndata: {"text":"Partial ","offset":8}',
            "",
          ].join("\n\n"),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      }
      return new Response(
        [
          'id: 8\nevent: connected\ndata: {"offset":8}',
          'id: 15\nevent: delta\ndata: {"text":"answer.","offset":15}',
          `id: 15\nevent: done\ndata: ${JSON.stringify({
            offset: 15,
            metadata: { sessionKey: "session-resumed", actions: [action] },
          })}`,
          "",
        ].join("\n\n"),
        { headers: { "Content-Type": "text/event-stream" } },
      );
    }
    if (url.pathname === "/assistant/actions/apply" && method === "POST") {
      return Response.json({
        actionId: action.id,
        type: action.type,
        status: "applied",
        message: "Profile headline updated",
        resourceKind: "profile",
        resource: { headline: "Senior product designer" },
      });
    }
    if (
      url.pathname.startsWith("/assistant/conversations/") &&
      url.pathname.includes("/messages/") &&
      method === "PUT"
    ) {
      return Response.json({});
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });

  render(
    <AssistantView
      profile={{
        name: "Alex Morgan",
        current_role: "Designer",
        desired_role: "Senior Designer",
        location: "Zurich",
        headline: "Product designer",
        skills: "Research",
        experience: "Six years",
        education: "BA Design",
        resume_file_name: "resume.docx",
      }}
      jobs={[]}
      applications={[]}
      launch={null}
      onLaunchHandled={vi.fn()}
      onDocumentAttached={vi.fn()}
      onActionApplied={onActionApplied}
    />,
  );

  await screen.findByRole("button", { name: "Revoke AI consent" });
  fireEvent.change(
    screen.getByPlaceholderText("Ask anything about your job search…"),
    {
      target: { value: "Update my headline" },
    },
  );
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));

  expect(await screen.findByText("Partial answer.")).toBeInTheDocument();
  expect(streamBodies).toHaveLength(2);
  expect(streamBodies[0].offset).toBe(0);
  expect(streamBodies[1].offset).toBe(8);
  expect(streamBodies[1].requestId).toBe(streamBodies[0].requestId);
  expect(streamBodies[1].assistantMessageId).toBe(
    streamBodies[0].assistantMessageId,
  );

  expect(screen.getByText("Preview")).toBeInTheDocument();
  expect(screen.getByText("Senior product designer")).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Apply Update profile field" }),
  );

  expect(
    await screen.findByText("Profile headline updated"),
  ).toBeInTheDocument();
  expect(onActionApplied).toHaveBeenCalledWith(
    expect.objectContaining({
      actionId: action.id,
      status: "applied",
      resourceKind: "profile",
    }),
  );
});
