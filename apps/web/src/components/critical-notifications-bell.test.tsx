import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { CriticalNotificationsBell } from "@/components/critical-notifications-bell";

const notification = {
  id: "notice-1",
  severity: "critical",
  category: "parser_failure",
  source: "sbb",
  title: "SBB parser failed",
  description: "SBB returned HTTP 503",
  attempts: 3,
  runId: "run-1",
  createdAt: "2026-08-28T18:00:00Z",
};

it("shows persistent parser failure details in the critical notification bell", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json([notification])),
  );

  render(<CriticalNotificationsBell apiBaseUrl="http://localhost:8000" />);

  const bell = await screen.findByRole("button", {
    name: "Critical notifications (1)",
  });
  fireEvent.click(bell);

  expect(
    await screen.findByRole("dialog", { name: "Critical notifications" }),
  ).toBeInTheDocument();
  expect(screen.getByText("SBB parser failed")).toBeInTheDocument();
  expect(screen.getByText("Failed after 3 attempts")).toBeInTheDocument();
  expect(screen.getByText("SBB returned HTTP 503")).toBeInTheDocument();

  fireEvent.click(
    screen.getByRole("button", { name: "Close critical notifications" }),
  );
  expect(screen.queryByRole("dialog", { name: "Critical notifications" }))
    .not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Critical notifications (1)" }),
  ).toBeInTheDocument();
});

it("removes a critical notification only after explicit deletion", async () => {
  const requests: Array<{ path: string; method: string }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input)).pathname;
      const method = init?.method ?? "GET";
      requests.push({ path, method });
      if (method === "DELETE") return new Response(null, { status: 204 });
      return Response.json([notification]);
    }),
  );

  render(<CriticalNotificationsBell apiBaseUrl="http://localhost:8000" />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Critical notifications (1)" }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete SBB parser failed" }),
  );

  await waitFor(() => {
    expect(requests).toContainEqual({
      path: "/notifications/critical/notice-1",
      method: "DELETE",
    });
  });
  expect(screen.queryByText("SBB parser failed")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Critical notifications" }),
  ).toBeInTheDocument();
});
