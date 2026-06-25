import type { RecentRun } from "./api";
import { formatMoney, formatPercent } from "./api";

export type DashboardLocale = "en" | "zh";
export type DashboardRunIconKind = "backtest" | "factor" | "paper" | "replication";

function numberField(record: Record<string, unknown>, key: string) {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function metricField(run: RecentRun, key: string) {
  const metrics = run.summary.metrics;
  if (!metrics || typeof metrics !== "object" || Array.isArray(metrics)) {
    return undefined;
  }
  return numberField(metrics as Record<string, unknown>, key);
}

export function formatCount(value: number | undefined) {
  if (value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return new Intl.NumberFormat("en-US").format(value);
}

function backtestSummary(run: RecentRun) {
  const sharpe = metricField(run, "sharpe");
  return [
    `Sharpe ${sharpe === undefined ? "--" : sharpe.toFixed(2)}`,
    `Return ${formatPercent(metricField(run, "total_return"))}`,
    `Max DD ${formatPercent(metricField(run, "max_drawdown"))}`,
  ].join(" | ");
}

export function dashboardRunSummary(run: RecentRun) {
  if (run.kind === "backtest") {
    return backtestSummary(run);
  }
  if (run.kind === "factor") {
    return [
      `Rows ${formatCount(numberField(run.summary, "row_count"))}`,
      `Signals ${formatCount(numberField(run.summary, "signal_count"))}`,
    ].join(" | ");
  }
  if (run.kind === "replication") {
    const sharpe = metricField(run, "sharpe");
    return [
      `Sharpe ${sharpe === undefined ? "--" : sharpe.toFixed(2)}`,
      `Return ${formatPercent(metricField(run, "total_return"))}`,
      `Months ${formatCount(metricField(run, "observation_months"))}`,
    ].join(" | ");
  }
  return [
    `Equity ${formatMoney(numberField(run.summary, "final_equity"))}`,
    `Orders ${formatCount(numberField(run.summary, "order_count"))}`,
    `Breaches ${formatCount(numberField(run.summary, "risk_breach_count"))}`,
  ].join(" | ");
}

export function dashboardRunHref(run: RecentRun) {
  if (run.kind === "backtest") {
    return `/backtest/${run.run_id}`;
  }
  if (run.kind === "factor") {
    return `/factor-lab/${run.run_id}`;
  }
  if (run.kind === "replication") {
    return `/strategies/${run.run_id}`;
  }
  return `/paper-trading/${run.run_id}`;
}

export function dashboardRunKindLabel(run: RecentRun, locale: DashboardLocale) {
  if (run.kind === "backtest") {
    return locale === "zh" ? "回测" : "Backtest";
  }
  if (run.kind === "factor") {
    return locale === "zh" ? "运行因子分析" : "Run Factor Analysis";
  }
  if (run.kind === "replication") {
    return locale === "zh" ? "复现运行" : "Replication";
  }
  return locale === "zh" ? "模拟运行" : "Paper Run";
}

export function dashboardRunIconKind(run: RecentRun): DashboardRunIconKind {
  return run.kind;
}
