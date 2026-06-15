'use client';

import Link from "next/link";
import { useMemo, useState } from "react";
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
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { Card, MetricStat, PageHeader, SectionTitle } from "@/components/ui/primitives";
import type {
  FactorMetadata,
  PreviewRecord,
  StrategyMetadata,
  UniverseDefinition,
} from "@/lib/api";
import { formatPercent } from "@/lib/api";
import { ApiClientError, apiPost } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";
import { localizePath, type Locale } from "@/lib/locale";
import { asStringArray, buildStrategyPayload } from "@/lib/strategyPayload";
import { FutuUnavailableHint, futuOptionLabel } from "./FutuProviderHint";

type StrategyCatalogWorkbenchProps = {
  strategies: StrategyMetadata[];
  universes: UniverseDefinition[];
  factors: FactorMetadata[];
  locale: Locale;
  futuReachable?: boolean;
  initialStrategyId?: string;
  initialResult?: Record<string, unknown> | null;
};

// Note: the "Strategy Catalog" heading, the "Strategy" select label, and the
// "Run Strategy" button name are asserted by e2e specs
// (reversal-momentum-replication.spec.ts, phase10-smoke.spec.ts) — keep them.
const copy = {
  en: {
    eyebrow: "Research Pipeline",
    title: "Strategy Catalog",
    subtitle: "Registered research strategies. Adding a backend strategy adds a catalog entry here.",
    source: "Paper source",
    parameters: "Parameters",
    run: "Run Strategy",
    running: "Running...",
    result: "Result",
    openBacktest: "Open backtest",
    openReplication: "Open replication",
    openDocs: "Open docs",
    noResultTitle: "No result yet",
    noResult: "Run a strategy to see the response.",
    strategy: "Strategy",
    runsInBacktester: "Also available in the dedicated Backtester",
    catalogOnly: "Replication · runs from this catalog only",
    universeSize: (n: number) => `Universe: ${n} symbols`,
    longShort: (l: number, s: number) => `≈ ${l} long · ${s} short`,
    autoDecile: "Blank = auto decile (10% of monthly investable names, min 1)",
    smallUniverseWarn:
      "Small universe — this validates the workflow, not a paper-grade decile replication.",
    finished: (name: string) => `${name} finished`,
    metricTotalReturn: "Total Return",
    metricAnnualReturn: "Annual Return",
    metricSharpe: "Sharpe",
    metricMonths: "Months",
    equityTitle: "Composite Equity Curve",
    equityHint: "Normalized long-short index from the combined reversal and momentum signal.",
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
    monthlyDesc: "Reversal, momentum, and composite long-short return rows.",
    monthlyEmptyTitle: "No monthly return rows",
    monthlyEmptyDesc: "Run a wider universe and longer history.",
    positionsTitle: "Composite Positions",
    positionsDesc: "Long and short legs selected by the composite signal.",
    positionsEmptyTitle: "No position rows",
    positionsEmptyDesc: "Run the replication to generate composite positions.",
    rawTitle: "Raw Response",
    rawDesc: (endpoint: string) => `Top-level fields returned by ${endpoint}.`,
  },
  zh: {
    eyebrow: "研究流水线",
    title: "策略目录",
    subtitle: "后端已登记的研究策略。新增后端策略后，这里会自动出现目录项。",
    source: "论文出处",
    parameters: "参数",
    run: "运行策略",
    running: "运行中...",
    result: "结果",
    openBacktest: "打开回测",
    openReplication: "打开复现",
    openDocs: "打开文档",
    noResultTitle: "暂无结果",
    noResult: "运行策略后会显示结果。",
    strategy: "策略",
    runsInBacktester: "同时可在独立的回测器中运行",
    catalogOnly: "研报复现 · 仅在本目录运行",
    universeSize: (n: number) => `当前股票池：${n} 个标的`,
    longShort: (l: number, s: number) => `预计做多 ${l} 只 · 做空 ${s} 只`,
    autoDecile: "留空 = 自动十分位（每月可投标的的 10%，至少 1 只）",
    smallUniverseWarn: "股票池较小，这只是流程验证，不是严谨的论文级十分位复现。",
    finished: (name: string) => `${name} 运行完成`,
    metricTotalReturn: "总收益",
    metricAnnualReturn: "年化收益",
    metricSharpe: "夏普",
    metricMonths: "月数",
    equityTitle: "复合权益曲线",
    equityHint: "由反转与动量组合信号生成的归一化多空指数。",
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
    monthlyDesc: "反转、动量及复合多空收益行。",
    monthlyEmptyTitle: "暂无月度收益行",
    monthlyEmptyDesc: "请运行更大的标的范围和更长的历史区间。",
    positionsTitle: "复合持仓",
    positionsDesc: "由复合信号选出的多头与空头腿。",
    positionsEmptyTitle: "暂无持仓行",
    positionsEmptyDesc: "请运行复现以生成复合持仓。",
    rawTitle: "原始响应",
    rawDesc: (endpoint: string) => `${endpoint} 返回的顶层字段。`,
  },
} as const;

const fieldLabels = {
  en: {
    universe_id: "Universe",
    factor_ids: "Factors",
    weights: "Weights",
    top_n: "Top N",
    benchmark_symbol: "Benchmark",
    start: "Start Date",
    end: "End Date",
    provider: "Provider",
    symbols: "Symbols",
    initial_cash: "Initial Cash",
  },
  zh: {
    universe_id: "股票池",
    factor_ids: "因子",
    weights: "权重",
    top_n: "Top N",
    benchmark_symbol: "基准",
    start: "开始日期",
    end: "结束日期",
    provider: "数据源",
    symbols: "标的",
    initial_cash: "初始资金",
  },
} as const;

const inputClass =
  "rounded-lg border border-border-subtle bg-bg-base px-3 py-2 font-data-mono text-text-primary disabled:opacity-50";

export function StrategyCatalogWorkbench({
  strategies,
  universes,
  factors,
  locale,
  futuReachable = true,
  initialStrategyId,
  initialResult = null,
}: StrategyCatalogWorkbenchProps) {
  const text = copy[locale];
  const isHydrated = useIsHydrated();
  const activeStrategies = strategies.length ? strategies : fallbackStrategies();
  const [strategyId, setStrategyId] = useState(
    initialStrategyId ?? activeStrategies[0]?.id ?? "",
  );
  const strategy = activeStrategies.find((item) => item.id === strategyId) ?? activeStrategies[0];
  const [values, setValues] = useState<Record<string, unknown>>(strategy?.default_payload ?? {});
  const [result, setResult] = useState<Record<string, unknown> | null>(initialResult);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const fields = useMemo(
    () => strategy?.parameter_schema?.fields ?? {},
    [strategy],
  );

  // For replication strategies the top_n field is hard to reason about: blank
  // means "auto decile" and each leg is capped at half the universe. Compute
  // live guidance so the user can see the actual long/short sizing.
  const replicationGuidance = useMemo(() => {
    if (!strategy || strategy.result_type !== "replication") {
      return null;
    }
    if (!("top_n" in fields) || !("symbols" in fields)) {
      return null;
    }
    const symbols = asStringArray(values.symbols ?? fields.symbols?.default);
    const universeSize = symbols.length;
    if (universeSize < 2) {
      return { universeSize, longCount: 0, shortCount: 0, isAuto: true };
    }
    const rawTopN = values.top_n;
    const isAuto = rawTopN === "" || rawTopN === null || rawTopN === undefined;
    const requested = isAuto
      ? Math.max(1, Math.floor(universeSize * 0.1))
      : Math.max(1, Number(rawTopN) || 1);
    // Each leg is capped at half the universe (see reversal_momentum.py).
    const perLeg = Math.min(requested, Math.floor(universeSize / 2));
    return { universeSize, longCount: perLeg, shortCount: perLeg, isAuto };
  }, [strategy, fields, values]);

  const replicationView =
    result && strategy?.result_type === "replication" ? asReplicationView(result) : null;

  function chooseStrategy(nextId: string) {
    const nextStrategy = activeStrategies.find((item) => item.id === nextId);
    setStrategyId(nextId);
    setValues(nextStrategy?.default_payload ?? {});
    setResult(null);
    setError(null);
  }

  async function submit() {
    if (!strategy) {
      return;
    }
    setPending(true);
    setError(null);
    try {
      const payload = buildStrategyPayload(fields, values);
      // Backtest-engine strategies dispatch on strategy_id; the schema fields
      // do not include it, so inject it for backtest result types. Replication
      // endpoints have their own contract and ignore it.
      if (strategy.result_type === "backtest") {
        payload.strategy_id = strategy.id;
      }
      const response = await apiPost<Record<string, unknown>>(strategy.run_endpoint, payload);
      setResult(response);
      toast.success(text.finished(strategy.name));
    } catch (requestError) {
      setError(
        requestError instanceof ApiClientError
          ? requestError.message
          : requestError instanceof Error
            ? requestError.message
            : "Request failed",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="flex h-full min-h-0 bg-bg-base">
      <aside className="flex h-full w-[360px] shrink-0 flex-col overflow-y-auto border-r border-border-subtle bg-bg-surface p-4">
        <h2 className="font-headline-lg text-text-primary">{text.title}</h2>
        <p className="mt-2 font-body-sm text-text-secondary">{text.subtitle}</p>

        <label className="mt-5 flex flex-col gap-1 font-body-sm text-text-primary">
          {text.strategy}
          <select
            className={inputClass}
            disabled={!isHydrated || pending}
            onChange={(event) => chooseStrategy(event.target.value)}
            value={strategy?.id ?? ""}
          >
            {activeStrategies.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>

        {strategy ? (
          <section className="mt-4 rounded-lg border border-border-subtle bg-bg-surface-muted p-3">
            <div className="font-label-caps text-text-secondary">{text.source}</div>
            <p className="mt-2 font-body-sm text-text-primary">
              {strategy.paper_source ?? strategy.description}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex rounded-lg border px-2 py-1 font-data-mono text-[10px] uppercase ${
                  strategy.result_type === "backtest"
                    ? "border-accent-success/40 bg-accent-success/10 text-accent-success"
                    : "border-info/40 bg-info/10 text-info"
                }`}
              >
                {strategy.result_type === "backtest" ? text.runsInBacktester : text.catalogOnly}
              </span>
              {strategy.id === "reversal_momentum" ? (
                <Link
                  className="font-body-sm text-info underline-offset-2 hover:underline"
                  href={localizePath("/docs/reversal-momentum", locale)}
                >
                  {text.openDocs}
                </Link>
              ) : null}
            </div>
          </section>
        ) : null}

        <section className="mt-4 flex flex-col gap-3 rounded-lg border border-border-subtle bg-bg-surface-muted p-3">
          <div className="font-label-caps text-text-secondary">{text.parameters}</div>
          {Object.entries(fields).map(([fieldName, schema]) => (
            <FieldRenderer
              factors={factors}
              fieldName={fieldName}
              key={fieldName}
              schema={schema}
              disabled={!isHydrated || pending}
              setValues={setValues}
              locale={locale}
              universes={universes}
              values={values}
              futuReachable={futuReachable}
            />
          ))}
          {error ? <p className="font-body-sm text-danger">{error}</p> : null}
          {replicationGuidance ? (
            <div className="rounded-lg border border-info/30 bg-info/5 p-3 font-body-sm">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="font-data-mono text-text-primary">
                  {text.universeSize(replicationGuidance.universeSize)}
                </span>
                <span className="font-data-mono text-info">
                  {text.longShort(replicationGuidance.longCount, replicationGuidance.shortCount)}
                </span>
              </div>
              <p className="mt-1 text-text-secondary">{text.autoDecile}</p>
              {replicationGuidance.universeSize > 0 && replicationGuidance.universeSize < 10 ? (
                <p className="mt-1 text-warning">{text.smallUniverseWarn}</p>
              ) : null}
            </div>
          ) : null}
          <button
            className="rounded-lg bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!isHydrated || pending}
            onClick={() => void submit()}
            type="button"
          >
            {pending ? text.running : text.run}
          </button>
        </section>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-5">
        <PageHeader
          eyebrow={text.eyebrow}
          title={strategy?.name ?? text.title}
          subtitle={strategy?.description}
          actions={
            <>
              {result?.run_id ? (
                <span className="max-w-full break-all rounded-lg border border-border-subtle px-3 py-2 font-data-mono text-xs text-text-secondary">
                  {String(result.run_id)}
                </span>
              ) : null}
              {replicationView ? <DataSourceBadge source={replicationView.source} /> : null}
              {result?.run_id && strategy?.result_type === "backtest" ? (
                <Link
                  className="rounded-lg border border-border-subtle px-3 py-2 font-body-sm text-info"
                  href={localizePath(`/backtest/${String(result.run_id)}`, locale)}
                >
                  {text.openBacktest}
                </Link>
              ) : null}
              {result?.run_id && strategy?.result_type === "replication" ? (
                <Link
                  className="rounded-lg border border-border-subtle px-3 py-2 font-body-sm text-info"
                  href={localizePath(`/replications/${String(result.run_id)}`, locale)}
                >
                  {text.openReplication}
                </Link>
              ) : null}
            </>
          }
        />

        {replicationView ? (
          <>
            {replicationView.warnings.length ? (
              <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 font-body-sm text-warning">
                {replicationView.warnings.join(" ")}
              </div>
            ) : null}
            <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
              <MetricStat
                label={text.metricTotalReturn}
                value={percentMetric(replicationView.metrics.total_return)}
              />
              <MetricStat
                label={text.metricAnnualReturn}
                value={percentMetric(replicationView.metrics.annualized_return)}
              />
              <MetricStat
                label={text.metricSharpe}
                value={numberMetric(replicationView.metrics.sharpe, 2)}
              />
              <MetricStat
                label={text.metricMonths}
                value={numberMetric(replicationView.metrics.observation_months, 0)}
              />
            </div>
            <Card>
              <SectionTitle title={text.equityTitle} hint={text.equityHint} />
              <ReplicationEquityChart rows={replicationView.equityCurve} />
            </Card>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Card>
                <SectionTitle title={text.paperMethod} />
                <dl className="grid gap-3 font-body-sm">
                  <MethodRow label={text.methodFormation} value={replicationView.methodology.formation} />
                  <MethodRow label={text.methodReversal} value={replicationView.methodology.reversal_signal} />
                  <MethodRow label={text.methodMomentum} value={replicationView.methodology.momentum_signal} />
                  <MethodRow label={text.methodHolding} value={replicationView.methodology.holding_period} />
                  <MethodRow label={text.methodFilter} value={replicationView.methodology.price_filter} />
                </dl>
              </Card>
              <Card>
                <SectionTitle title={text.diagnostics} />
                <dl className="grid gap-3 font-body-sm">
                  <MethodRow
                    label={text.diagRelation}
                    value={numberMetric(replicationView.diagnostics.reversal_momentum_return_correlation, 3)}
                  />
                  <MethodRow
                    label={text.diagHighNoise}
                    value={percentMetric(replicationView.diagnostics.high_noise_average_reversal_return)}
                  />
                  <MethodRow
                    label={text.diagLowNoise}
                    value={percentMetric(replicationView.diagnostics.low_noise_average_reversal_return)}
                  />
                  <MethodRow label={text.diagDoi} value={replicationView.doi} />
                </dl>
              </Card>
            </div>
            <DataPreviewTable
              title={text.monthlyTitle}
              description={text.monthlyDesc}
              rows={replicationView.monthlyReturns}
              emptyTitle={text.monthlyEmptyTitle}
              emptyDescription={text.monthlyEmptyDesc}
              maxRows={12}
            />
            <DataPreviewTable
              title={text.positionsTitle}
              description={text.positionsDesc}
              rows={replicationView.positions}
              emptyTitle={text.positionsEmptyTitle}
              emptyDescription={text.positionsEmptyDesc}
              maxRows={12}
            />
          </>
        ) : result ? (
          <DataPreviewTable
            columns={["key", "value"]}
            description={text.rawDesc(strategy?.run_endpoint ?? "")}
            emptyDescription={text.noResult}
            emptyTitle={text.noResultTitle}
            rows={flattenResult(result)}
            title={text.rawTitle}
          />
        ) : (
          <Card>
            <SectionTitle title={text.noResultTitle} hint={text.noResult} />
          </Card>
        )}
      </section>
    </main>
  );
}

function MethodRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[150px_1fr] gap-3">
      <dt className="font-label-caps text-text-secondary">{label}</dt>
      <dd className="font-data-mono text-text-primary">{value}</dd>
    </div>
  );
}

function ReplicationEquityChart({ rows }: { rows: Array<Record<string, unknown>> }) {
  const chartRows = rows
    .map((row, index) => ({
      timestamp: String(row.timestamp ?? `row-${index + 1}`).slice(0, 10),
      equity: Number(row.equity),
    }))
    .filter((row) => Number.isFinite(row.equity));

  return (
    <div
      className="h-[320px] rounded-lg border border-border-subtle bg-bg-surface-muted p-3"
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
              borderRadius: 8,
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
            stroke="#00C896"
            strokeWidth={2}
            type="monotone"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

type ReplicationView = {
  source: string;
  warnings: string[];
  metrics: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
  methodology: Record<string, string>;
  doi: string;
  equityCurve: Array<Record<string, unknown>>;
  monthlyReturns: Array<Record<string, unknown>>;
  positions: Array<Record<string, unknown>>;
};

/**
 * The replication endpoint returns a rich payload (metrics + methodology +
 * equity curve). Parse it defensively: if the shape is unexpected, return null
 * and the caller falls back to the raw key/value table.
 */
function asReplicationView(result: Record<string, unknown>): ReplicationView | null {
  const metrics = asRecord(result.metrics);
  const methodologyRaw = asRecord(result.methodology);
  if (!metrics || !methodologyRaw || !Array.isArray(result.equity_curve)) {
    return null;
  }
  const methodology: Record<string, string> = {};
  for (const key of [
    "formation",
    "reversal_signal",
    "momentum_signal",
    "holding_period",
    "price_filter",
  ]) {
    methodology[key] = typeof methodologyRaw[key] === "string" ? (methodologyRaw[key] as string) : "--";
  }
  const paper = asRecord(result.paper);
  return {
    source: typeof result.source === "string" ? result.source : "unknown",
    warnings: Array.isArray(result.warnings) ? result.warnings.map(String).filter(Boolean) : [],
    metrics,
    diagnostics: asRecord(result.diagnostics) ?? {},
    methodology,
    doi: paper && typeof paper.doi === "string" ? paper.doi : "--",
    equityCurve: result.equity_curve as Array<Record<string, unknown>>,
    monthlyReturns: Array.isArray(result.monthly_returns)
      ? (result.monthly_returns as Array<Record<string, unknown>>)
      : [],
    positions: Array.isArray(result.positions)
      ? (result.positions as Array<Record<string, unknown>>)
      : [],
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function percentMetric(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? formatPercent(value) : "--";
}

function numberMetric(value: unknown, digits: number) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function FieldRenderer({
  factors,
  fieldName,
  schema,
  disabled,
  setValues,
  locale,
  universes,
  values,
  futuReachable = true,
}: {
  factors: FactorMetadata[];
  fieldName: string;
  schema: Record<string, unknown>;
  disabled: boolean;
  setValues: (updater: (current: Record<string, unknown>) => Record<string, unknown>) => void;
  locale: Locale;
  universes: UniverseDefinition[];
  values: Record<string, unknown>;
  futuReachable?: boolean;
}) {
  const type = String(schema.type ?? "text");
  if (type === "universe") {
    return (
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {label(fieldName, locale)}
        <select
          className={inputClass}
          disabled={disabled}
          onChange={(event) => update(fieldName, event.target.value, setValues)}
          value={String(values[fieldName] ?? schema.default ?? universes[0]?.id ?? "etf")}
        >
          {universes.map((universe) => (
            <option key={universe.id} value={universe.id}>
              {universe.name}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (type === "provider") {
    return (
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {label(fieldName, locale)}
        <select
          className={inputClass}
          disabled={disabled}
          onChange={(event) => update(fieldName, event.target.value, setValues)}
          value={String(values[fieldName] ?? schema.default ?? "futu")}
        >
          {["futu", "sample", "tiingo"].map((provider) => (
            <option
              key={provider}
              value={provider}
              disabled={provider === "futu" && !futuReachable}
            >
              {provider === "futu" ? futuOptionLabel(futuReachable, locale) : provider}
            </option>
          ))}
        </select>
        <FutuUnavailableHint reachable={futuReachable} locale={locale} />
      </label>
    );
  }
  if (type === "factor_multi_select") {
    const selected = asStringArray(values[fieldName] ?? schema.default);
    return (
      <div className="flex flex-col gap-2 font-body-sm text-text-primary">
        <div className="font-label-caps text-text-secondary">{label(fieldName, locale)}</div>
        {factors.map((factor) => (
          <label className="inline-flex items-center gap-2" key={factor.factor_id}>
            <input
              checked={selected.includes(factor.factor_id)}
              disabled={disabled}
              onChange={(event) => {
                const next = event.target.checked
                  ? [...selected, factor.factor_id]
                  : selected.filter((item) => item !== factor.factor_id);
                update(fieldName, next, setValues);
              }}
              type="checkbox"
            />
            {factor.factor_name}
          </label>
        ))}
      </div>
    );
  }
  if (type === "factor_weight_map") {
    const selected = asStringArray(values.factor_ids);
    const weights = (values[fieldName] as Record<string, unknown> | undefined) ?? {};
    return (
      <div className="flex flex-col gap-2 font-body-sm text-text-primary">
        <div className="font-label-caps text-text-secondary">{label(fieldName, locale)}</div>
        {selected.map((factorId) => (
          <label className="grid grid-cols-[1fr_96px] items-center gap-2" key={factorId}>
            <span>{factorId}</span>
            <input
              className="rounded-lg border border-border-subtle bg-bg-base px-2 py-1 font-data-mono text-text-primary disabled:opacity-50"
              disabled={disabled}
              onChange={(event) =>
                update(fieldName, { ...weights, [factorId]: Number(event.target.value) }, setValues)
              }
              step="0.1"
              type="number"
              value={String(weights[factorId] ?? 1)}
            />
          </label>
        ))}
      </div>
    );
  }
  if (type === "symbol_list") {
    return (
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {label(fieldName, locale)}
        <textarea
          className={`min-h-24 ${inputClass}`}
          disabled={disabled}
          onChange={(event) => update(fieldName, event.target.value, setValues)}
          value={asStringArray(values[fieldName] ?? schema.default).join(",")}
        />
      </label>
    );
  }
  const inputType = type === "date" ? "date" : type === "number" || type === "integer" || type === "integer_or_null" ? "number" : "text";
  return (
    <label className="flex flex-col gap-1 font-body-sm text-text-primary">
      {label(fieldName, locale)}
      <input
        className={inputClass}
        disabled={disabled}
        onChange={(event) => update(fieldName, event.target.value, setValues)}
        step={inputType === "number" ? "0.1" : undefined}
        type={inputType}
        value={String(values[fieldName] ?? schema.default ?? "")}
      />
    </label>
  );
}

function update(
  fieldName: string,
  value: unknown,
  setValues: (updater: (current: Record<string, unknown>) => Record<string, unknown>) => void,
) {
  setValues((current) => ({ ...current, [fieldName]: value }));
}

function flattenResult(result: Record<string, unknown>): PreviewRecord[] {
  return Object.entries(result)
    .filter(([key]) => key !== "safety")
    .slice(0, 20)
    .map(([key, value]) => ({
      key,
      value: typeof value === "object" ? JSON.stringify(value) : String(value),
    }));
}

function label(fieldName: string, locale: Locale) {
  return (
    fieldLabels[locale][fieldName as keyof typeof fieldLabels.en] ??
    fieldName.replaceAll("_", " ")
  );
}

function fallbackStrategies(): StrategyMetadata[] {
  return [
    {
      id: "cross_sectional_top_n",
      name: "Cross-Sectional Top-N",
      description: "",
      paper_source: null,
      run_endpoint: "/api/backtests/run",
      result_type: "backtest",
      parameter_schema: { fields: {} },
      default_payload: {},
    },
  ];
}
