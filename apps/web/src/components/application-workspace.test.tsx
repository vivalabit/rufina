import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  createV3WorkspaceApplication,
  renderApplicationWorkspace,
} from "@/test/application-workspace-harness";

describe("ApplicationWorkspace", () => {
  it("shows an empty state when no application is selected", () => {
    const { props } = renderApplicationWorkspace(null);

    expect(
      screen.getByRole("heading", { name: "No application selected" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Applications" }));
    expect(props.onBack).toHaveBeenCalledOnce();
  });

  it("renders a compact vacancy card with the application status", () => {
    renderApplicationWorkspace(
      createV3WorkspaceApplication({ status: "interview" }),
    );

    expect(
      screen.getByRole("heading", { name: "Senior Product Designer" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Acme Labs")).toBeInTheDocument();
    expect(screen.getByText("Zurich, Switzerland")).toBeInTheDocument();
    expect(screen.getByText("Full-time")).toBeInTheDocument();
    expect(screen.getByText("Interview")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Lead product discovery and delivery for a growing B2B platform.",
      ),
    ).toBeInTheDocument();
  });

  it("normalizes jobs.ch vacancy links", () => {
    renderApplicationWorkspace(
      createV3WorkspaceApplication({
        job: {
          applyUrl:
            "https://www.jobs.ch/en/vacancies/detail/de866122-37da-4c9d-ad34-c2fa0bc45d5f/apply/",
        },
      }),
    );

    expect(screen.getByRole("link", { name: "View vacancy" })).toHaveAttribute(
      "href",
      "https://www.jobs.ch/en/vacancies/detail/de866122-37da-4c9d-ad34-c2fa0bc45d5f/",
    );
  });

  it("lists existing application documents without generation actions", () => {
    renderApplicationWorkspace(
      createV3WorkspaceApplication({
        documents: [
          {
            id: "document-1",
            title: "Tailored CV",
            fileName: "alex-morgan-cv.pdf",
            fileSize: "128 KB",
            fileType: "application/pdf",
            uploadedAt: "2026-07-25T10:00:00.000Z",
            downloadUrl: "/documents/document-1/download",
          },
          {
            id: "document-2",
            title: "Cover letter",
            fileName: "alex-morgan-letter.docx",
            fileSize: "64 KB",
            fileType:
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            uploadedAt: "2026-07-26T10:00:00.000Z",
            downloadUrl: "/documents/document-2/download",
          },
        ],
      }),
    );

    const documents = screen.getByRole("region", {
      name: "Existing documents",
    });

    expect(within(documents).getByText("Tailored CV")).toBeInTheDocument();
    expect(within(documents).getByText("Cover letter")).toBeInTheDocument();
    expect(
      within(documents).getByRole("link", { name: "Download Tailored CV" }),
    ).toHaveAttribute("href", "/documents/document-1/download");
    expect(
      within(documents).getByRole("link", { name: "Download Cover letter" }),
    ).toHaveAttribute("href", "/documents/document-2/download");
    expect(
      screen.queryByRole("button", { name: /Generate|Create CV|Create letter/ }),
    ).not.toBeInTheDocument();
  });

  it("does not render any legacy preparation content", () => {
    renderApplicationWorkspace(createV3WorkspaceApplication());

    expect(screen.queryByText("Your application angle")).not.toBeInTheDocument();
    expect(screen.queryByText("Required confirmations")).not.toBeInTheDocument();
    expect(screen.queryByText("CV direction")).not.toBeInTheDocument();
    expect(screen.queryByText("Cover letter direction")).not.toBeInTheDocument();
    expect(screen.queryByText("CV generation mode")).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "Turn complex B2B workflows into clear, validated product experiences.",
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "Do not imply unverified people-management experience",
      ),
    ).not.toBeInTheDocument();
  });
});
