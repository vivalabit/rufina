import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { ProfileEditorDialog } from "@/components/profile-editor-dialog";
import {
  DocumentEditorDialog,
  ExperienceEditorDialog,
} from "@/components/profile-entry-editor-dialogs";
import {
  AdditionalNotesEditorDialog,
  PreferencesEditorDialog,
  SkillsEditorDialog,
} from "@/components/profile-preference-editor-dialogs";
import {
  defaultCandidateProfile,
  defaultDocumentDraft,
  defaultExperienceDraft,
  defaultJobPreferences,
  defaultPreferenceInputs,
} from "@/features/profile/model/defaults";

it("keeps the main profile editor controlled and delegates save and close", () => {
  const onChange = vi.fn();
  const onClose = vi.fn();
  const onSave = vi.fn();

  render(
    <ProfileEditorDialog
      profile={{ ...defaultCandidateProfile, name: "Alex Morgan" }}
      avatarFile={null}
      useDefaultAvatar={false}
      status="idle"
      message=""
      onChange={onChange}
      onAvatarFileSelected={vi.fn()}
      onUseDefaultAvatar={vi.fn()}
      onClose={onClose}
      onSave={onSave}
    />,
  );

  fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
    target: { value: "Taylor Morgan" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  fireEvent.click(screen.getByRole("button", { name: "Close profile editor" }));

  expect(onChange).toHaveBeenCalledWith("name", "Taylor Morgan");
  expect(onSave).toHaveBeenCalledOnce();
  expect(onClose).toHaveBeenCalledOnce();
});

it("delegates structured experience changes without owning the draft", () => {
  const onChange = vi.fn();
  const onSave = vi.fn();

  render(
    <ExperienceEditorDialog
      experience={defaultExperienceDraft}
      isEditMode={false}
      status="idle"
      message=""
      onChange={onChange}
      onClose={vi.fn()}
      onSave={onSave}
    />,
  );

  expect(
    screen.getByRole("heading", { name: "Add Experience" }),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: "Role title" }), {
    target: { value: "Platform Engineer" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(onChange).toHaveBeenCalledWith("title", "Platform Engineer");
  expect(onSave).toHaveBeenCalledOnce();
});

it("offers the current supporting-document types and delegates file selection", () => {
  const onChange = vi.fn();
  const onAttachFile = vi.fn();

  render(
    <DocumentEditorDialog
      document={{ ...defaultDocumentDraft, category: "CV / Resume" }}
      isEditMode={false}
      status="idle"
      message=""
      onChange={onChange}
      onAttachFile={onAttachFile}
      onClose={vi.fn()}
      onSave={vi.fn()}
    />,
  );

  const typeSelect = screen.getByRole("combobox", { name: "Type" });
  expect(
    within(typeSelect).getByRole("option", { name: "CV / Resume" }),
  ).toBeInTheDocument();
  expect(
    within(typeSelect).queryByRole("option", { name: "Cover Letter" }),
  ).not.toBeInTheDocument();

  const file = new File(["resume"], "resume.docx", {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
  fireEvent.change(screen.getByLabelText("Attach file"), {
    target: { files: [file] },
  });

  expect(onAttachFile).toHaveBeenCalledWith(file);
});

it("delegates skill suggestions and preference no-preference choices", () => {
  const onAddSkill = vi.fn();
  const skillsRender = render(
    <SkillsEditorDialog
      skills={[]}
      skillInput="Python"
      status="idle"
      message=""
      onSkillInputChange={vi.fn()}
      onAddSkill={onAddSkill}
      onRemoveSkill={vi.fn()}
      onClose={vi.fn()}
      onSave={vi.fn()}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Python" }));
  expect(onAddSkill).toHaveBeenCalledWith("Python");
  skillsRender.unmount();

  const onSetAny = vi.fn();
  render(
    <PreferencesEditorDialog
      preferences={defaultJobPreferences}
      inputs={defaultPreferenceInputs}
      status="idle"
      message=""
      onChange={vi.fn()}
      onInputChange={vi.fn()}
      onAddListItem={vi.fn()}
      onRemoveListItem={vi.fn()}
      onToggleOption={vi.fn()}
      onSetAny={onSetAny}
      onClose={vi.fn()}
      onSave={vi.fn()}
    />,
  );

  const desiredRolesGroup = screen.getByText("Desired roles").closest("div");
  expect(desiredRolesGroup).not.toBeNull();
  fireEvent.click(
    within(desiredRolesGroup!).getByRole("button", { name: "No preference" }),
  );
  expect(onSetAny).toHaveBeenCalledWith("desired_roles");
});

it("keeps additional notes controlled and delegates clearing", () => {
  const onChange = vi.fn();
  const onClear = vi.fn();

  render(
    <AdditionalNotesEditorDialog
      notes="Available in October"
      status="idle"
      message=""
      onChange={onChange}
      onClear={onClear}
      onClose={vi.fn()}
      onSave={vi.fn()}
    />,
  );

  fireEvent.change(
    screen.getByPlaceholderText(
      "Availability, motivation, personal positioning, application context, or anything that does not fit elsewhere...",
    ),
    {
      target: { value: "Available in November" },
    },
  );
  fireEvent.click(screen.getByRole("button", { name: "Clear notes" }));

  expect(onChange).toHaveBeenCalledWith("Available in November");
  expect(onClear).toHaveBeenCalledOnce();
});
