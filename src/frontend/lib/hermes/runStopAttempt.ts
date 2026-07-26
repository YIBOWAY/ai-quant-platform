import type { WorkspaceCommandProjection } from "./workspaceClient";

export type RunStopAttempt = Readonly<{
  runId: string;
  clientActionId: string;
}>;

export type StoppableHermesRun = Readonly<{
  commandId: string;
  runId: string;
  state: "delivered" | "outcome_unknown";
  updatedAt: string | null;
}>;

const STOPPABLE_COMMAND_STATES = new Set(["delivered", "outcome_unknown"]);
const EXACT_HERMES_RUN_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$/;

function exactHermesRunId(value: string | null | undefined): string | null {
  if (typeof value !== "string" || !EXACT_HERMES_RUN_ID.test(value)) {
    return null;
  }
  return value;
}

function commandRank(row: WorkspaceCommandProjection): readonly [number, string] {
  const timestamp = Date.parse(row.updated_at || row.created_at || "");
  return [
    Number.isFinite(timestamp) ? timestamp : 0,
    `${String(row.version).padStart(12, "0")}:${row.command_id}`,
  ];
}

function isNewerCommand(
  candidate: WorkspaceCommandProjection,
  current: WorkspaceCommandProjection,
): boolean {
  const candidateRank = commandRank(candidate);
  const currentRank = commandRank(current);
  return (
    candidateRank[0] > currentRank[0] ||
    (candidateRank[0] === currentRank[0] &&
      candidateRank[1] > currentRank[1])
  );
}

/**
 * Fail closed to the same durable active-Run states used by the backend:
 * delivered|outcome_unknown + exact hermes_run_id. The newest command fact
 * wins for a duplicated run id, so an older active row cannot outvote a newer
 * terminal row.
 */
export function selectStoppableHermesRuns(
  commands: WorkspaceCommandProjection[],
  mutationEnabled: boolean,
): StoppableHermesRun[] {
  if (!mutationEnabled) return [];

  const newestByRun = new Map<string, WorkspaceCommandProjection>();
  for (const row of commands) {
    const runId = exactHermesRunId(row.hermes_run_id);
    if (!runId) continue;
    const current = newestByRun.get(runId);
    if (!current || isNewerCommand(row, current)) {
      newestByRun.set(runId, row);
    }
  }

  return [...newestByRun.entries()]
    .filter(([, row]) => STOPPABLE_COMMAND_STATES.has(row.state))
    .map(([runId, row]) => ({
      commandId: row.command_id,
      runId,
      state: row.state as StoppableHermesRun["state"],
      updatedAt: row.updated_at || row.created_at || null,
    }))
    .sort((a, b) => {
      const byTime =
        Date.parse(b.updatedAt || "") - Date.parse(a.updatedAt || "");
      return Number.isFinite(byTime) && byTime !== 0
        ? byTime
        : b.commandId.localeCompare(a.commandId);
    });
}

/** The same logical Run always retains its first idempotency key on retry. */
export function ensureRunStopAttempt(
  existing: RunStopAttempt | null,
  runId: string,
  createId: () => string = () => crypto.randomUUID(),
): RunStopAttempt {
  if (existing?.runId === runId) {
    return existing;
  }
  return Object.freeze({
    runId,
    clientActionId: createId(),
  });
}

export function shouldRetainRunStopAttemptAfterError(error: unknown): boolean {
  if (!error || typeof error !== "object") return true;
  const status = (error as { status?: unknown }).status;
  if (typeof status !== "number") return true;
  return ![400, 401, 403, 409, 422].includes(status);
}
