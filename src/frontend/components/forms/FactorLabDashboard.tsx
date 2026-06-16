'use client';

import Link from "next/link";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge, SyntheticMetricsWarning, isSampleSource } from "@/components/DataSourceBadge";
import { GLOSSARY } from "@/components/InfoTip";
import { FactorLabControls, type FactorLabControlsInitial } from "@/components/forms/FactorLabControls";
import { FactorRunForm } from "@/components/forms/FactorRunForm";
import { Card, MetricStat, StatusPill } from "@/components/ui/primitives";
import { Tabs } from "@/components/ui/Tabs";
import type {
  FactorLabResponse,
  FactorRunSummary,
  PreviewRecord,
  UniverseDefinition,
} from "@/lib/api";
import { buildFactorLabBacktestHref } from "@/lib/factorLabHandoff";
import { localizePath, type Locale } from "@/lib/locale";

type FactorLabDashboardProps = {
  dashboard: FactorLabResponse;
  runs: FactorRunSummary[];
  hiddenSampleCount: number;
  universes: UniverseDefinition[];
  controlsInitial: FactorLabControlsInitial;
  locale: Locale;
};

const copy = {
  en: {
    title: "Factor Lab",
    subtitle: (symbol: string) =>
      `Read-only health diagnostics for every registered factor, plus a single-symbol timing sanity check on ${symbol}.`,
    workflow: "How to use: 1) adjust the query below · 2) read the health tables · 3) run a saved factor research for charts.",
    scope: "Query",
    sendToBacktest: "Send to Backtest",
    sendToBacktestDesc:
      "Prefills provider, universe, benchmark, and the registered factors. It does not run anything.",
    universe: "Universe",
    benchmark: "Benchmark",
    cache: "Cache",
    guardrails: "Guardrails",
    source: "Source",
    walkForward: "Walk-forward folds",
    leakage: "Leakage audit",
    status: "Status",
    generated: "Generated",
    exploratory: "Exploratory only",
    overfit: "Easy to overfit. Review walk-forward and leakage notes before using a factor elsewhere.",
    cacheStatus: { cached: "cached", recomputed: "recomputed" } as Record<string, string>,
    leakageMap: {
      basic_passed: { label: "passed", tone: "success" },
      pass: { label: "passed", tone: "success" },
      failed: { label: "FAILED", tone: "danger" },
      empty: { label: "no data", tone: "neutral" },
    } as Record<string, { label: string; tone: "success" | "danger" | "neutral" }>,
    runNew: "Run Factor Research",
    runNewDesc: "Computes factor values, scores, IC and quantile returns for your symbols, then opens the saved result with charts.",
    savedRuns: "Saved runs",
    noRun: "No saved runs yet — use the form above to create one.",
    openRun: "Open",
    hiddenSample: (n: number) => `${n} sample run(s) hidden —`,
    showSample: "show",
    factorsCard: "Registered factors",
    directionUp: "higher is better",
    directionDown: "lower is better",
    crossTab: "Cross-Sectional Health",
    timingTab: "Single-Ticker Timing",
    crossTitle: "Cross-Sectional Factor Health",
    crossDesc: "Per-factor predictive quality across the selected universe. Hover headers for definitions; values are 0-1 fractions.",
    timingTitle: (symbol: string) => `${symbol} Timing Diagnostics`,
    timingDesc: "Long-when-z-score-positive sanity test per factor on the timing symbol. '--' = never evaluated (no data).",
    emptyTitle: "No diagnostics",
    emptyDesc: "The backend did not return factor lab rows. If the provider is futu, make sure OpenD is running, or switch the data source above.",
    columns: {
      factor_id: "Factor ID",
      factor_name: "Name",
      direction: "Direction",
      ic_mean: "Rank IC (h1)",
      ic_decay: "IC Decay (h5−h1)",
      quantile_spread: "Quantile Spread",
      turnover: "Turnover",
      coverage: "Coverage",
      sample_count: "Samples",
      sharpe: "Sharpe",
      max_drawdown: "Max Drawdown",
      win_rate: "Win Rate",
      trade_count: "Trades",
    } as Record<string, string>,
  },
  zh: {
    title: "因子实验室",
    subtitle: (symbol: string) =>
      `所有已登记因子的只读体检看板，外加在 ${symbol} 上的单标的择时抽检。`,
    workflow: "用法：1) 在下方调整查询 · 2) 阅读体检表 · 3) 运行一次因子研究查看图表。",
    scope: "查询",
    sendToBacktest: "发送至回测",
    sendToBacktestDesc: "预填数据源、股票池、基准和已登记因子；不会自动运行回测。",
    universe: "股票池",
    benchmark: "基准",
    cache: "缓存",
    guardrails: "护栏",
    source: "数据源",
    walkForward: "滚动验证折数",
    leakage: "泄漏检查",
    status: "状态",
    generated: "生成时间",
    exploratory: "仅用于探索",
    overfit: "容易过拟合。因子进入其他流程前，需要看滚动验证和泄漏检查。",
    cacheStatus: { cached: "已缓存", recomputed: "新计算" } as Record<string, string>,
    leakageMap: {
      basic_passed: { label: "通过", tone: "success" },
      pass: { label: "通过", tone: "success" },
      failed: { label: "未通过", tone: "danger" },
      empty: { label: "无数据", tone: "neutral" },
    } as Record<string, { label: string; tone: "success" | "danger" | "neutral" }>,
    runNew: "运行因子研究",
    runNewDesc: "对你给定的标的计算因子值、评分、IC 与分位收益，完成后打开带图表的保存结果。",
    savedRuns: "已保存运行",
    noRun: "暂无保存结果——用上方表单创建一次。",
    openRun: "打开",
    hiddenSample: (n: number) => `已隐藏 ${n} 条 sample 演示运行 ——`,
    showSample: "显示",
    factorsCard: "已登记因子",
    directionUp: "越高越好",
    directionDown: "越低越好",
    crossTab: "横截面体检",
    timingTab: "单标的择时",
    crossTitle: "横截面因子体检",
    crossDesc: "各因子在所选股票池内的预测质量。悬停列头看定义；数值为 0-1 小数。",
    timingTitle: (symbol: string) => `${symbol} 择时诊断`,
    timingDesc: "每个因子在择时标的上的「z 分数为正则做多」抽检。“--” = 没有可评估数据。",
    emptyTitle: "暂无诊断",
    emptyDesc: "后端没有返回因子实验室数据。若数据源为 futu，请确认 OpenD 已启动，或在上方切换数据源。",
    columns: {
      factor_id: "因子 ID",
      factor_name: "名称",
      direction: "方向",
      ic_mean: "Rank IC 均值 (h1)",
      ic_decay: "IC 衰减 (h5−h1)",
      quantile_spread: "分位价差",
      turnover: "换手",
      coverage: "覆盖率",
      sample_count: "样本数",
      sharpe: "夏普",
      max_drawdown: "最大回撤",
      win_rate: "胜率",
      trade_count: "交易数",
    } as Record<string, string>,
  },
} as const;

const SECTION_LABEL = "font-label-caps text-text-secondary";

export function FactorLabDashboard({
  dashboard,
  runs,
  hiddenSampleCount,
  universes,
  controlsInitial,
  locale,
}: FactorLabDashboardProps) {
  const text = copy[locale];
  const timingSymbol = dashboard.timing.symbol || "QQQ";
  const backtestHref = buildFactorLabBacktestHref({
    benchmarkSymbol: controlsInitial.benchmarkSymbol,
    end: controlsInitial.end,
    factorIds: dashboard.factors.map((factor) => factor.factor_id),
    locale,
    lookback: controlsInitial.lookback,
    provider: controlsInitial.provider,
    start: controlsInitial.start,
    universeId: controlsInitial.universeId,
  });

  const walkForwardFolds = String(dashboard.guardrails.walk_forward.fold_count);
  const leakageRaw = dashboard.guardrails.leakage_audit.status.toLowerCase();
  const leakage = text.leakageMap[leakageRaw] ?? { label: leakageRaw, tone: "neutral" as const };
  const cacheStatusRaw = String(dashboard.cache.status ?? "--");
  const cacheStatus = text.cacheStatus[cacheStatusRaw] ?? cacheStatusRaw;

  const columnTips: Record<string, string> = {
    ic_mean: GLOSSARY.rankIc[locale],
    ic_decay: GLOSSARY.icDecay[locale],
    quantile_spread: GLOSSARY.quantileSpread[locale],
    turnover: GLOSSARY.turnover[locale],
    coverage: GLOSSARY.coverage[locale],
    sharpe: GLOSSARY.sharpe[locale],
    max_drawdown: GLOSSARY.maxDrawdown[locale],
    win_rate: GLOSSARY.winRate[locale],
    direction: locale === "zh" ? "因子值越高越好还是越低越好（决定 IC 正负怎么读）。" : "Whether higher or lower factor values are better (how to read the IC sign).",
  };

  const crossRows = (dashboard.cross_sectional.rows as PreviewRecord[]).map((row) => ({
    ...row,
    direction:
      String(row.direction ?? "") === "lower_is_better" ? text.directionDown :
      String(row.direction ?? "") === "higher_is_better" ? text.directionUp :
      String(row.direction ?? "--"),
  }));
  const timingRows = (dashboard.timing.rows as PreviewRecord[]).map((row) => {
    const noData = Number(row.trade_count ?? 0) === 0 && Number(row.coverage ?? 0) === 0;
    if (!noData) return row;
    return {
      ...row,
      sharpe: "--",
      max_drawdown: "--",
      win_rate: "--",
      trade_count: "--",
      coverage: "--",
    };
  });

  const tabItems = [
    {
      id: "cross",
      label: text.crossTab,
      content: (
        <DataPreviewTable
          columns={[
            "factor_id",
            "factor_name",
            "direction",
            "ic_mean",
            "ic_decay",
            "quantile_spread",
            "turnover",
            "coverage",
            "sample_count",
          ]}
          columnLabels={text.columns}
          columnTips={columnTips}
          description={text.crossDesc}
          emptyDescription={text.emptyDesc}
          emptyTitle={text.emptyTitle}
          locale={locale}
          maxRows={50}
          rows={crossRows}
          title={text.crossTitle}
        />
      ),
    },
    {
      id: "timing",
      label: text.timingTab,
      content: (
        <DataPreviewTable
          columns={[
            "factor_id",
            "factor_name",
            "sharpe",
            "max_drawdown",
            "win_rate",
            "trade_count",
            "coverage",
          ]}
          columnLabels={text.columns}
          columnTips={columnTips}
          description={text.timingDesc}
          emptyDescription={text.emptyDesc}
          emptyTitle={text.emptyTitle}
          locale={locale}
          maxRows={50}
          rows={timingRows}
          title={text.timingTitle(timingSymbol)}
        />
      ),
    },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg-base lg:flex-row">
      <aside className="flex w-full shrink-0 flex-col gap-4 overflow-y-auto border-b border-border-subtle bg-bg-surface p-4 lg:h-full lg:w-[320px] lg:border-b-0 lg:border-r">
        <div>
          <h2 className="font-headline-lg text-text-primary">{text.title}</h2>
          <p className="mt-2 font-body-sm text-text-secondary">{text.subtitle(timingSymbol)}</p>
          <p className="mt-2 font-body-sm text-text-secondary/80">{text.workflow}</p>
        </div>

        <Card padded={false}>
          <div className="flex items-center justify-between gap-2 border-b border-border-subtle px-3 py-2">
            <span className={SECTION_LABEL}>{text.scope}</span>
            <DataSourceBadge source={dashboard.source} />
          </div>
          <div className="p-3">
            <FactorLabControls initial={controlsInitial} locale={locale} universes={universes} />
          </div>
          <div className="border-t border-border-subtle px-3 py-3">
            <Link
              className="inline-flex w-full items-center justify-center rounded-lg bg-accent-success px-3 py-2 font-body-sm font-semibold text-on-primary transition-opacity hover:opacity-90"
              href={backtestHref}
            >
              {text.sendToBacktest}
            </Link>
            <p className="mt-2 font-body-sm text-text-secondary">{text.sendToBacktestDesc}</p>
          </div>
          <div className="divide-y divide-border-subtle/60 border-t border-border-subtle">
            <MetricStat
              size="inline"
              label={text.universe}
              value={`${dashboard.universe.name} · ${dashboard.universe.symbols.length || "--"}`}
              hint={dashboard.universe.symbols.join(", ")}
            />
            <MetricStat size="inline" label={text.benchmark} value={dashboard.benchmark_symbol} />
          </div>
        </Card>

        <Card padded={false}>
          <div className="border-b border-border-subtle px-3 py-2">
            <span className={SECTION_LABEL}>{text.runNew}</span>
            <p className="mt-1 font-body-sm text-text-secondary">{text.runNewDesc}</p>
          </div>
          <div className="p-3">
            <FactorRunForm locale={locale} />
          </div>
        </Card>

        <Card padded={false}>
          <div className="border-b border-border-subtle px-3 py-2">
            <span className={SECTION_LABEL}>{text.savedRuns}</span>
          </div>
          <div className="p-3">
            {runs.length ? (
              <ul className="space-y-2">
                {runs.slice(0, 5).map((run) => (
                  <li className="flex items-center justify-between gap-2" key={run.id}>
                    <span className="min-w-0 truncate font-data-mono text-xs text-text-primary" title={run.id}>
                      {run.id}
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      {run.source ? <DataSourceBadge source={run.source} /> : null}
                      <Link
                        aria-label={`Open ${run.id}`}
                        className="font-body-sm text-info underline-offset-2 hover:underline"
                        href={localizePath(`/factor-lab/${run.id}`, locale)}
                      >
                        {text.openRun}
                      </Link>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="font-body-sm text-text-secondary">{text.noRun}</p>
            )}
            {hiddenSampleCount > 0 ? (
              <p className="mt-2 font-body-sm text-text-secondary">
                {text.hiddenSample(hiddenSampleCount)}{" "}
                <Link className="text-info underline underline-offset-2" href="?include_sample=1">
                  {text.showSample}
                </Link>
              </p>
            ) : null}
          </div>
        </Card>

        <Card tone="warning" padded={false}>
          <div className="border-b border-warning/40 px-3 py-2">
            <span className="font-label-caps text-warning">{text.guardrails}</span>
          </div>
          <div className="space-y-3 p-3">
            <p className="font-body-sm text-text-secondary">{text.overfit}</p>
            <div className="flex flex-wrap gap-2">
              <StatusPill label={text.status} value={text.exploratory} tone="warning" />
              <StatusPill label={text.walkForward} value={walkForwardFolds} tone="neutral" />
              <StatusPill label={text.leakage} value={leakage.label} tone={leakage.tone} />
            </div>
          </div>
        </Card>

        {dashboard.factors.length ? (
          <Card padded={false}>
            <details>
              <summary className="cursor-pointer px-3 py-2 font-label-caps text-text-secondary transition-colors hover:text-text-primary">
                {text.factorsCard} · {dashboard.factors.length}
              </summary>
              <ul className="space-y-2 border-t border-border-subtle p-3">
                {dashboard.factors.map((factor) => (
                  <li key={factor.factor_id}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-data-mono text-xs text-text-primary">{factor.factor_name}</span>
                      <span className="font-label-caps text-[10px] text-text-secondary">
                        {factor.direction === "lower_is_better" ? text.directionDown : text.directionUp}
                      </span>
                    </div>
                    {factor.description ? (
                      <p className="mt-0.5 font-body-sm text-text-secondary">{factor.description}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </details>
          </Card>
        ) : null}

        <Card padded={false}>
          <div className="border-b border-border-subtle px-3 py-2">
            <span className={SECTION_LABEL}>{text.cache}</span>
          </div>
          <div className="divide-y divide-border-subtle/60">
            <MetricStat size="inline" label={text.status} value={cacheStatus} />
            <MetricStat
              size="inline"
              label={text.generated}
              value={dashboard.generated_at?.slice(0, 19).replace("T", " ") ?? "--"}
            />
          </div>
        </Card>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        <SyntheticMetricsWarning source={isSampleSource(dashboard.source) ? dashboard.source : null} locale={locale} />
        <Tabs items={tabItems} defaultId="cross" />
      </section>
    </div>
  );
}
