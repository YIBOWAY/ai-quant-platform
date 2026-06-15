'use client';

import Link from "next/link";
import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { EmptyState } from "@/components/EmptyState";
import { Tabs } from "@/components/ui/Tabs";
import { Card, SectionTitle, StatusPill } from "@/components/ui/primitives";
import type { ExperimentDetailResponse, ExperimentSummary, PreviewRecord } from "@/lib/api";
import { providerFromExperimentSource } from "@/lib/experimentRunPayload";
import type { ExperimentStrategySummary } from "@/lib/experimentSummary";
import { summarizeExperimentStrategy } from "@/lib/experimentSummary";
import { useIsHydrated } from "@/lib/hydration";
import type { Locale } from "@/lib/locale";

const EMPTY_ROWS: PreviewRecord[] = [];

const copy = {
  en: {
    tabLabels: {
      sweep: "Sweep heatmap",
      folds: "Walk-forward folds",
      runs: "Run comparison",
      summary: "Agent summary",
    },
    noDetailTitle: "No experiment selected",
    noDetailDescription:
      "Create or select a local experiment to review sweep, folds, runs, and summary.",
    selectedExperiment: "Selected experiment",
    runs: "runs",
    folds: "folds",
    dataSource: "Data source",
    sendToBacktest: "Send to Backtest",
    strategyTitle: "Strategy under test",
    strategyDescription: "Fixed factor blend used for every sweep run.",
    strategyUnavailable: "No factor blend was found in this experiment config.",
    rebalanceEvery: "Rebalance",
    bars: "bars",
    factor: "Factor",
    weight: "Weight",
    direction: "Direction",
    totalAbsWeight: "Total abs. weight",
    higherIsBetter: "higher is better",
    lowerIsBetter: "lower is better",
    sweepUnavailableTitle: "Sweep heatmap unavailable",
    sweepUnavailableDescription: "This experiment does not include experiment_runs.parquet data.",
    sweepHeatmapTitle: "Sweep Heatmap",
    sweepHeatmapDescription: "Sharpe by lookback and top_n from the local parameter sweep.",
    sharpe: "Sharpe",
    foldsUnavailableTitle: "Walk-forward folds unavailable",
    foldsUnavailableDescription:
      "This experiment does not include walk_forward_folds.parquet data.",
    foldsTitle: "Walk-forward Folds",
    foldsDescription: "Validation windows and fold metrics for the selected experiment.",
    runsUnavailableTitle: "Run comparison unavailable",
    runsUnavailableDescription: "This experiment does not include run-level metric data.",
    runsTitle: "Run Comparison",
    runsDescription: "Runs sorted by Sharpe, with total return shown in the detail table.",
    summaryUnavailableTitle: "Agent summary unavailable",
    summaryUnavailableDescription:
      "agent_summary.json was not found in this experiment directory.",
    summaryTitle: "Agent Summary",
    summaryDescription:
      "Read-only agent summary for human review. It does not promote or deploy anything.",
    copyJson: "Copy JSON",
  },
  zh: {
    tabLabels: {
      sweep: "参数扫描热力图",
      folds: "滚动验证折",
      runs: "运行对比",
      summary: "代理摘要",
    },
    noDetailTitle: "未选择实验",
    noDetailDescription: "创建或选择一个本地实验以查看扫描、验证折、运行与摘要。",
    selectedExperiment: "已选实验",
    runs: "运行",
    folds: "验证折",
    dataSource: "数据源",
    sendToBacktest: "发送至回测",
    strategyTitle: "测试中的策略",
    strategyDescription: "每次参数扫描运行使用的固定因子组合。",
    strategyUnavailable: "此实验配置中未找到 factor_blend。",
    rebalanceEvery: "再平衡",
    bars: "根 bar",
    factor: "因子",
    weight: "权重",
    direction: "方向",
    totalAbsWeight: "绝对权重合计",
    higherIsBetter: "越高越好",
    lowerIsBetter: "越低越好",
    sweepUnavailableTitle: "参数扫描热力图不可用",
    sweepUnavailableDescription: "此实验不包含 experiment_runs.parquet 数据。",
    sweepHeatmapTitle: "参数扫描热力图",
    sweepHeatmapDescription: "来自本地参数扫描的 lookback 与 top_n 对应的 Sharpe。",
    sharpe: "Sharpe",
    foldsUnavailableTitle: "滚动验证折不可用",
    foldsUnavailableDescription: "此实验不包含 walk_forward_folds.parquet 数据。",
    foldsTitle: "滚动验证折",
    foldsDescription: "所选实验的验证窗口与折指标。",
    runsUnavailableTitle: "运行对比不可用",
    runsUnavailableDescription: "此实验不包含运行级指标数据。",
    runsTitle: "运行对比",
    runsDescription: "按 Sharpe 排序的运行，详情表中显示总回报。",
    summaryUnavailableTitle: "代理摘要不可用",
    summaryUnavailableDescription: "在此实验目录中未找到 agent_summary.json。",
    summaryTitle: "代理摘要",
    summaryDescription: "仅供人工查阅的只读代理摘要。它不会推广或部署任何内容。",
    copyJson: "复制 JSON",
  },
} as const;

type Copy = (typeof copy)[Locale];

type ExperimentTabsProps = {
  detail: ExperimentDetailResponse | null;
  experiment: ExperimentSummary | undefined;
  locale?: Locale;
};

export function ExperimentTabs({ detail, experiment, locale = "en" }: ExperimentTabsProps) {
  const text = copy[locale];
  // e2e (experiments-workbench.spec.ts) waits for data-experiment-tabs-ready="true"
  // before clicking tabs — only flip it once the client is interactive.
  const isHydrated = useIsHydrated();
  const runs = detail?.runs ?? EMPTY_ROWS;
  const folds = detail?.folds ?? EMPTY_ROWS;
  const config = detail?.experiment_config ?? {};
  const agentSummary = detail?.agent_summary ?? {};
  const bestRun = useMemo(
    () => findBestRun(runs, experiment?.best_run_id ?? stringValue(agentSummary.best_run_id)),
    [agentSummary.best_run_id, experiment?.best_run_id, runs],
  );
  const dataSource = experimentDataSource(agentSummary);
  const dataProvider = providerFromExperimentSource(dataSource);
  const backtestHref = buildBacktestHref(config, bestRun, dataSource);
  const strategySummary = summarizeExperimentStrategy(config);
  const dataSourceBadgeClass =
    dataProvider === "sample"
      ? "inline-flex items-center rounded-lg border border-warning/40 bg-warning/10 px-2 py-1 font-data-mono text-[10px] uppercase text-warning"
      : "inline-flex items-center rounded-lg border border-info/40 bg-info/10 px-2 py-1 font-data-mono text-[10px] uppercase text-info";

  if (!detail) {
    return (
      <EmptyState
        title={text.noDetailTitle}
        description={text.noDetailDescription}
      />
    );
  }

  const tabItems = [
    { id: "sweep", label: text.tabLabels.sweep, content: <SweepHeatmap runs={runs} text={text} /> },
    { id: "folds", label: text.tabLabels.folds, content: <WalkForwardFolds folds={folds} text={text} /> },
    {
      id: "runs",
      label: text.tabLabels.runs,
      content: <RunComparison runs={runs} bestRunId={stringValue(bestRun?.run_id)} text={text} />,
    },
    { id: "summary", label: text.tabLabels.summary, content: <AgentSummary summary={agentSummary} text={text} /> },
  ];

  return (
    <div className="flex flex-col gap-4" data-experiment-tabs-ready={isHydrated ? "true" : "false"}>
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="font-label-caps text-text-secondary">{text.selectedExperiment}</div>
            <h3 className="mt-1 break-all font-data-mono text-sm text-text-primary">{detail.id}</h3>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StatusPill label={text.runs} value={runs.length} />
              <StatusPill label={text.folds} value={folds.length} />
              <span className={dataSourceBadgeClass}>
                {text.dataSource}: {dataSource}
              </span>
            </div>
          </div>
          {bestRun ? (
            <Link
              className="shrink-0 rounded-lg bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary transition-opacity hover:opacity-90"
              href={backtestHref}
            >
              {text.sendToBacktest}
            </Link>
          ) : null}
        </div>
        <StrategySummaryTable locale={locale} summary={strategySummary} text={text} />
      </Card>

      <Tabs defaultId="sweep" items={tabItems} />
    </div>
  );
}

function StrategySummaryTable({
  locale,
  summary,
  text,
}: {
  locale: Locale;
  summary: ExperimentStrategySummary;
  text: Copy;
}) {
  const rebalanceValue = formatRebalanceInterval(summary.rebalanceEveryNBars, locale, text);

  return (
    <div className="mt-4 border-t border-border-subtle pt-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="font-label-caps text-text-secondary">{text.strategyTitle}</div>
          <p className="mt-1 font-body-sm text-text-secondary">{text.strategyDescription}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusPill label={text.rebalanceEvery} value={rebalanceValue} />
          <StatusPill label={text.totalAbsWeight} value={summary.totalAbsoluteWeight.toFixed(2)} />
        </div>
      </div>

      {summary.factors.length ? (
        <div className="mt-3 overflow-auto rounded-lg border border-border-subtle">
          <table className="w-full min-w-[28rem] border-collapse text-left">
            <thead>
              <tr className="border-b border-border-subtle bg-bg-surface-muted">
                <th className="px-3 py-2 font-label-caps text-text-secondary">{text.factor}</th>
                <th className="px-3 py-2 text-right font-label-caps text-text-secondary">{text.weight}</th>
                <th className="px-3 py-2 font-label-caps text-text-secondary">{text.direction}</th>
              </tr>
            </thead>
            <tbody className="font-data-mono text-xs text-text-primary">
              {summary.factors.map((factor) => (
                <tr className="border-b border-border-subtle/50 last:border-b-0" key={factor.factorId}>
                  <td className="px-3 py-2">{factor.factorId}</td>
                  <td className="px-3 py-2 text-right">{factor.weightLabel}</td>
                  <td className="px-3 py-2">{directionLabel(factor.direction, text)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mt-3 font-body-sm text-text-secondary">{text.strategyUnavailable}</p>
      )}
    </div>
  );
}

function directionLabel(direction: string, text: Copy) {
  if (direction === "higher_is_better") {
    return text.higherIsBetter;
  }
  if (direction === "lower_is_better") {
    return text.lowerIsBetter;
  }
  return direction.replaceAll("_", " ");
}

function formatRebalanceInterval(value: number | null, locale: Locale, text: Copy) {
  if (!value) {
    return "--";
  }
  if (locale === "zh") {
    return `每 ${value} ${text.bars}`;
  }
  return `every ${value} ${value === 1 ? "bar" : text.bars}`;
}

function SweepHeatmap({ runs, text }: { runs: PreviewRecord[]; text: Copy }) {
  if (!runs.length) {
    return (
      <EmptyState
        title={text.sweepUnavailableTitle}
        description={text.sweepUnavailableDescription}
      />
    );
  }

  const sharpeValues = runs.map((run) => numberValue(run.sharpe)).filter(isNumber);
  const minSharpe = Math.min(...sharpeValues);
  const maxSharpe = Math.max(...sharpeValues);
  const orderedRuns = [...runs].sort(
    (left, right) =>
      numberValue(left.lookback) - numberValue(right.lookback) ||
      numberValue(left.top_n) - numberValue(right.top_n),
  );

  return (
    <Card>
      <SectionTitle title={text.sweepHeatmapTitle} hint={text.sweepHeatmapDescription} />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {orderedRuns.map((run) => {
          const sharpe = numberValue(run.sharpe);
          const lookback = stringValue(run.lookback ?? "--");
          const topN = stringValue(run.top_n ?? "--");
          return (
            <div
              key={stringValue(run.run_id) || `${lookback}-${topN}`}
              className="rounded-lg border border-border-subtle p-3"
              style={{ backgroundColor: heatColor(sharpe, minSharpe, maxSharpe) }}
            >
              <div className="font-data-mono text-[11px] uppercase text-text-secondary">
                lookback={lookback} / top_n={topN}
              </div>
              <div className="mt-3 font-data-mono text-2xl font-semibold text-text-primary">
                {formatNumber(sharpe, 2)}
              </div>
              <div className="mt-1 font-label-caps text-text-secondary">{text.sharpe}</div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function WalkForwardFolds({ folds, text }: { folds: PreviewRecord[]; text: Copy }) {
  if (!folds.length) {
    return (
      <EmptyState
        title={text.foldsUnavailableTitle}
        description={text.foldsUnavailableDescription}
      />
    );
  }

  return (
    <Card>
      <SectionTitle title={text.foldsTitle} hint={text.foldsDescription} />
      <RecordTable
        columns={[
          "run_id",
          "fold_id",
          "train_start",
          "train_end",
          "validation_start",
          "validation_end",
          "sharpe",
          "total_return",
        ]}
        rows={folds}
      />
    </Card>
  );
}

function RunComparison({ runs, bestRunId, text }: { runs: PreviewRecord[]; bestRunId?: string; text: Copy }) {
  if (!runs.length) {
    return (
      <EmptyState
        title={text.runsUnavailableTitle}
        description={text.runsUnavailableDescription}
      />
    );
  }

  const chartRows = [...runs]
    .sort((left, right) => numberValue(right.sharpe) - numberValue(left.sharpe))
    .map((run) => ({
      run_id: stringValue(run.run_id),
      short_id: stringValue(run.run_id).replace(/^run-/, ""),
      sharpe: numberValue(run.sharpe),
      total_return: numberValue(run.total_return),
    }));

  return (
    <Card>
      <SectionTitle title={text.runsTitle} hint={text.runsDescription} />
      <div className="h-72 rounded-lg border border-border-subtle bg-bg-surface-muted p-3">
        <ResponsiveContainer height="100%" width="100%">
          <BarChart data={chartRows} margin={{ bottom: 36, left: 0, right: 8, top: 8 }}>
            <CartesianGrid stroke="#1F2937" strokeDasharray="3 3" />
            <XAxis
              angle={-24}
              dataKey="short_id"
              height={48}
              interval={0}
              stroke="#94A3B8"
              tick={{ fill: "#94A3B8", fontSize: 10 }}
              textAnchor="end"
            />
            <YAxis stroke="#94A3B8" tick={{ fill: "#94A3B8", fontSize: 10 }} />
            <Tooltip
              contentStyle={{ background: "#111827", border: "1px solid #1F2937" }}
              labelStyle={{ color: "#F1F5F9" }}
            />
            <Bar dataKey="sharpe" fill="#00C896" name="Sharpe" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <RecordTable
        columns={["run_id", "lookback", "top_n", "sharpe", "total_return", "max_drawdown", "turnover"]}
        highlightId={bestRunId}
        rows={runs}
      />
    </Card>
  );
}

function AgentSummary({ summary, text }: { summary: Record<string, unknown>; text: Copy }) {
  if (!Object.keys(summary).length) {
    return (
      <EmptyState
        title={text.summaryUnavailableTitle}
        description={text.summaryUnavailableDescription}
      />
    );
  }

  const notes = Array.isArray(summary.notes) ? summary.notes.map(String) : [];
  const json = JSON.stringify(summary, null, 2);

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <SectionTitle title={text.summaryTitle} hint={text.summaryDescription} />
        <button
          className="shrink-0 rounded-lg border border-border-subtle px-3 py-2 font-body-sm text-text-secondary transition-colors hover:bg-bg-surface-muted hover:text-text-primary"
          onClick={() => void navigator.clipboard?.writeText(json)}
          type="button"
        >
          {text.copyJson}
        </button>
      </div>
      {notes.length ? (
        <ul className="space-y-2">
          {notes.map((note) => (
            <li
              key={note}
              className="rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 font-body-sm text-text-primary"
            >
              {note}
            </li>
          ))}
        </ul>
      ) : null}
      <pre className="mt-4 max-h-96 overflow-auto rounded-lg border border-border-subtle bg-bg-surface-muted p-3 font-data-mono text-xs text-text-primary">
        {json}
      </pre>
    </Card>
  );
}

function RecordTable({
  columns,
  highlightId,
  rows,
}: {
  columns: string[];
  highlightId?: string;
  rows: PreviewRecord[];
}) {
  return (
    <div className="mt-4 overflow-auto rounded-lg border border-border-subtle">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-border-subtle bg-bg-surface-muted">
            {columns.map((column) => (
              <th key={column} className="px-3 py-2 font-label-caps text-text-secondary">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="font-data-mono text-xs text-text-primary">
          {rows.map((row, index) => {
            const runId = stringValue(row.run_id);
            const isBest = runId && runId === highlightId;
            return (
              <tr
                key={`${runId || "row"}-${index}`}
                className={`border-b border-border-subtle/50 ${isBest ? "bg-primary/10" : ""}`}
              >
                {columns.map((column) => (
                  <td key={`${runId}-${column}`} className="px-3 py-2 align-top">
                    <span className="block max-w-64 truncate" title={formatCell(row[column])}>
                      {formatCell(row[column])}
                    </span>
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function findBestRun(runs: PreviewRecord[], bestRunId?: string) {
  if (bestRunId) {
    const matched = runs.find((run) => stringValue(run.run_id) === bestRunId);
    if (matched) {
      return matched;
    }
  }
  return [...runs].sort((left, right) => numberValue(right.sharpe) - numberValue(left.sharpe))[0];
}

function buildBacktestHref(
  config: Record<string, unknown>,
  bestRun: PreviewRecord | undefined,
  dataSource: string,
) {
  const params = new URLSearchParams();
  const symbols = Array.isArray(config.symbols) ? config.symbols.map(String).join(",") : "SPY,QQQ";
  params.set("symbols", symbols);
  params.set("start", stringValue(config.start) || "2024-01-02");
  params.set("end", stringValue(config.end) || "2024-02-15");
  params.set("provider", providerFromExperimentSource(dataSource));
  params.set("lookback", stringValue(bestRun?.lookback ?? "5"));
  params.set("top_n", stringValue(bestRun?.top_n ?? "1"));
  params.set("initial_cash", stringValue(config.initial_cash ?? "100000"));
  params.set("commission_bps", stringValue(config.commission_bps ?? "1"));
  params.set("slippage_bps", stringValue(config.slippage_bps ?? "5"));
  return `/backtest?${params.toString()}`;
}

function experimentDataSource(summary: Record<string, unknown>) {
  const data = summary.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return "sample";
  }
  return stringValue((data as Record<string, unknown>).source) || "sample";
}

function heatColor(value: number, min: number, max: number) {
  if (!Number.isFinite(value) || !Number.isFinite(min) || !Number.isFinite(max)) {
    return "rgba(31, 41, 55, 0.55)";
  }
  const normalized = max === min ? 1 : (value - min) / (max - min);
  const alpha = 0.16 + normalized * 0.44;
  return `rgba(0, 200, 150, ${alpha.toFixed(2)})`;
}

function numberValue(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function isNumber(value: number) {
  return Number.isFinite(value);
}

function stringValue(value: unknown) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

function formatCell(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "--";
  }
  if (typeof value === "number") {
    if (Math.abs(value) < 1 && value !== 0) {
      return value.toFixed(4);
    }
    return value.toFixed(2);
  }
  return String(value);
}

function formatNumber(value: number, digits = 2) {
  return Number.isFinite(value) ? value.toFixed(digits) : "--";
}
