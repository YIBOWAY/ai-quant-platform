export function isSampleSource(source?: string | null) {
  return (source ?? "").toLowerCase().includes("sample");
}

export function shouldIncludeSampleRuns(params: Record<string, string | string[] | undefined>) {
  const value = single(params.include_sample);
  return value === "1" || value === "true";
}

export function selectDisplayRun<T extends { source?: string | null }>(
  runs: T[],
  includeSample = false,
) {
  if (includeSample) {
    return runs[0];
  }
  return runs.find((run) => !isSampleSource(run.source));
}

function single(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}
