import assert from "node:assert/strict";
import test from "node:test";

import {
  isCandidateConfirmationComplete,
  isMeaningfulCandidateConfirmation,
} from "./candidate-confirmations.ts";

const questions = [
  { id: "production", requirement: "Production delivery", blocking: true },
  { id: "german", requirement: "German C1", blocking: true },
  { id: "leadership", requirement: "Leadership", blocking: false },
];

test("requires a substantive example for blocking yes and partial answers", () => {
  const shortYes = {
    questionId: "production",
    requirement: "Production delivery",
    response: "yes",
    exampleText: "yes",
    blocking: true,
    updatedAt: "",
  };
  const substantivePartial = {
    ...shortYes,
    response: "partial",
    exampleText: "Supported one production rollout with the platform team.",
  };

  assert.equal(isMeaningfulCandidateConfirmation(shortYes), false);
  assert.equal(isCandidateConfirmationComplete(questions[0], shortYes), false);
  assert.equal(isMeaningfulCandidateConfirmation(substantivePartial), true);
  assert.equal(isCandidateConfirmationComplete(questions[0], substantivePartial), true);
  assert.equal(
    isCandidateConfirmationComplete(questions[1], { ...shortYes, response: "no", exampleText: "" }),
    true,
  );
});
