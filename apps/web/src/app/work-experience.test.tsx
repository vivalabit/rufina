import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it } from "vitest";

import HomePage from "@/app/page";
import { defaultCandidateProfile } from "@/features/profile/model/defaults";
import type { ExperienceEntry } from "@/shared/types/profile";
import { installApplicationWorkspaceApiMock } from "@/test/application-workspace-harness";

it("keeps detailed experience after a failed save, persists it and reloads it without changing a neighbor", async () => {
  window.history.replaceState(null, "", "#profile");
  const neighbor = { id: "job-b", title: "Engineer", company: "Beta", description: "Neighbor" };
  let stored = { ...defaultCandidateProfile, name: "Ada", experience: JSON.stringify([
    { id: "job-a", title: "Engineer", company: "Alpha", description: "Existing achievement" }, neighbor,
  ]) };
  let failSave = true;
  installApplicationWorkspaceApiMock({ currentMasterResume: null, requestHandler: (url, method, init) => {
    if (url.pathname === "/profile" && method === "GET") return Response.json(stored, { headers: { ETag: '"1"' } });
    if (url.pathname === "/profile" && method === "PUT") {
      if (failSave) return Response.json({ detail: "Save unavailable" }, { status: 500 });
      stored = JSON.parse(String(init?.body));
      return Response.json(stored, { headers: { ETag: '"2"' } });
    }
    if (url.pathname === "/settings") return Response.json({});
    if (["/jobs", "/jobs/state", "/applications", "/applications/events", "/profile/files", "/job-search/configs"].includes(url.pathname)) return Response.json([]);
  } });
  const page = render(<HomePage />);
  fireEvent.click((await screen.findAllByRole("button", { name: "Edit experience" }))[0]);
  fireEvent.click(screen.getByRole("button", { name: "Add technology" }));
  fireEvent.change(screen.getByLabelText("Technology"), { target: { value: "Python" } });
  fireEvent.change(screen.getByLabelText("Where it was used"), { target: { value: "Billing workers" } });
  fireEvent.click(screen.getByRole("button", { name: "Add technology" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove technology 2" }));
  fireEvent.click(screen.getByRole("button", { name: "Add responsibility" }));
  fireEvent.change(screen.getByLabelText("Area of responsibility"), { target: { value: "Payments" } });
  fireEvent.change(screen.getByLabelText("Decisions"), { target: { value: "Selected queues" } });
  fireEvent.click(screen.getByRole("button", { name: "Add project" }));
  for (const [label, value] of [["Project name", "Ledger"], ["Project description", "Reconciliation"], ["Project type", "Internal"],
    ["Team", "4 engineers"], ["Systems", "Billing API"], ["Users", "Finance"], ["Load / scale", "100k invoices/day"]]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("Save unavailable");
  expect(screen.getByLabelText("Where it was used")).toHaveValue("Billing workers");
  expect(screen.getByLabelText("Load / scale")).toHaveValue("100k invoices/day");
  failSave = false;
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.queryByRole("heading", { name: "Edit Experience" })).not.toBeInTheDocument());
  const saved = JSON.parse(stored.experience) as ExperienceEntry[];
  expect(saved[0].description).toBe("Existing achievement");
  expect(saved[0].stack).toEqual([expect.objectContaining({ id: expect.any(String), technology: "Python", context: "Billing workers" })]);
  expect(saved[0].responsibilities?.[0].decisions).toBe("Selected queues");
  expect(saved[0].projects?.[0].team).toBe("4 engineers");
  expect(saved[1]).toMatchObject(neighbor);
  page.unmount();
  render(<HomePage />);
  fireEvent.click((await screen.findAllByRole("button", { name: "Edit experience" }))[0]);
  expect(screen.getByLabelText("Project name")).toHaveValue("Ledger");
  expect(screen.getByLabelText("Decisions")).toHaveValue("Selected queues");
  fireEvent.change(screen.getByLabelText("Where it was used"), { target: { value: "Updated context" } });
  fireEvent.click(screen.getByRole("button", { name: "Remove responsibility 1" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove project 1" }));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.queryByRole("heading", { name: "Edit Experience" })).not.toBeInTheDocument());
  const edited = JSON.parse(stored.experience) as ExperienceEntry[];
  expect(edited[0].stack?.[0]).toMatchObject({ id: saved[0].stack?.[0].id, context: "Updated context" });
  expect(edited[0].projects).toEqual([]);
  expect(edited[0].responsibilities).toEqual([]);
  expect(edited[1]).toEqual(saved[1]);
});
