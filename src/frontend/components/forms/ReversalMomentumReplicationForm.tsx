'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useForm } from "react-hook-form";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { toast } from "sonner";
import { z } from "zod";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { formatPercent } from "@/lib/api";
import { useIsHydrated } from "@/lib/hydration";
import type { Locale } from "@/lib/locale";

const replicationSchema = z.object({
  symbols: z.string().min(1, "Enter at least two symbols"),
  start: z.string().min(1, "Start date is required"),
  end: z.string().min(1, "End date is required"),
  provider: z.enum(["futu", "sample", "tiingo"]),
  initial_cash: z.coerce.number().positive(),
});

type ReplicationFormValues = z.infer<typeof replicationSchema>;

type ReplicationResult = {
  source: string;
  paper: {
    title: string;
    authors: string[];
    doi: string;
    journal: string;
  };
  methodology: {
    formation: string;
    reversal_signal: string;
    momentum_signal: string;
    holding_period: string;
    price_filter: string;
  };
  metrics: Record<string, number | null>;
  diagnostics: Record<string, number | null>;
  equity_curve: Array<Record<string, unknown>>;
  monthly_returns: Array<Record<string, unknown>>;
  positions: Array<Record<string, unknown>>;
  legs: Array<Record<string, unknown>>;
  warnings: string[];
};

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };
const DEFAULTS: ReplicationFormValues = {
  symbols: "SPY,QQQ,IWM,DIA,XLK,XLF,XLV,XLY,XLP,XLE",
  start: "2023-01-01",
  end: "2026-05-22",
  provider: "futu",
  initial_cash: 1,
};

const copy = {
  en: {
    panelTitle: "Paper Replication",
    panelDescription:
      "Rebuilds the paper monthly reversal and momentum portfolios with local read-only market data.",
    symbolsLabel: "Symbols",
    startLabel: "Start",
    endLabel: "End",
    dataSourceLabel: "Data Source",
    initialLevelLabel: "Initial Index Level",
    running: "Running...",
    runButton: "Run paper replication",
    runSuccess: (source: string) => `Replication finished with ${source} data`,
    pageTitle: "Short-Term Reversals and Longer-Term Momentum",
    pageDescription:
      "This page implements the paper core portfolio test: contrarian ranking on the previous month, momentum ranking on months t-12 through t-2, then one-month holding returns.",
    metricTotalReturn: "Total return",
    metricAnnualReturn: "Annual return",
    metricSharpe: "Sharpe",
    metricMonths: "Months",
    paperMethod: "Paper Method",
    methodFormation: "Formation",
    methodReversal: "Reversal",
    methodMomentum: "Momentum",
    methodHolding: "Holding",
    methodFilter: "Filter",
    diagnostics: "Diagnostics",
    diagRelation: "Reversal / momentum relation",
    diagHighNoise: "High-noise reversal avg.",
    diagLowNoise: "Low-noise reversal avg.",
    diagDoi: "DOI",
    monthlyTitle: "Monthly Strategy Returns",
    monthlyDescription: "Reversal, momentum, and composite long-short return rows.",
    monthlyEmptyTitle: "No monthly return rows",
    monthlyEmptyDescription: "Run a wider universe and longer history.",
    positionsTitle: "Composite Positions",
    positionsDescription: "Long and short legs selected by the composite signal.",
    positionsEmptyTitle: "No position rows",
    positionsEmptyDescription: "Run the replication to generate composite positions.",
    readyTitle: "Ready to Run",
    readyDescription:
      "Keep Futu selected for local real data. Use sample only when you need a stable smoke test without touching external market data.",
    notesTitle: "Replication Notes",
    notesDescription:
      "The full local notes describe the implemented paper method, data requirements, and current scope limits.",
    openDocs: "Open docs",
    equityTitle: "Composite Equity Curve",
    equityDescription: "Normalized long-short index from the combined reversal and momentum signal.",
  },
  zh: {
    panelTitle: "策略复现",
    panelDescription: "使用本地只读市场数据重建论文中的月度反转与动量组合。",
    symbolsLabel: "标的",
    startLabel: "开始",
    endLabel: "结束",
    dataSourceLabel: "数据源",
    initialLevelLabel: "初始指数水平",
    running: "运行中…",
    runButton: "运行模拟复现",
    runSuccess: (source: string) => `复现完成，使用 ${source} 数据`,
    pageTitle: "短期反转与长期动量",
    pageDescription:
      "本页面实现论文的核心组合测试：基于上一个月的反向排序、基于 t-12 至 t-2 月份的动量排序，然后计算持有一个月的收益。",
    metricTotalReturn: "总收益",
    metricAnnualReturn: "年化收益",
    metricSharpe: "夏普比率",
    metricMonths: "月数",
    paperMethod: "论文方法",
    methodFormation: "形成期",
    methodReversal: "反转",
    methodMomentum: "动量",
    methodHolding: "持有期",
    methodFilter: "过滤",
    diagnostics: "诊断",
    diagRelation: "反转 / 动量关系",
    diagHighNoise: "高噪声反转均值",
    diagLowNoise: "低噪声反转均值",
    diagDoi: "DOI",
    monthlyTitle: "月度策略收益",
    monthlyDescription: "反转、动量及复合多空收益行。",
    monthlyEmptyTitle: "暂无月度收益行",
    monthlyEmptyDescription: "请运行更大的标的范围和更长的历史区间。",
    positionsTitle: "复合持仓",
    positionsDescription: "由复合信号选出的多头与空头腿。",
    positionsEmptyTitle: "暂无持仓行",
    positionsEmptyDescription: "请运行复现以生成复合持仓。",
    readyTitle: "准备运行",
    readyDescription:
      "保持选择 Futu 以使用本地真实数据。仅在需要不触及外部市场数据的稳定冒烟测试时使用 sample。",
    notesTitle: "复现说明",
    notesDescription: "完整的本地说明描述了已实现的论文方法、数据要求以及当前的范围限制。",
    openDocs: "打开文档",
    equityTitle: "复合权益曲线",
    equityDescription: "由反转与动量组合信号生成的归一化多空指数。",
  },
} as const;

export function ReversalMomentumReplicationForm({ locale = "en" }: { locale?: Locale }) {
  const text = copy[locale];
  const isHydrated = useIsHydrated();
  const form = useForm<ReplicationFormValues>({
    resolver: zodResolver(replicationSchema),
    defaultValues: DEFAULTS,
  });
  const mutation = useMutation({
    mutationFn: (values: ReplicationFormValues) =>
      apiPost<ReplicationResult>("/api/replications/reversal-momentum/run", {
        ...values,
        symbols: splitSymbols(values.symbols),
        top_n: null,
      }),
    onSuccess: (payload) => {
      toast.success(text.runSuccess(payload.source));
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;
  const result = mutation.data;

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex h-full w-[340px] flex-col overflow-y-auto border-r border-border-subtle bg-bg-surface">
        <div className="border-b border-border-subtle p-4">
          <h2 className="font-headline-lg text-text-primary">{text.panelTitle}</h2>
          <p className="mt-1 font-body-sm text-text-secondary">
            {text.panelDescription}
          </p>
        </div>
        <form
          className="flex flex-col gap-4 p-4"
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
        >
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.symbolsLabel}
            <textarea
              className="min-h-24 rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
              {...form.register("symbols")}
            />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              {text.startLabel}
              <input
                className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary"
                type="date"
                {...form.register("start")}
              />
            </label>
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              {text.endLabel}
              <input
                className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary"
                type="date"
                {...form.register("end")}
              />
            </label>
          </div>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.dataSourceLabel}
            <select
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
              {...form.register("provider")}
            >
              <option value="futu" style={optionStyle}>
                futu
              </option>
              <option value="sample" style={optionStyle}>
                sample
              </option>
              <option value="tiingo" style={optionStyle}>
                tiingo
              </option>
            </select>
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.initialLevelLabel}
            <input
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
              min="0.01"
              step="0.01"
              type="number"
              {...form.register("initial_cash", { valueAsNumber: true })}
            />
          </label>
          {error ? <p className="font-body-sm text-danger">{error}</p> : null}
          <button
            className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!isHydrated || mutation.isPending}
            type="submit"
          >
            {mutation.isPending ? text.running : text.runButton}
          </button>
        </form>
      </aside>

      <section className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border-subtle pb-4">
          <div>
            <h1 className="font-headline-xl text-text-primary">
              {text.pageTitle}
            </h1>
            <p className="mt-1 max-w-3xl font-body-sm text-text-secondary">
              {text.pageDescription}
            </p>
          </div>
          {result ? <DataSourceBadge source={result.source} /> : null}
        </div>

        {result ? (
          <>
            {result.warnings.length ? (
              <div className="rounded border border-warning/30 bg-warning/10 p-3 font-body-sm text-warning">
                {result.warnings.join(" ")}
              </div>
            ) : null}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
              <MetricCard label={text.metricTotalReturn} value={percentMetric(result.metrics.total_return)} />
              <MetricCard label={text.metricAnnualReturn} value={percentMetric(result.metrics.annualized_return)} />
              <MetricCard label={text.metricSharpe} value={numberMetric(result.metrics.sharpe, 2)} />
              <MetricCard label={text.metricMonths} value={numberMetric(result.metrics.observation_months, 0)} />
            </div>
            <ReplicationEquityChart rows={result.equity_curve} text={text} />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <section className="rounded border border-border-subtle bg-bg-surface p-4">
                <h3 className="font-label-caps text-text-primary">{text.paperMethod}</h3>
                <dl className="mt-3 grid gap-3 font-body-sm">
                  <MethodRow label={text.methodFormation} value={result.methodology.formation} />
                  <MethodRow label={text.methodReversal} value={result.methodology.reversal_signal} />
                  <MethodRow label={text.methodMomentum} value={result.methodology.momentum_signal} />
                  <MethodRow label={text.methodHolding} value={result.methodology.holding_period} />
                  <MethodRow label={text.methodFilter} value={result.methodology.price_filter} />
                </dl>
              </section>
              <section className="rounded border border-border-subtle bg-bg-surface p-4">
                <h3 className="font-label-caps text-text-primary">{text.diagnostics}</h3>
                <dl className="mt-3 grid gap-3 font-body-sm">
                  <MethodRow
                    label={text.diagRelation}
                    value={numberMetric(result.diagnostics.reversal_momentum_return_correlation, 3)}
                  />
                  <MethodRow
                    label={text.diagHighNoise}
                    value={percentMetric(result.diagnostics.high_noise_average_reversal_return)}
                  />
                  <MethodRow
                    label={text.diagLowNoise}
                    value={percentMetric(result.diagnostics.low_noise_average_reversal_return)}
                  />
                  <MethodRow label={text.diagDoi} value={result.paper.doi} />
                </dl>
              </section>
            </div>
            <DataPreviewTable
              title={text.monthlyTitle}
              description={text.monthlyDescription}
              rows={result.monthly_returns}
              emptyTitle={text.monthlyEmptyTitle}
              emptyDescription={text.monthlyEmptyDescription}
              maxRows={12}
            />
            <DataPreviewTable
              title={text.positionsTitle}
              description={text.positionsDescription}
              rows={result.positions}
              emptyTitle={text.positionsEmptyTitle}
              emptyDescription={text.positionsEmptyDescription}
              maxRows={12}
            />
          </>
        ) : (
          <div className="rounded border border-border-subtle bg-bg-surface p-6">
            <h3 className="font-label-caps text-text-primary">{text.readyTitle}</h3>
            <p className="mt-2 max-w-3xl font-body-sm text-text-secondary">
              {text.readyDescription}
            </p>
          </div>
        )}
        <section className="rounded border border-border-subtle bg-bg-surface p-4" id="paper-docs">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-label-caps text-text-primary">{text.notesTitle}</h3>
              <p className="mt-1 max-w-3xl font-body-sm text-text-secondary">
                {text.notesDescription}
              </p>
            </div>
            <Link
              className="rounded border border-border-subtle px-3 py-2 font-body-sm text-info hover:bg-surface-muted"
              href="/docs/reversal-momentum"
            >
              {text.openDocs}
            </Link>
          </div>
        </section>
      </section>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-3">
      <span className="font-label-caps text-text-secondary">{label}</span>
      <div className="mt-2 font-data-mono text-lg font-bold text-text-primary">{value}</div>
    </div>
  );
}

function MethodRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-3">
      <dt className="font-label-caps text-text-secondary">{label}</dt>
      <dd className="font-data-mono text-text-primary">{value}</dd>
    </div>
  );
}

function ReplicationEquityChart({
  rows,
  text,
}: {
  rows: Array<Record<string, unknown>>;
  text: (typeof copy)[Locale];
}) {
  const chartRows = rows
    .map((row, index) => ({
      timestamp: String(row.timestamp ?? `row-${index + 1}`).slice(0, 10),
      equity: Number(row.equity),
    }))
    .filter((row) => Number.isFinite(row.equity));

  return (
    <section className="rounded border border-border-subtle bg-bg-surface p-4">
      <div className="mb-3">
        <h3 className="font-label-caps text-text-primary">{text.equityTitle}</h3>
        <p className="mt-1 font-body-sm text-text-secondary">
          {text.equityDescription}
        </p>
      </div>
      <div
        className="h-[320px] rounded border border-border-subtle bg-surface-muted p-3"
        data-testid="replication-equity-chart"
      >
        <ResponsiveContainer height="100%" width="100%">
          <LineChart data={chartRows} margin={{ bottom: 8, left: 0, right: 16, top: 12 }}>
            <CartesianGrid stroke="rgba(148, 163, 184, 0.12)" vertical={false} />
            <XAxis
              dataKey="timestamp"
              minTickGap={34}
              stroke="#64748B"
              tick={{ fill: "#94A3B8", fontSize: 11 }}
              tickLine={false}
            />
            <YAxis
              domain={["auto", "auto"]}
              stroke="#64748B"
              tick={{ fill: "#94A3B8", fontSize: 11 }}
              tickFormatter={(value) => Number(value).toFixed(2)}
              tickLine={false}
              width={54}
            />
            <Tooltip
              contentStyle={{
                background: "#101614",
                border: "1px solid rgba(148, 163, 184, 0.24)",
                borderRadius: 4,
                color: "#E2E8F0",
              }}
              formatter={(value) => Number(value).toFixed(4)}
              labelStyle={{ color: "#94A3B8" }}
            />
            <Line
              activeDot={{ r: 4 }}
              dataKey="equity"
              dot={false}
              name="Composite"
              stroke="#10C89B"
              strokeWidth={2}
              type="monotone"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function percentMetric(value: unknown) {
  return typeof value === "number" ? formatPercent(value) : "--";
}

function numberMetric(value: unknown, digits: number) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}
