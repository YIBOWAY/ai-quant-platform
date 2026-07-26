export type ComposerAttempt = Readonly<{
  prompt: string;
  clientActionId: string;
}>;

export type SessionBoundComposerAttempt = Readonly<{
  attempt: ComposerAttempt;
  hermesSessionId: string;
}>;

export function createComposerAttempt(
  prompt: string,
  createId: () => string = () => crypto.randomUUID(),
): ComposerAttempt {
  return Object.freeze({ prompt, clientActionId: createId() });
}

/** A retry is the same logical action, never a second submit gesture. */
export function retryComposerAttempt(attempt: ComposerAttempt): ComposerAttempt {
  return attempt;
}

/**
 * A retry is only valid in the exact writable Hermes Session that accepted the
 * original logical action. Navigation must never retarget an old attempt.
 */
export function canRetryComposerAttempt(
  retry: SessionBoundComposerAttempt | null,
  activeHermesSessionId: string | null,
  sessionCanSubmit: boolean,
): retry is SessionBoundComposerAttempt {
  return Boolean(
    retry &&
      sessionCanSubmit &&
      activeHermesSessionId &&
      activeHermesSessionId === retry.hermesSessionId,
  );
}

/**
 * A transport or server failure can happen after durable acceptance. Preserve
 * the exact id and body unless the server definitively rejected the request.
 */
export function shouldRetainComposerAttemptAfterError(error: unknown): boolean {
  if (!error || typeof error !== "object") return true;
  const status = (error as { status?: unknown }).status;
  if (typeof status !== "number") return true;
  return ![400, 401, 403, 409, 422].includes(status);
}
