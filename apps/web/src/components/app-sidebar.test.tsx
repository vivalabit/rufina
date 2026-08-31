import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { AppSidebar } from "@/components/app-sidebar";
import { defaultCandidateProfile } from "@/features/profile/model/defaults";

vi.mock("@/components/critical-notifications-bell", () => ({
  CriticalNotificationsBell: ({ apiBaseUrl }: { apiBaseUrl: string }) => (
    <button type="button" data-api-base-url={apiBaseUrl}>
      Critical notifications
    </button>
  ),
}));

it("shows optional logs and treats the application workspace as Applications", () => {
  const onChangeView = vi.fn();

  render(
    <AppSidebar
      activeView="ApplicationWorkspace"
      onChangeView={onChangeView}
      profile={defaultCandidateProfile}
      showLogs
    />,
  );

  expect(screen.getByRole("link", { name: "Logs" })).toHaveAttribute(
    "href",
    "#logs",
  );
  expect(screen.getByRole("link", { name: "Applications" })).toHaveClass(
    "text-accent",
    "after:scale-x-100",
  );
  expect(screen.getByRole("button", { name: "Critical notifications" })).toHaveAttribute(
    "data-api-base-url",
    expect.stringContaining("http"),
  );

  fireEvent.click(screen.getByRole("link", { name: "Jobs" }));
  expect(onChangeView).toHaveBeenCalledWith("Jobs");
});

it("hides logs and delegates profile and settings navigation", () => {
  const onChangeView = vi.fn();

  render(
    <AppSidebar
      activeView="Dashboard"
      onChangeView={onChangeView}
      profile={{
        ...defaultCandidateProfile,
        name: "",
        current_role: "",
        avatar_url: "",
      }}
      showLogs={false}
    />,
  );

  expect(screen.queryByRole("link", { name: "Logs" })).not.toBeInTheDocument();
  expect(screen.getByText("Set up profile")).toBeInTheDocument();
  expect(screen.getByText("Add your role")).toBeInTheDocument();

  fireEvent.click(screen.getByText("Set up profile").closest("a")!);
  fireEvent.click(screen.getByRole("link", { name: "Settings" }));

  expect(onChangeView).toHaveBeenNthCalledWith(1, "Profile");
  expect(onChangeView).toHaveBeenNthCalledWith(2, "Settings");
  expect(screen.getByRole("link", { name: "Source code" })).toHaveAttribute(
    "target",
    "_blank",
  );
});
