import { fireEvent, render, screen } from "@testing-library/react";
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

it("streams immediately", async () => {
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
    if (url.pathname === "/assistant/chat/stream" && method === "POST") {
      return new Response([
        "event: connected\ndata: {}",
        "event: delta\ndata: {\"text\":\"AI reply\",\"offset\":8}",
        "event: done\ndata: {\"metadata\":{\"backend\":\"openclaw_codex\"}}",
        "",
      ].join("\n\n"), { headers: { "Content-Type": "text/event-stream" } });
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

  await screen.findByText("No conversations yet");
  expect(screen.queryByText("Tailor my resume")).not.toBeInTheDocument();
  fireEvent.change(screen.getByPlaceholderText("Ask anything about your job search…"), {
    target: { value: "Review my profile" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));

  expect(await screen.findByText("AI reply")).toBeInTheDocument();
  expect(screen.queryByText("Save tailored resume")).not.toBeInTheDocument();
  expect(screen.getByText("Codex credits via OpenClaw")).toBeInTheDocument();
});

it("does not retry a dropped POST stream automatically", async () => {
  const streamBodies: Array<Record<string, unknown>> = [];
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
    if (url.pathname === "/assistant/chat/stream" && method === "POST") {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      streamBodies.push(body);
      return new Response(
        [
          'id: 0\nevent: connected\ndata: {"offset":0}',
          'id: 8\nevent: delta\ndata: {"text":"Partial ","offset":8}',
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
      jobs={[]}
      applications={[]}
      launch={null}
      onLaunchHandled={vi.fn()}
      onDocumentAttached={vi.fn()}
      onActionApplied={vi.fn()}
    />,
  );

  await screen.findByText("No conversations yet");
  fireEvent.change(
    screen.getByPlaceholderText("Ask anything about your job search…"),
    {
      target: { value: "Update my headline" },
    },
  );
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));

  expect(await screen.findByText("Partial")).toBeInTheDocument();
  expect(await screen.findByText("Assistant stream disconnected")).toBeInTheDocument();
  expect(streamBodies).toHaveLength(1);
  expect(streamBodies[0].offset).toBe(0);
});
