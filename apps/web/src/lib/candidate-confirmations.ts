export type CandidateConfirmationResponse = "yes" | "no" | "partial";

export type CandidateConfirmation = {
  questionId: string;
  requirement: string;
  response: CandidateConfirmationResponse;
  exampleText: string;
  blocking: boolean;
  updatedAt: string;
};

export type CandidateConfirmationQuestion = {
  id: string;
  requirement: string;
  blocking: boolean;
};

export function isMeaningfulCandidateConfirmation(
  confirmation: CandidateConfirmation | undefined,
) {
  if (!confirmation) return false;
  if (confirmation.response === "no") return true;

  const normalized = confirmation.exampleText.trim().replace(/\s+/g, " ");
  const words = normalized.split(" ").filter((word) => /[\p{L}\p{N}]/u.test(word));
  return normalized.length >= 10 && words.length >= 2;
}

export function isCandidateConfirmationComplete(
  question: CandidateConfirmationQuestion,
  confirmation: CandidateConfirmation | undefined,
) {
  if (!confirmation) return !question.blocking;
  return !question.blocking || isMeaningfulCandidateConfirmation(confirmation);
}
