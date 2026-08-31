export const assistantPrompts = {
  whyMatch: (score: number) =>
    `Why ${score}%? Explain this rating using the selected vacancy and my verified profile: show what raises the score, what lowers it, and which requirements are missing or only partially supported. End with a prioritized "How to improve the match" section containing concrete actions I can take before applying. Separate resume/presentation improvements from genuinely missing experience or skills, and do not invent evidence.`,
  whyNoMatch:
    "Explain why this vacancy does not have a match score yet and what information or analysis is needed to assess it against my profile.",
  beforeApplying:
    "Tell me what I need to know before applying to this vacancy. Prioritize must-have requirements, hard constraints, missing or transferable evidence, likely recruiter concerns, facts I should verify, and a clear recommendation on whether and how to apply. Use only the vacancy and verified profile evidence.",
  followUpApplication: "Write a concise recruiter follow-up for this application based on its current status, next step, and notes.",
  prepareInterview: "Prepare me for an interview for this role with likely questions, answer guidance, verified evidence to use, and questions to ask.",
  improveProfile: "Review my candidate profile and give me a prioritized, evidence-based improvement plan. Identify missing or weak sections and rewrite my headline and summary without inventing facts.",
} as const;
