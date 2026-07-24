import type { ReactNode } from "react";

export type PaperEquityAvailabilityInput = {
  accountApiError?: string;
  curveApiError?: string;
  accountBlockedLabel: string;
  curveBlockedLabel: string;
};

export type PaperEquityAvailability = {
  unavailableReason: string | null;
  blockedReason: string | null;
};

/**
 * One truth gate for both the visible paper-equity figure and factual archive.
 * A fallback response may keep the page renderable, but it never becomes a
 * chart fact or an archive-authorizing value.
 */
export function resolvePaperEquityAvailability({
  accountApiError,
  curveApiError,
  accountBlockedLabel,
  curveBlockedLabel,
}: PaperEquityAvailabilityInput): PaperEquityAvailability {
  if (accountApiError) {
    return {
      unavailableReason: accountApiError,
      blockedReason: accountBlockedLabel,
    };
  }
  if (curveApiError) {
    return {
      unavailableReason: curveApiError,
      blockedReason: curveBlockedLabel,
    };
  }
  return { unavailableReason: null, blockedReason: null };
}

export function PaperEquityFigureState({
  children,
  unavailableLabel,
  unavailableReason,
}: {
  children?: ReactNode;
  unavailableLabel: string;
  unavailableReason: string | null;
}) {
  if (!unavailableReason) {
    return children;
  }

  return (
    <>
      <div
        className="flex min-h-[280px] items-center justify-center border border-editorial-rule bg-paper-surface px-6 text-center"
        data-brief-paper-equity-unavailable
        role="alert"
      >
        <div>
          <p className="font-editorial-body text-base text-ink">{unavailableLabel}</p>
          <p className="mt-2 font-data-mono text-xs text-ink-secondary">
            {unavailableReason}
          </p>
        </div>
      </div>
      <figcaption
        className="mt-2 text-center font-editorial-caps text-sm text-ink-secondary"
        data-brief-paper-equity-caption-unavailable
      >
        {unavailableLabel}
      </figcaption>
    </>
  );
}
