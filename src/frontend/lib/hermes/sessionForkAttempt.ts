export type SessionForkSelection = Readonly<{
  hermesSessionId: string;
  forkPoint: string;
}>;

export type SessionForkAttempt = Readonly<
  SessionForkSelection & {
    clientActionId: string;
  }
>;

/**
 * Return the existing immutable attempt for an unchanged selection. The
 * caller may retry transport/provision observation without minting a new
 * idempotency key or drifting to a different message cursor.
 */
export function ensureSessionForkAttempt(
  existing: SessionForkAttempt | null,
  selection: SessionForkSelection,
  createId: () => string = () => crypto.randomUUID(),
): SessionForkAttempt {
  if (
    existing?.hermesSessionId === selection.hermesSessionId &&
    existing.forkPoint === selection.forkPoint
  ) {
    return existing;
  }
  return Object.freeze({
    clientActionId: createId(),
    hermesSessionId: selection.hermesSessionId,
    forkPoint: selection.forkPoint,
  });
}
