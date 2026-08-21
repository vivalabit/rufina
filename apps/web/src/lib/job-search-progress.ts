export type JobSearchProgressPhase =
  | "parsing"
  | "screening"
  | "matching"
  | "finalizing";

type JobSearchProgressRun = {
  jobsFound: number;
  jobsAlreadyKnown: number;
  jobsScreened: number;
  jobsAdded: number;
  jobsAnalyzed: number;
  completedAt?: string | null;
};

export function getJobSearchProgress(
  run: JobSearchProgressRun,
  parsersLabel: string,
  elapsedSeconds: number,
  autoAiMatchEnabled: boolean,
): {
  phase: JobSearchProgressPhase;
  message: string;
  screeningTotal: number;
} {
  const elapsed = `${Math.max(1, Math.floor(elapsedSeconds))}s elapsed`;
  const screeningTotal = Math.max(
    0,
    run.jobsFound - run.jobsAlreadyKnown,
  );

  if (run.jobsFound === 0) {
    return {
      phase: "parsing",
      message: `Waiting for ${parsersLabel} parser... (${elapsed})`,
      screeningTotal,
    };
  }
  if (run.jobsScreened < screeningTotal) {
    return {
      phase: "screening",
      message: `${parsersLabel}: screening ${run.jobsScreened} of ${screeningTotal} vacancies...`,
      screeningTotal,
    };
  }
  if (
    autoAiMatchEnabled &&
    run.jobsAdded > 0 &&
    run.completedAt == null
  ) {
    return {
      phase: "matching",
      message: `${parsersLabel}: AI Match ${run.jobsAnalyzed} of ${run.jobsAdded} vacancies...`,
      screeningTotal,
    };
  }
  return {
    phase: "finalizing",
    message: `${parsersLabel}: finalizing results...`,
    screeningTotal,
  };
}
