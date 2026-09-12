export const assistantPrompts = {
  beforeApplying:
    "Tell me what I need to know before applying to this vacancy. Prioritize must-have requirements, hard constraints, missing or transferable evidence, likely recruiter concerns, facts I should verify, and a clear recommendation on whether and how to apply. Use only the vacancy and verified profile evidence.",
  followUpApplication: "Write a concise recruiter follow-up for this application based on its current status, next step, and notes.",
  prepareInterview: "Prepare me for an interview for this role with likely questions, answer guidance, verified evidence to use, and questions to ask.",
  improveProfile: "Review my candidate profile and give me a prioritized, evidence-based improvement plan. Identify missing or weak sections and rewrite my headline and summary without inventing facts.",
} as const;
