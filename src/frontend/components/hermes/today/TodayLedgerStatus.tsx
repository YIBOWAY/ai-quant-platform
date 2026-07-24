'use client';

import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import type { Locale } from "@/lib/locale";

export type TodayLedgerStatusProps = {
  locale: Locale;
};

const OK_VALUES = new Set(["ready", "ok", "available", "healthy"]);

function dotClass(tone: "ok" | "warn" | "idle"): string {
  if (tone === "ok") return "bg-accent-success";
  if (tone === "warn") return "bg-warning";
  return "bg-text-secondary";
}

/**
 * UI-1 Direction A status-line ledger item. Client island: reads
 * authority_health.command_ledger from the shared follow spine when local
 * chat is on; renders nothing when chat is off (contract §2.4 allows omit).
 */
export function TodayLedgerStatus({ locale }: TodayLedgerStatusProps) {
  const copy = hermesWorkbenchCopy(locale).today.status;
  const { state } = useWorkspaceFollow();
  const value = state.authorityHealth?.command_ledger;
  const spineActive =
    state.transport !== "idle" || state.snapshotCursor != null;

  if (!spineActive && !value) {
    return null;
  }

  const normalized = (value ?? "").trim().toLowerCase();
  const tone = OK_VALUES.has(normalized) ? "ok" : !normalized ? "idle" : "warn";
  const label = OK_VALUES.has(normalized)
    ? copy.ledgerOk
    : !normalized
      ? copy.ledgerUnknown
      : copy.ledgerAttention;

  return (
    <span
      className="inline-flex items-center gap-1.5"
      data-hermes-status-item="ledger"
      data-hermes-ledger-status={normalized || "unknown"}
    >
      <span aria-hidden className={`inline-block h-[7px] w-[7px] rounded-full ${dotClass(tone)}`} />
      {copy.ledgerLabel} <span className="text-text-primary">{label}</span>
    </span>
  );
}
