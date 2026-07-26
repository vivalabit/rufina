import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import {
  type ResumeTemplateDraft,
} from "@/components/resume-template-editor";
import { ResumeTemplatePreview } from "@/components/resume-template-preview";

const draft: ResumeTemplateDraft = {
  name: "Preview",
  baseTemplateId: "modern_single",
  designJson: {
    accentColor: "#176B87",
    fontFamily: "Inter",
    fontScale: 1,
    density: "standard",
    pageMargins: { top: 14, right: 14, bottom: 14, left: 14 },
    headingStyle: "accent-rule",
    skillsStyle: "pills",
    sidebarWidth: 0,
    sidebarSections: [],
  },
};

it("debounces draft changes and keeps the PDF as a browser Blob URL", async () => {
  const createObjectUrl = vi.fn(() => "blob:latest-resume-preview");
  const revokeObjectUrl = vi.fn();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: createObjectUrl,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: revokeObjectUrl,
  });

  const previewBodies: Array<Record<string, unknown>> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      previewBodies.push(
        JSON.parse(String(init?.body)) as Record<string, unknown>,
      );
      return new Response(
        new Blob(["validated-pdf"], { type: "application/pdf" }),
        { headers: { "Content-Type": "application/pdf" } },
      );
    }),
  );

  const { rerender, unmount } = render(
    <ResumeTemplatePreview
      apiBaseUrl="http://localhost:8000"
      draft={draft}
      debounceMs={20}
    />,
  );
  rerender(
    <ResumeTemplatePreview
      apiBaseUrl="http://localhost:8000"
      draft={{
        ...draft,
        designJson: { ...draft.designJson, accentColor: "#8A1538" },
      }}
      debounceMs={20}
    />,
  );

  const frame = await screen.findByTitle("Resume template preview");
  expect(frame).toHaveAttribute("src", "blob:latest-resume-preview");
  expect(previewBodies).toHaveLength(1);
  expect(previewBodies[0]).toMatchObject({
    baseTemplateId: "modern_single",
    designJson: { accentColor: "#8A1538" },
  });
  expect(createObjectUrl).toHaveBeenCalledOnce();

  unmount();
  await waitFor(() =>
    expect(revokeObjectUrl).toHaveBeenCalledWith(
      "blob:latest-resume-preview",
    ),
  );
});
