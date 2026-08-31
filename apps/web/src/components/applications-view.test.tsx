import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { ApplicationsView } from "@/components/applications-view";
import { demoJobs } from "@/features/jobs/model/demo-jobs";
import { defaultCandidateProfile } from "@/features/profile/model/defaults";
import type {
  ApplicationDocument,
  TrackedApplication,
} from "@/shared/types/application";

const document: ApplicationDocument = {
  id: "document-1",
  sourceId: "source-1",
  kind: "uploaded",
  title: "Tailored resume",
  fileName: "resume.pdf",
  fileSize: "12 KB",
  fileType: "application/pdf",
  uploadedAt: "2026-08-20T08:00:00.000Z",
  downloadUrl: "/documents/resume.pdf",
};

const application: TrackedApplication = {
  id: "application-1",
  job: demoJobs[0],
  status: "applied",
  appliedAt: "2026-08-20T08:00:00.000Z",
  nextStep: "Recruiter screen",
  notes: "Initial note",
  documents: [document],
};

function renderApplicationsView(
  overrides: Partial<React.ComponentProps<typeof ApplicationsView>> = {},
) {
  const props: React.ComponentProps<typeof ApplicationsView> = {
    applications: [application],
    events: [],
    matchingApplicationIds: [],
    profile: defaultCandidateProfile,
    selectedApplication: application,
    onSelectApplication: vi.fn(),
    onOpenJobs: vi.fn(),
    onPrepareApplication: vi.fn(),
    onAddManualApplication: vi.fn().mockResolvedValue(undefined),
    onChangeStatus: vi.fn(),
    onChangeNotes: vi.fn(),
    onChangeDocuments: vi.fn(),
    onDeleteApplication: vi.fn(),
    onSaveEvent: vi.fn(),
    onDeleteEvent: vi.fn(),
    onUploadDocument: vi.fn().mockResolvedValue(document),
    onDeleteDocument: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };

  render(<ApplicationsView {...props} />);
  return props;
}

it("filters applications and preserves parent navigation callbacks", () => {
  const props = renderApplicationsView();

  expect(
    screen.getByRole("heading", { name: "Applications" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Prepare application" }));
  expect(props.onPrepareApplication).toHaveBeenCalledWith(application.id);

  fireEvent.change(
    screen.getByRole("searchbox", { name: "Search applications" }),
    { target: { value: "does-not-exist" } },
  );
  expect(
    screen.getByRole("heading", { name: "No applications found" }),
  ).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Clear all filters" }));
  expect(screen.getAllByText(application.job.title).length).toBeGreaterThan(0);
});

it("keeps notes and event drafts local and emits normalized saves", () => {
  const props = renderApplicationsView();

  fireEvent.click(screen.getByRole("button", { name: "Edit note" }));
  fireEvent.change(
    screen.getByPlaceholderText("Add notes about this application..."),
    { target: { value: "  Follow up Friday  " } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Save notes" }));
  expect(props.onChangeNotes).toHaveBeenCalledWith(
    application.id,
    "Follow up Friday",
  );

  fireEvent.click(screen.getByRole("button", { name: "Schedule" }));
  fireEvent.click(screen.getByRole("button", { name: "Save event" }));
  expect(props.onSaveEvent).toHaveBeenCalledWith(
    expect.objectContaining({
      applicationId: application.id,
      type: "screening",
      status: "scheduled",
      title: `${application.job.company} screening`,
    }),
  );
});

it("delegates attachment network I/O before updating document state", async () => {
  const uploadedDocument: ApplicationDocument = {
    ...document,
    id: "document-2",
    title: "Portfolio",
    fileName: "portfolio.pdf",
  };
  const onUploadDocument = vi.fn().mockResolvedValue(uploadedDocument);
  const onDeleteDocument = vi.fn().mockResolvedValue(undefined);
  const onChangeDocuments = vi.fn();
  renderApplicationsView({
    onUploadDocument,
    onDeleteDocument,
    onChangeDocuments,
  });

  const upload = new File(["portfolio"], "portfolio.pdf", {
    type: "application/pdf",
  });
  fireEvent.change(screen.getByLabelText("Add document"), {
    target: { files: [upload] },
  });

  await waitFor(() =>
    expect(onUploadDocument).toHaveBeenCalledWith(application.id, upload, {
      fileName: "portfolio.pdf",
      title: "portfolio",
    }),
  );
  expect(onChangeDocuments).toHaveBeenCalledWith(application.id, [
    document,
    uploadedDocument,
  ]);

  fireEvent.click(screen.getByRole("button", { name: "Delete resume.pdf" }));
  await waitFor(() =>
    expect(onDeleteDocument).toHaveBeenCalledWith(application.id, document),
  );
  expect(onChangeDocuments).toHaveBeenLastCalledWith(application.id, []);
});
