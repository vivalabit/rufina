import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import {
  ApplicationAiInfoDialog,
  ApplicationEventDialog,
  ApplicationNotesDialog,
  ManualApplicationDialog,
} from "@/components/application-dialogs";
import { defaultManualApplicationDraft } from "@/features/applications/model/constants";
import type { ManualApplicationDraft } from "@/features/applications/model/types";
import { demoJobs } from "@/features/jobs/model/demo-jobs";
import { defaultCandidateProfile } from "@/features/profile/model/defaults";
import type {
  ApplicationEventDraft,
  TrackedApplication,
} from "@/shared/types/application";

const application: TrackedApplication = {
  id: "application-1",
  job: demoJobs[0],
  status: "applied",
  appliedAt: "2026-08-20T08:00:00.000Z",
  nextStep: "",
  notes: "Initial note",
  documents: [],
};

const completeManualDraft: ManualApplicationDraft = {
  ...defaultManualApplicationDraft,
  title: "Platform Engineer",
  company: "Acme",
  location: "Zurich",
  applyUrl: "https://example.com/jobs/1",
  overview: "Build and operate the platform.",
};

it("keeps the manual application form controlled and delegates resume selection", () => {
  const onChange = vi.fn();
  const onAttachResume = vi.fn();
  const onSave = vi.fn();

  render(
    <ManualApplicationDialog
      draft={completeManualDraft}
      profile={{
        ...defaultCandidateProfile,
        resume_file_id: "resume-1",
        resume_file_name: "resume.pdf",
      }}
      isSaving={false}
      error=""
      onChange={onChange}
      onUseProfileResume={vi.fn()}
      onAttachResume={onAttachResume}
      onClose={vi.fn()}
      onSave={onSave}
    />,
  );

  fireEvent.change(screen.getByPlaceholderText("Company name"), {
    target: { value: "New Company" },
  });
  expect(onChange).toHaveBeenCalledWith("company", "New Company");

  const resume = new File(["resume"], "resume.pdf", {
    type: "application/pdf",
  });
  fireEvent.change(screen.getByLabelText("Upload another"), {
    target: { files: [resume] },
  });
  expect(onAttachResume).toHaveBeenCalledWith(resume);

  fireEvent.click(screen.getByRole("button", { name: "Save application" }));
  expect(onSave).toHaveBeenCalledOnce();
});

it("delegates notes and event edits without owning application state", () => {
  const onNotesChange = vi.fn();
  const onNotesSave = vi.fn();
  const notesRender = render(
    <ApplicationNotesDialog
      application={application}
      notes="Initial note"
      onChange={onNotesChange}
      onClear={vi.fn()}
      onClose={vi.fn()}
      onSave={onNotesSave}
    />,
  );

  fireEvent.change(
    screen.getByPlaceholderText("Add notes about this application..."),
    { target: { value: "Follow up tomorrow" } },
  );
  expect(onNotesChange).toHaveBeenCalledWith("Follow up tomorrow");
  fireEvent.click(screen.getByRole("button", { name: "Save notes" }));
  expect(onNotesSave).toHaveBeenCalledOnce();
  notesRender.unmount();

  const draft: ApplicationEventDraft = {
    type: "interview",
    status: "scheduled",
    outcome: "",
    title: "Technical interview",
    startsAt: "2026-09-05T10:00",
    durationMinutes: "60",
    timezone: "Europe/Zurich",
    location: "Meet",
    notes: "",
  };
  const onEventChange = vi.fn();
  const onEventSave = vi.fn();

  render(
    <ApplicationEventDialog
      application={application}
      draft={draft}
      onChange={onEventChange}
      onClose={vi.fn()}
      onSave={onEventSave}
    />,
  );

  expect(screen.getByRole("combobox", { name: "Outcome" })).toBeDisabled();
  fireEvent.change(screen.getByRole("combobox", { name: "Status" }), {
    target: { value: "completed" },
  });
  expect(onEventChange).toHaveBeenCalledWith("status", "completed");
  fireEvent.click(screen.getByRole("button", { name: "Save event" }));
  expect(onEventSave).toHaveBeenCalledOnce();
});

it("renders the AI application information state", () => {
  render(
    <ApplicationAiInfoDialog
      application={application}
      isAnalyzing
      onClose={vi.fn()}
    />,
  );

  expect(
    screen.getByRole("heading", { name: "AI application info" }),
  ).toBeInTheDocument();
  expect(screen.getAllByText("Analyzing...").length).toBeGreaterThan(0);
  expect(screen.getByText(/AI analysis is running/)).toBeInTheDocument();
});
