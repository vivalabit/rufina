import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { AppShell } from "@/components/app-shell";

it("keeps the sidebar and active view inside the application frame", () => {
  render(
    <AppShell sidebar={<header>Application navigation</header>}>
      <section>Current view</section>
    </AppShell>,
  );

  const main = screen.getByRole("main");
  const sidebar = screen.getByText("Application navigation");
  const view = screen.getByText("Current view");

  expect(main).toHaveClass(
    "h-screen",
    "overflow-hidden",
    "bg-background",
    "text-foreground",
  );
  expect(main.querySelector(".rufina-wash")).toBeInTheDocument();
  expect(sidebar.compareDocumentPosition(view)).toBe(
    Node.DOCUMENT_POSITION_FOLLOWING,
  );
});
