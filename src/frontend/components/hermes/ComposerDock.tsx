'use client';

import { useRef, useState, type FormEvent } from "react";
import { MessageSquarePlus, RotateCcw, Send } from "lucide-react";

import {
  composerDraftState,
  composerErrorMessage,
} from "@/lib/hermes/composerPresentation";
import type { Locale } from "@/lib/locale";

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
  /** Locale for byte-count and local error presentation. */
  locale?: Locale;
  /** Incremented by the controller once the durable submit is accepted. */
  draftResetToken?: number;
};

/**
 * Hermes composer dock. Network submit only fires when allowSubmit is on,
 * disabled is off, onSubmitPrompt is provided, and the draft passes local checks.
 */
export function ComposerDock({
  draftResetToken,
  ...props
}: ComposerDockProps) {
  return (
    <ComposerDockStateful
      key={draftResetToken ?? "persistent-draft"}
      {...props}
    />
  );
}

function ComposerDockStateful({
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
  locale = "en",
}: ComposerDockProps) {
  const [draft, setDraft] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const newSessionButtonRef = useRef<HTMLButtonElement | null>(null);

  const networkWired = typeof onSubmitPrompt === "function";
  const draftState = composerDraftState(draft, locale);
  const submitEnabled =
    !disabled &&
    allowSubmit &&
    networkWired &&
    draftState.valid &&
    !busy &&
    !submitting;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!submitEnabled || !onSubmitPrompt || !draftState.valid) {
      return;
    }
    const prompt = draft;
    setLocalError(null);
    setSubmitting(true);
    try {
      await onSubmitPrompt(prompt);
      setDraft("");
    } catch (error) {
      setLocalError(composerErrorMessage(error, locale));
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
      setLocalError(composerErrorMessage(error, locale));
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
      setLocalError(composerErrorMessage(error, locale));
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
    <div className="bg-transparent px-4 pb-4 pt-2">
      <form
        className="mx-auto flex w-full max-w-[var(--spacing-chat-max)] flex-col gap-2"
        onSubmit={handleSubmit}
      >
        {onStartNewSession ? (
          <div className="flex justify-end">
            <button
              aria-label={newSessionLabel}
              className="app-touch-target inline-flex items-center gap-1.5 rounded-md px-2 font-body-sm text-text-secondary transition-colors hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
              disabled={busy || submitting}
              onClick={() => void handleStartNewSession()}
              ref={newSessionButtonRef}
              type="button"
            >
              <MessageSquarePlus aria-hidden="true" size={14} />
              {newSessionLabel}
            </button>
          </div>
        ) : null}
        <div className="rounded-[var(--radius-input)] border border-border-subtle bg-bg-surface p-2 shadow-[var(--shadow-composer)] transition-colors focus-within:border-[var(--color-hermes)]/50 motion-reduce:transition-none">
          <label className="sr-only" htmlFor="hermes-composer-draft">
            {label}
          </label>
          <textarea
            id="hermes-composer-draft"
            aria-describedby="hermes-composer-byte-count hermes-composer-status"
            aria-busy={busy || submitting || undefined}
            aria-disabled={disabled || undefined}
            aria-invalid={
              localError || draftState.overLimitBytes > 0 ? true : undefined
            }
            aria-label={label}
            className="app-touch-target block max-h-32 min-h-[44px] w-full resize-y border-none bg-transparent px-2 py-2 font-body-md text-text-primary placeholder:text-text-secondary focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:opacity-70 read-only:cursor-not-allowed read-only:opacity-70"
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
          <div className="flex items-center justify-end gap-2 px-1">
            <p
              className={`font-body-sm text-[11px] opacity-60 ${
                draftState.overLimitBytes > 0
                  ? "text-danger"
                  : "text-text-secondary"
              }`}
              data-testid="hermes-composer-byte-count"
              id="hermes-composer-byte-count"
            >
              {draftState.counterText}
            </p>
            <button
              aria-label={sendLabel}
              className="app-touch-target inline-flex shrink-0 items-center justify-center rounded-full bg-transparent text-text-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed"
              disabled={!submitEnabled}
              type="submit"
            >
              {/* 44px hit area (app-touch-target contract) around a 36px visual circle. */}
              <span
                className={`flex h-9 w-9 items-center justify-center rounded-full transition-colors motion-reduce:transition-none ${
                  submitEnabled
                    ? "bg-[var(--color-hermes)] text-white"
                    : "bg-bg-surface-muted text-text-secondary opacity-50"
                }`}
              >
                <Send size={16} />
              </span>
            </button>
          </div>
        </div>
        {hint ? (
          <p className="font-body-sm text-text-secondary">{hint}</p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <p
            aria-atomic="true"
            className={`font-body-sm ${localError ? "rounded-md bg-bg-base px-2 py-1 text-danger" : "text-text-secondary"}`}
            data-testid="hermes-composer-status"
            id="hermes-composer-status"
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
