'use client';

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
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
import type { ExperimentDetailResponse, ExperimentSummary, PreviewRecord } from "@/lib/api";

const TABS = [
  { id: "sweep", label: "Sweep heatmap", heading: "Sweep Heatmap" },
  { id: "folds", label: "Walk-forward folds", heading: "Walk-forward Folds" },
  { id: "runs", label: "Run comparison", heading: "Run Comparison" },
  { id: "summary", label: "Agent summary", heading: "Agent Summary" },
] as const;
const EMPTY_ROWS: PreviewRecord[] = [];

type TabId = (typeof TABS)[number]["id"];

type ExperimentTabsProps = {
  detail: ExperimentDetailResponse | null;
  experiment: ExperimentSummary | undefined;
};

export function ExperimentTabs({ detail, experiment }: ExperimentTabsProps) {
  const [active, setActive] = useState<TabId>("sweep");
  const [isReady, setIsReady] = useState(false);
  const runs = detail?.runs ?? EMPTY_ROWS;
  const folds = detail?.folds ?? EMPTY_ROWS;
  const config = detail?.experiment_config ?? {};
  const agentSummary = detail?.agent_summary ?? {};
  const bestRun = useMemo(
    () => findBestRun(runs, experiment?.best_run_id ?? stringValue(agentSummary.best_run_id)),
    [agentSummary.best_run_id, experiment?.best_run_id, runs],
  );
  const backtestHref = buildBacktestHref(config, bestRun);

  useEffect(() => {
    const timer = window.setTimeout(() => setIsReady(true), 0);
    return () => window.clearTimeout(timer);
  }, []);

  if (!detail) {
    return (
      <EmptyState
        title="No experiment selected"
        description="Create or select a local experiment to review sweep, folds, runs, and summary."
      />
    );
  }

  return (
    <section
      className="flex min-h-[520px] flex-col rounded border border-border-subtle bg-bg-surface"
      data-experiment-tabs-ready={isReady ? "true" : "false"}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle p-4">
        <div>
          <div className="font-label-caps text-text-secondary">Selected experiment</div>
          <h3 className="mt-1 break-all font-data-mono text-sm text-text-primary">{detail.id}</h3>
          <div className="mt-2 flex flex-wrap gap-2 font-data-mono text-[10px] uppercase">
            <span className="rounded border border-border-subtle px-2 py-1 text-text-secondary">
              runs {runs.length}
            </span>
            <span className="rounded border border-border-subtle px-2 py-1 text-text-secondary">
              folds {folds.length}
            </span>
            <span className="rounded border border-warning/40 bg-warning/10 px-2 py-1 text-warning">
              Sample data - illustrative only
            </span>
          </div>
        </div>
        {bestRun ? (
          <Link
            className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary"
            href={backtestHref}
          >
            Send to Backtest
          </Link>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2 border-b border-border-subtle p-4">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`rounded border px-3 py-2 font-body-sm ${
              active === tab.id
                ? "border-primary bg-primary/10 text-primary"
                : "border-border-subtle text-text-secondary"
            }`}
            onClick={() => setActive(tab.id)}
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 p-4">
        {active === "sweep" ? <SweepHeatmap runs={runs} /> : null}
        {active === "folds" ? <WalkForwardFolds folds={folds} /> : null}
        {active === "runs" ? <RunComparison runs={runs} bestRunId={stringValue(bestRun?.run_id)} /> : null}
        {active === "summary" ? <AgentSummary summary={agentSummary} /> : null}
      </div>
    </section>
  );
}

function SweepHeatmap({ runs }: { runs: PreviewRecord[] }) {
  if (!runs.length) {
    return (
      <EmptyState
        title="Sweep heatmap unavailable"
        description="This experiment does not include experiment_runs.parquet data."
      />
    );
  }

  const sharpeValues = runs.map((run) => numberValue(run.sharpe)).filter(isNumber);
  const minSharpe = Math.min(...sharpeValues);
  const maxSharpe = Math.max(...sharpeValues);

  return (
    <div>
      <PanelHeading
        title="Sweep Heatmap"
        description="Sharpe by lookback and top_n from the local parameter sweep."
      />
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {runs.map((run) => {
          const sharpe = numberValue(run.sharpe);
          const lookback = stringValue(run.lookback ?? "--");
          const topN = stringValue(run.top_n ?? "--");
          return (
            <div
              key={stringValue(run.run_id) || `${lookback}-${topN}`}
              className="rounded border border-border-subtle p-3"
              style={{ backgroundColor: heatColor(sharpe, minSharpe, maxSharpe) }}
            >
              <div className="font-data-mono text-xs text-text-primary">
                lookback={lookback} / top_n={topN}
              </div>
              <div className="mt-3 font-data-mono text-2xl font-semibold text-text-primary">
                {formatNumber(sharpe, 2)}
              </div>
              <div className="mt-1 font-body-sm text-text-secondary">Sharpe</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WalkForwardFolds({ folds }: { folds: PreviewRecord[] }) {
  if (!folds.length) {
    return (
      <EmptyState
        title="Walk-forward folds unavailable"
        description="This experiment does not include walk_forward_folds.parquet data."
      />
    );
  }

  return (
    <div>
      <PanelHeading
        title="Walk-forward Folds"
        description="Validation windows and fold metrics for the selected experiment."
      />
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
    </div>
  );
}

function RunComparison({ runs, bestRunId }: { runs: PreviewRecord[]; bestRunId?: string }) {
  if (!runs.length) {
    return (
      <EmptyState
        title="Run comparison unavailable"
        description="This experiment does not include run-level metric data."
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
    <div>
      <PanelHeading
        title="Run Comparison"
        description="Runs sorted by Sharpe, with total return shown in the detail table."
      />
      <div className="mt-4 h-72 rounded border border-border-subtle bg-surface-muted p-3">
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
    </div>
  );
}

function AgentSummary({ summary }: { summary: Record<string, unknown> }) {
  if (!Object.keys(summary).length) {
    return (
      <EmptyState
        title="Agent summary unavailable"
        description="agent_summary.json was not found in this experiment directory."
      />
    );
  }

  const notes = Array.isArray(summary.notes) ? summary.notes.map(String) : [];
  const json = JSON.stringify(summary, null, 2);

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PanelHeading
          title="Agent Summary"
          description="Read-only agent summary for human review. It does not promote or deploy anything."
        />
        <button
          className="rounded border border-border-subtle px-3 py-2 font-body-sm text-text-secondary"
          onClick={() => void navigator.clipboard?.writeText(json)}
          type="button"
        >
          Copy JSON
        </button>
      </div>
      {notes.length ? (
        <ul className="mt-4 space-y-2">
          {notes.map((note) => (
            <li
              key={note}
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-body-sm text-text-primary"
            >
              {note}
            </li>
          ))}
        </ul>
      ) : null}
      <pre className="mt-4 max-h-96 overflow-auto rounded border border-border-subtle bg-surface-muted p-3 font-data-mono text-xs text-text-primary">
        {json}
      </pre>
    </div>
  );
}

function PanelHeading({ title, description }: { title: string; description: string }) {
  return (
    <div>
      <h3 className="font-headline-lg text-text-primary">{title}</h3>
      <p className="mt-1 font-body-sm text-text-secondary">{description}</p>
    </div>
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
    <div className="mt-4 overflow-auto rounded border border-border-subtle">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-border-subtle bg-surface-muted">
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

function buildBacktestHref(config: Record<string, unknown>, bestRun: PreviewRecord | undefined) {
  const params = new URLSearchParams();
  const symbols = Array.isArray(config.symbols) ? config.symbols.map(String).join(",") : "SPY,QQQ";
  params.set("symbols", symbols);
  params.set("start", stringValue(config.start) || "2024-01-02");
  params.set("end", stringValue(config.end) || "2024-02-15");
  params.set("provider", "futu");
  params.set("lookback", stringValue(bestRun?.lookback ?? "5"));
  params.set("top_n", stringValue(bestRun?.top_n ?? "1"));
  params.set("initial_cash", stringValue(config.initial_cash ?? "100000"));
  params.set("commission_bps", stringValue(config.commission_bps ?? "1"));
  params.set("slippage_bps", stringValue(config.slippage_bps ?? "5"));
  return `/backtest?${params.toString()}`;
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
