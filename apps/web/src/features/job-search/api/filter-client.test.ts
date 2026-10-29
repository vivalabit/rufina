import { expect, it } from "vitest";

import { normalizeVacancyFilterSettings } from "./filter-client";

it("leaves the canton criterion off for older saved settings", () => {
  expect(normalizeVacancyFilterSettings({ enabled: true })).toMatchObject({
    enabled: true,
    cantonEnabled: false,
    allowedCantons: [],
  });
});

it("normalizes canton selections and drops invalid values", () => {
  expect(normalizeVacancyFilterSettings({
    cantonEnabled: true,
    allowedCantons: ["ZH", " ZG ", "ZH", "invalid", 42],
  })).toMatchObject({
    cantonEnabled: true,
    allowedCantons: ["ZH", "ZG"],
  });
});
