import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";

import {
  ResumeTailoringProgressPanel,
  completedResumeTailoringProgress,
} from "@/components/resume-tailoring-progress";

it("shows exactly three AI stages and two separate PDF stages", () => {
  render(
    <ResumeTailoringProgressPanel
      progress={{
        stage: "experience_rewrite",
        status: "active",
        message: "Rewriting supported achievements",
        attempt: 1,
      }}
    />,
  );

  const aiStages = screen.getByRole("list", {
    name: "AI tailoring stages",
  });
  const pdfStages = screen.getByRole("list", {
    name: "PDF processing stages",
  });

  expect(within(aiStages).getAllByRole("listitem")).toHaveLength(3);
  expect(within(pdfStages).getAllByRole("listitem")).toHaveLength(2);
  expect(
    within(aiStages).getByRole("listitem", {
      name: "Recruiter analysis: completed",
    }),
  ).toBeInTheDocument();
  expect(
    within(aiStages).getByRole("listitem", {
      name: "Experience rewrite: in progress",
    }),
  ).toBeInTheDocument();
  expect(
    within(aiStages).getByRole("listitem", {
      name: "ATS final review: pending",
    }),
  ).toBeInTheDocument();
  expect(
    within(pdfStages).getByRole("listitem", {
      name: "Rendering PDF: pending",
    }),
  ).toBeInTheDocument();
  expect(
    within(pdfStages).getByRole("listitem", {
      name: "Validating PDF: pending",
    }),
  ).toBeInTheDocument();
  expect(screen.getByText("3 AI stages")).toBeInTheDocument();
});

it("keeps PDF validation separate from completed AI and rendering stages", () => {
  render(
    <ResumeTailoringProgressPanel
      progress={{
        stage: "validating_pdf",
        status: "failed",
        message: "PDF overflow detected",
        attempt: 2,
      }}
    />,
  );

  const aiStages = screen.getByRole("list", {
    name: "AI tailoring stages",
  });
  const pdfStages = screen.getByRole("list", {
    name: "PDF processing stages",
  });

  for (const label of [
    "Recruiter analysis",
    "Experience rewrite",
    "ATS final review",
  ]) {
    expect(
      within(aiStages).getByRole("listitem", {
        name: `${label}: completed`,
      }),
    ).toBeInTheDocument();
  }
  expect(
    within(pdfStages).getByRole("listitem", {
      name: "Rendering PDF: completed",
    }),
  ).toBeInTheDocument();
  expect(
    within(pdfStages).getByRole("listitem", {
      name: "Validating PDF: failed",
    }),
  ).toBeInTheDocument();
  expect(screen.getByText("attempt 2")).toBeInTheDocument();
});

it("marks all five stages complete after a successful pipeline", () => {
  render(
    <ResumeTailoringProgressPanel
      progress={completedResumeTailoringProgress(
        "PDF rendered, validated, and saved",
      )}
    />,
  );

  expect(
    screen.getAllByRole("listitem", { name: /completed$/ }),
  ).toHaveLength(5);
  expect(
    screen.getByText("PDF rendered, validated, and saved"),
  ).toBeInTheDocument();
});
