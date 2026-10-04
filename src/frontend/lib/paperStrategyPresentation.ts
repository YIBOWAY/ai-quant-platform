import type {
  PaperStrategyOpsStatus,
  PaperStrategySleeveMode,
  PaperStrategySleeveResponse,
} from "./api";
import type { Locale } from "./locale";
import { factorDisplayName } from "./hermes/candidatePresentation";

export function isHistoricalStrategySleeve(sleeve: PaperStrategySleeveResponse): boolean {
  return sleeve.metadata?.fossil === true;
}

export function partitionStrategySleeves(sleeves: PaperStrategySleeveResponse[]) {
  const historical = sleeves.filter(isHistoricalStrategySleeve);
  const nonHistorical = sleeves.filter((sleeve) => !isHistoricalStrategySleeve(sleeve));
  const hasRemoteHangLineage = (sleeve: PaperStrategySleeveResponse) =>
    sleeve.metadata?.mandate_id === "remote-hang" &&
    typeof sleeve.metadata?.candidate_id === "string" &&
    sleeve.metadata.candidate_id.trim().length > 0;
  const pending = nonHistorical.filter(
    (sleeve) =>
      hasRemoteHangLineage(sleeve) &&
      (sleeve.metadata?.official_observation === false ||
        sleeve.metadata?.hang_activation_state === "book_binding_pending"),
  );
  const pendingIds = new Set(pending.map((sleeve) => sleeve.sleeve_id));
  const official = nonHistorical.filter(
    (sleeve) =>
      hasRemoteHangLineage(sleeve) &&
      sleeve.metadata?.official_observation !== false &&
      !pendingIds.has(sleeve.sleeve_id),
  );
  const officialIds = new Set(official.map((sleeve) => sleeve.sleeve_id));
  const manual = nonHistorical.filter(
    (sleeve) =>
      !pendingIds.has(sleeve.sleeve_id) && !officialIds.has(sleeve.sleeve_id),
  );
  return {
    official,
    pending,
    manual,
    historical,
    officialInitialCash: official.reduce(
      (total, sleeve) => total + sleeve.initial_allocated_cash,
      0,
    ),
    officialAvailableCash: official.reduce((total, sleeve) => total + sleeve.cash, 0),
  };
}

export function strategyOpsNeedsAttention(status: PaperStrategyOpsStatus | null): boolean {
  if (!status) return false;
  return (
    status.blocked_count > 0 ||
    status.recovery_required_count > 0 ||
    status.pending_sleeve_count > 0 ||
    status.pending_journal_count > 0 ||
    status.corrupt_journal_count > 0
  );
}

export function strategySleeveStatusLabel(
  status: PaperStrategySleeveResponse["status"],
  locale: Locale,
): string {
  const labels = {
    en: { running: "Running", paused: "Paused", stopped: "Stopped" },
    zh: { running: "运行中", paused: "已暂停", stopped: "已停止" },
  } as const;
  return labels[locale][status];
}

export function strategySleeveModeLabel(
  mode: PaperStrategySleeveMode,
  locale: Locale,
): string {
  const labels = {
    en: { allocated: "Allocated cash", signal_only: "Signal only" },
    zh: { allocated: "已划拨资金", signal_only: "仅记录信号" },
  } as const;
  return labels[locale][mode];
}

export function strategySleeveDisplayName(
  sleeve: PaperStrategySleeveResponse,
  factorId: string | null | undefined,
  fallback: string,
  locale: Locale,
): string {
  const stored = sleeve.metadata?.display_name_zh;
  if (locale === "zh" && typeof stored === "string" && stored.trim()) {
    return stored.trim();
  }
  return factorDisplayName(factorId, fallback, locale);
}

export function strategyConfigDisplayName(name: string, locale: Locale): string {
  return name.replace(
    /^挂上(?=\s*(?:·|$))/,
    locale === "zh" ? "模拟运行策略" : "Simulation strategy",
  );
}
