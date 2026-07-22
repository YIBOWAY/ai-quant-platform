export type ComposerAttempt = Readonly<{
  prompt: string;
  clientActionId: string;
}>;

export function createComposerAttempt(
  prompt: string,
  createId: () => string = () => crypto.randomUUID(),
): ComposerAttempt {
  return Object.freeze({ prompt, clientActionId: createId() });
}

/** Retry is the same logical action, never a new submit gesture. */
export function retryComposerAttempt(attempt: ComposerAttempt): ComposerAttempt {
  return attempt;
}

/**
 * A transport/5xx failure can happen after the server accepted the action.
 * Keep the same logical identity unless the response is a definitive client
 * rejection that is unsafe or pointless to replay unchanged.
 */
export function shouldRetainComposerAttemptAfterError(error: unknown): boolean {
  if (!error || typeof error !== "object") return true;
  const status = (error as { status?: unknown }).status;
  if (typeof status !== "number") return true;
  return ![400, 401, 403, 409, 422].includes(status);
}
