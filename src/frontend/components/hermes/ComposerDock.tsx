'use client';

import { useState } from "react";
import { Send } from "lucide-react";

export type ComposerDockProps = {
  /**
   * Gates the textarea. Slice 8 keeps the composer non-interactive by default.
   * Submit stays forced off until a later slice wires allowSubmit.
   */
  disabled?: boolean;
  /**
   * Explicit submit unlock. Defaults to false and is ignored when disabled.
   * Slice 8 never enables network submit; leave this false.
   */
  allowSubmit?: boolean;
  placeholder?: string;
  label?: string;
  sendLabel?: string;
  unavailableHint?: string;
};

/**
 * Visual composer affordance for the Hermes workbench.
 * Slice 8 keeps submit disabled and never posts jobs/network requests.
 * Textarea can be marked disabled; submit remains forced-off unless a future
 * slice passes allowSubmit={true} with disabled={false}.
 */
export function ComposerDock({
  disabled = true,
  allowSubmit = false,
  placeholder = "Describe a research task… (submit disabled)",
  label = "Hermes composer",
  sendLabel = "Send (disabled)",
  unavailableHint = "Submit unavailable in this slice",
}: ComposerDockProps) {
  const [draft, setDraft] = useState("");
  // Slice 8 safety: submit never fires network; both flags must allow it.
  const submitEnabled = !disabled && allowSubmit;

  return (
    <div className="border-t border-border-subtle bg-[var(--color-stream-surface)] p-3">
      <form
        className="mx-auto flex w-full max-w-[var(--spacing-stream-max)] flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault();
        }}
      >
        <div className="flex items-end gap-2">
          <label className="sr-only" htmlFor="hermes-composer-draft">
            {label}
          </label>
          <textarea
            id="hermes-composer-draft"
            aria-disabled={disabled || undefined}
            className="min-h-[44px] max-h-32 flex-1 resize-y rounded-lg border border-border-subtle bg-bg-base px-3 py-2 font-body-sm text-text-primary placeholder:text-text-secondary focus:border-[var(--color-hermes)] focus:outline-none focus:ring-1 focus:ring-[var(--color-hermes)] disabled:cursor-not-allowed disabled:opacity-70 read-only:cursor-not-allowed read-only:opacity-70"
            disabled={disabled}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={placeholder}
            readOnly={disabled}
            rows={2}
            value={draft}
          />
          <button
            aria-label={sendLabel}
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-border-subtle bg-bg-surface-muted text-text-secondary transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!submitEnabled}
            type="submit"
          >
            <Send size={16} className="opacity-60" />
          </button>
        </div>
        {!submitEnabled ? (
          <p className="font-body-sm text-text-secondary" role="status">
            {unavailableHint}
          </p>
        ) : null}
      </form>
    </div>
  );
}
