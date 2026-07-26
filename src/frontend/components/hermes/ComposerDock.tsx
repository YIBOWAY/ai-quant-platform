'use client';

import { useRef, useState, type FormEvent } from "react";
import { MessageSquarePlus, RotateCcw, Send } from "lucide-react";

export type ComposerDockProps = {
  /**
   * Gates the textarea. Defaults non-interactive until local chat unlock.
   */
  disabled?: boolean;
  /**
   * Explicit submit unlock. Defaults to false and is ignored when disabled.
   */
  allowSubmit?: boolean;
  placeholder?: string;
  label?: string;
  sendLabel?: string;
  unavailableHint?: string;
  /**
   * Network submit handler. When omitted, form stays preventDefault-only
   * even if allowSubmit is true (safety for incomplete wiring).
   */
  onSubmitPrompt?: (prompt: string) => void | Promise<void>;
  /**
   * Optional status line under the dock (receipt / error / progress).
   */
  statusText?: string | null;
  /**
   * External busy flag (e.g. in-flight submit).
   */
  busy?: boolean;
  /** Explicit exact-id retry for an indeterminate prior attempt. */
  onRetry?: () => void | Promise<void>;
  retryLabel?: string;
  /** Explicitly create a new root Web-managed conversation. */
  onStartNewSession?: () => void | Promise<void>;
  newSessionLabel?: string;
};

/**
 * Hermes composer dock. Network submit only fires when allowSubmit is on,
 * disabled is off, onSubmitPrompt is provided, and the draft passes local checks.
 */
export function ComposerDock({
  disabled = true,
  allowSubmit = false,
  placeholder = "Describe a research task… (submit disabled)",
  label = "Hermes composer",
  sendLabel = "Send (disabled)",
  unavailableHint = "Submit unavailable in this slice",
  onSubmitPrompt,
  statusText = null,
  busy = false,
  onRetry,
  retryLabel = "Retry same send",
  onStartNewSession,
  newSessionLabel = "New conversation",
}: ComposerDockProps) {
  const [draft, setDraft] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const newSessionButtonRef = useRef<HTMLButtonElement | null>(null);

  const networkWired = typeof onSubmitPrompt === "function";
  const submitEnabled =
    !disabled && allowSubmit && networkWired && !busy && !submitting;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!submitEnabled || !onSubmitPrompt) {
      return;
    }
    const prompt = draft;
    setLocalError(null);
    setSubmitting(true);
    try {
      await onSubmitPrompt(prompt);
      setDraft("");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Submit failed";
      setLocalError(message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRetry() {
    if (!onRetry || busy || submitting) return;
    setLocalError(null);
    setSubmitting(true);
    try {
      await onRetry();
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "Retry failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleStartNewSession() {
    if (!onStartNewSession || busy || submitting) return;
    setLocalError(null);
    setSubmitting(true);
    try {
      await onStartNewSession();
    } catch (error) {
      setLocalError(
        error instanceof Error ? error.message : "New conversation failed",
      );
      window.requestAnimationFrame(() => {
        newSessionButtonRef.current?.focus();
      });
    } finally {
      setSubmitting(false);
    }
  }

  const hint = !allowSubmit || disabled
    ? statusText
      ? null
      : unavailableHint
    : !networkWired
      ? "Composer draft unlocked; network submit handler not wired."
      : null;

  const displayStatus = localError ?? statusText;

  return (
    <div className="border-t border-border-subtle bg-[var(--color-stream-surface)] p-3">
      <form
        className="mx-auto flex w-full max-w-[var(--spacing-hermes-content-max)] flex-col gap-2"
        onSubmit={handleSubmit}
      >
        {onStartNewSession ? (
          <div className="flex justify-end">
            <button
              aria-label={newSessionLabel}
              className="app-touch-target inline-flex items-center gap-1.5 rounded-md border border-border-subtle bg-bg-base px-2.5 py-1.5 font-body-sm text-text-primary transition-colors hover:bg-bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
              disabled={busy || submitting}
              onClick={() => void handleStartNewSession()}
              ref={newSessionButtonRef}
              type="button"
            >
              <MessageSquarePlus aria-hidden="true" size={15} />
              {newSessionLabel}
            </button>
          </div>
        ) : null}
        <div className="flex items-end gap-2">
          <label className="sr-only" htmlFor="hermes-composer-draft">
            {label}
          </label>
          <textarea
            id="hermes-composer-draft"
            aria-busy={busy || submitting || undefined}
            aria-disabled={disabled || undefined}
            aria-invalid={localError ? true : undefined}
            aria-label={label}
            className="app-touch-target min-h-[44px] max-h-32 min-w-0 flex-1 resize-y rounded-lg border border-border-subtle bg-bg-base px-3 py-2 font-body-sm text-text-primary placeholder:text-text-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:opacity-70 read-only:cursor-not-allowed read-only:opacity-70"
            disabled={disabled || busy || submitting}
            placeholder={placeholder}
            readOnly={disabled}
            rows={2}
            value={disabled ? "" : draft}
            onChange={(event) => {
              if (disabled) return;
              setDraft(event.target.value);
              if (localError) setLocalError(null);
            }}
          />
          <button
            aria-label={sendLabel}
            className="app-touch-target inline-flex shrink-0 items-center justify-center rounded-lg border border-border-subtle bg-info/10 text-info transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:border-border-subtle disabled:bg-bg-surface-muted disabled:text-text-secondary disabled:opacity-50 motion-reduce:transition-none"
            disabled={!submitEnabled}
            type="submit"
          >
            <Send size={16} className={submitEnabled ? "opacity-100" : "opacity-60"} />
          </button>
        </div>
        {hint ? (
          <p className="font-body-sm text-text-secondary">{hint}</p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <p
            aria-atomic="true"
            className={`font-body-sm ${localError ? "rounded-md bg-bg-base px-2 py-1 text-danger" : "text-text-secondary"}`}
            data-testid="hermes-composer-status"
            role="status"
          >
            {displayStatus ?? ""}
          </p>
          {onRetry ? (
            <button
              aria-label={retryLabel}
              className="app-touch-target inline-flex items-center gap-1 rounded-md border border-border-subtle bg-bg-surface-muted px-2 py-1 font-body-sm text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:opacity-50"
              disabled={busy || submitting}
              onClick={() => void handleRetry()}
              type="button"
            >
              <RotateCcw aria-hidden="true" size={14} />
              {retryLabel}
            </button>
          ) : null}
        </div>
      </form>
    </div>
  );
}
