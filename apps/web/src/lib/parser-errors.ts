export function formatParserFailure(sourceLabel: string, error: string) {
  const normalizedError = error.trim().replace(/\s+/g, " ");
  return normalizedError ? `${sourceLabel} — ${normalizedError}` : sourceLabel;
}
