import { expect, it } from "vitest";

import { formatPreferenceSummary, normalizeJobPreferences, parseJobPreferences, serializeJobPreferences } from "./preferences";

it("normalizes preference lists and only retains Swiss permit detail when applicable", () => {
  expect(normalizeJobPreferences({
    desired_roles: [" Python Developer ", "python developer", ""],
    work_authorization: "Needs sponsorship",
    swiss_permit_status: "B permit",
  })).toMatchObject({ desired_roles: ["python developer"], swiss_permit_status: "" });
});

it("keeps the legacy preference fallback and omits an empty serialized profile field", () => {
  expect(parseJobPreferences("Remote\nZurich").notes).toBe("Remote\nZurich");
  expect(serializeJobPreferences(normalizeJobPreferences({}))).toBe("");
});

it("formats explicit no-preference values", () => {
  const summary = formatPreferenceSummary(normalizeJobPreferences({ no_preference: ["salary"] }));
  expect(summary).toContainEqual({ label: "Salary floor", values: ["No preference"] });
});
