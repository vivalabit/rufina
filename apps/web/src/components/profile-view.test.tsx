import type { ComponentProps } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import {
  DocumentsPanel,
  ExperiencePanel,
  ProfileView,
} from "@/components/profile-view";
import { assistantPrompts } from "@/features/app-shell/model/assistant-prompts";
import { defaultCandidateProfile } from "@/features/profile/model/defaults";

vi.mock("@/components/master-resume-editor", () => ({
  ProfileResumeImport: () => <button>Import from resume</button>,
}));

vi.mock("@/components/resume-template-manager", () => ({
  ResumeTemplateManager: () => <div data-testid="resume-template-manager" />,
}));

function createProfileViewProps(
  overrides: Partial<ComponentProps<typeof ProfileView>> = {},
): ComponentProps<typeof ProfileView> {
  return {
    profile: defaultCandidateProfile,
    onOpenAssistant: vi.fn(),
    onEditProfile: vi.fn(),
    onAddExperience: vi.fn(),
    onEditExperience: vi.fn(),
    onDeleteExperience: vi.fn(),
    onAddEducation: vi.fn(),
    onEditEducation: vi.fn(),
    onDeleteEducation: vi.fn(),
    onAddDocument: vi.fn(),
    onEditDocument: vi.fn(),
    onDeleteDocument: vi.fn(),
    onEditPreferences: vi.fn(),
    onEditSkills: vi.fn(),
    onEditDealbreakers: vi.fn(),
    onEditAdditionalNotes: vi.fn(),
    ...overrides,
  };
}

it("composes the profile page and delegates its top-level actions", () => {
  const onOpenAssistant = vi.fn();
  const onEditProfile = vi.fn();

  render(
    <ProfileView
      {...createProfileViewProps({ onOpenAssistant, onEditProfile })}
    />,
  );

  expect(
    screen.getByRole("heading", { name: "My Profile" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Import from resume" })).toBeEnabled();
  expect(screen.queryByRole("heading", { name: "Profile resume" })).not.toBeInTheDocument();
  expect(screen.getByTestId("resume-template-manager")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Improve profile" }));
  expect(onOpenAssistant).toHaveBeenCalledWith(assistantPrompts.improveProfile);

  fireEvent.click(screen.getByRole("button", { name: "Edit Profile" }));
  expect(onEditProfile).toHaveBeenCalledOnce();
});

it("renders structured experience and delegates edit and delete without a resume file", () => {
  const experience = {
    id: "experience-1",
    title: "Backend Engineer",
    company: "Example AG",
    employment_type: "Full-time",
    location: "Zurich",
    start_date: "2024-01",
    end_date: "",
    is_current: true,
    description: "Built reliable APIs",
  };
  const onEditExperience = vi.fn();
  const onDeleteExperience = vi.fn();

  render(
    <ExperiencePanel
      profile={{
        ...defaultCandidateProfile,
        experience: JSON.stringify([experience]),
      }}
      onAddExperience={vi.fn()}
      onEditExperience={onEditExperience}
      onDeleteExperience={onDeleteExperience}
    />,
  );

  expect(screen.getByText("Backend Engineer")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Import from CV" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Edit experience" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete experience" }));

  expect(onEditExperience).toHaveBeenCalledWith(experience);
  expect(onDeleteExperience).toHaveBeenCalledWith("experience-1");
});

it("hides cover letters and delegates document actions", () => {
  const cv = {
    id: "document-cv",
    title: "English CV",
    category: "CV / Resume",
    language: "English",
    issuer: "",
    notes: "",
    file_name: "cv-en.docx",
    file_size: "40 KB",
    file_type:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    uploaded_at: "2026-08-29T10:00:00.000Z",
    download_url: "/profile/files/document-cv",
  };
  const coverLetter = {
    ...cv,
    id: "document-cover",
    title: "Legacy Cover Letter",
    category: "Cover Letter",
  };
  const onEditDocument = vi.fn();
  const onDeleteDocument = vi.fn();

  render(
    <DocumentsPanel
      profile={{
        ...defaultCandidateProfile,
        documents: JSON.stringify([cv, coverLetter]),
      }}
      onAddDocument={vi.fn()}
      onEditDocument={onEditDocument}
      onDeleteDocument={onDeleteDocument}
    />,
  );

  const card = screen.getByText("English CV").closest("article");
  expect(card).not.toBeNull();
  expect(screen.queryByText("Legacy Cover Letter")).not.toBeInTheDocument();

  fireEvent.click(within(card!).getByRole("button", { name: "Edit document" }));
  fireEvent.click(
    within(card!).getByRole("button", { name: "Delete document" }),
  );

  expect(onEditDocument).toHaveBeenCalledWith(cv);
  expect(onDeleteDocument).toHaveBeenCalledWith("document-cv");
});
