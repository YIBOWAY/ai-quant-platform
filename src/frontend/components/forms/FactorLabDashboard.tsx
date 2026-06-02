'use client';

import Link from "next/link";
import type { ReactNode } from "react";
import { useState } from "react";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import type { FactorLabResponse, PreviewRecord } from "@/lib/api";
import { localizePath, type Locale } from "@/lib/locale";

type FactorRunSummary = {
  id: string;
  source?: string;
  row_count: number;
  signal_count: number;
};

type FactorLabDashboardProps = {
  dashboard: FactorLabResponse;
  latestRun?: FactorRunSummary | null;
  locale: Locale;
};

const copy = {
  en: {
    title: "Factor Lab",
    subtitle:
      "Read-only factor diagnostics. QQQ is the default timing symbol and benchmark, not the whole universe.",
    scope: "Scope",
    universe: "Universe",
    benchmark: "Benchmark",
    cache: "Cache",
    guardrails: "Guardrails",
    source: "Source",
    walkForward: "Walk-forward",
    leakage: "Leakage",
    status: "Status",
    generated: "Generated",
    exploratory: "Exploratory only",
    overfit: "Easy to overfit. Review walk-forward and leakage notes before using a factor elsewhere.",
    latestRun: "Latest saved run",
    noRun: "No saved run",
    openRun: "Open run",
    crossTab: "Cross-Sectional Health",
    timingTab: "Single-Ticker Timing",
    crossTitle: "Cross-Sectional Factor Health",
    crossDesc: "IC, decay, quantile spread, turnover, and coverage across the fixed universe.",
    timingTitle: "QQQ Timing Diagnostics",
    timingDesc: "Single-symbol z-score timing test for every registered factor.",
    emptyTitle: "No diagnostics",
    emptyDesc: "The backend did not return factor lab rows.",
  },
  zh: {
    title: "因子实验室",
    subtitle: "只读因子体检看板。QQQ 是默认择时标的和基准，不是唯一股票池。",
    scope: "范围",
    universe: "股票池",
    benchmark: "基准",
    cache: "缓存",
    guardrails: "护栏",
    source: "数据源",
    walkForward: "滚动验证",
    leakage: "泄漏检查",
    status: "状态",
    generated: "生成时间",
    exploratory: "仅用于探索",
    overfit: "容易过拟合。因子进入其他流程前，需要看滚动验证和泄漏检查。",
    latestRun: "最近保存结果",
    noRun: "暂无保存结果",
    openRun: "打开结果",
    crossTab: "横截面体检",
    timingTab: "单标的择时",
    crossTitle: "横截面因子体检",
    crossDesc: "在固定股票池内查看 IC、衰减、分位收益、换手和覆盖度。",
    timingTitle: "QQQ 择时诊断",
    timingDesc: "每个已登记因子在 QQQ 上的 z-score 择时测试。",
    emptyTitle: "暂无诊断",
    emptyDesc: "后端没有返回因子实验室数据。",
  },
} as const;

export function FactorLabDashboard({
  dashboard,
  latestRun,
  locale,
}: FactorLabDashboardProps) {
  const text = copy[locale];
  const [tab, setTab] = useState<"cross" | "timing">("cross");
  const rows =
    tab === "cross"
      ? dashboard.cross_sectional.rows
      : dashboard.timing.rows;

  return (
    <main className="flex h-full min-h-0 bg-base">
      <aside className="flex h-full w-[320px] shrink-0 flex-col overflow-y-auto border-r border-border-subtle bg-bg-surface p-4">
        <div>
          <h2 className="font-headline-lg text-text-primary">{text.title}</h2>
          <p className="mt-2 font-body-sm text-text-secondary">{text.subtitle}</p>
        </div>

        <section className="mt-5 rounded border border-border-subtle bg-surface-muted p-3">
          <div className="font-label-caps text-text-secondary">{text.scope}</div>
          <div className="mt-3 space-y-3 font-body-sm">
            <Metric label={text.universe} value={`${dashboard.universe.name} (${dashboard.universe.symbols.length})`} />
            <Metric label={text.benchmark} value={dashboard.benchmark_symbol} />
            <div>
              <div className="text-text-secondary">{text.source}</div>
              <div className="mt-1">
                <DataSourceBadge source={dashboard.source} />
              </div>
            </div>
          </div>
        </section>

        <section className="mt-4 rounded border border-border-subtle bg-surface-muted p-3">
          <div className="font-label-caps text-text-secondary">{text.guardrails}</div>
          <div className="mt-3 space-y-2 font-body-sm text-text-secondary">
            <div className="font-semibold text-warning">{text.exploratory}</div>
            <p>{text.overfit}</p>
            <Metric
              label={text.walkForward}
              value={String((dashboard.guardrails.walk_forward as Record<string, unknown> | undefined)?.fold_count ?? 0)}
            />
            <Metric
              label={text.leakage}
              value={String((dashboard.guardrails.leakage_audit as Record<string, unknown> | undefined)?.status ?? "--")}
            />
          </div>
        </section>

        <section className="mt-4 rounded border border-border-subtle bg-surface-muted p-3">
          <div className="font-label-caps text-text-secondary">{text.cache}</div>
          <div className="mt-3 space-y-2 font-body-sm">
            <Metric label={text.status} value={String(dashboard.cache.status ?? "--")} />
            <Metric label={text.generated} value={dashboard.generated_at?.slice(0, 19) ?? "--"} />
          </div>
        </section>

        <section className="mt-4 rounded border border-border-subtle bg-surface-muted p-3">
          <div className="font-label-caps text-text-secondary">{text.latestRun}</div>
          <div className="mt-2 truncate font-data-mono text-xs text-text-primary">
            {latestRun?.id ?? text.noRun}
          </div>
          {latestRun?.source ? (
            <div className="mt-2">
              <DataSourceBadge source={latestRun.source} />
            </div>
          ) : null}
          {latestRun ? (
            <Link
              aria-label={`Open ${latestRun.id}`}
              className="mt-3 inline-flex rounded border border-border-subtle px-3 py-1.5 font-body-sm text-info"
              href={localizePath(`/factor-lab/${latestRun.id}`, locale)}
            >
              {text.openRun}
            </Link>
          ) : null}
        </section>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        <div className="inline-flex w-fit rounded border border-border-subtle bg-bg-surface p-1">
          <TabButton active={tab === "cross"} onClick={() => setTab("cross")}>
            {text.crossTab}
          </TabButton>
          <TabButton active={tab === "timing"} onClick={() => setTab("timing")}>
            {text.timingTab}
          </TabButton>
        </div>

        <DataPreviewTable
          columns={
            tab === "cross"
              ? ["factor_id", "factor_name", "ic_mean", "ic_decay", "quantile_spread", "turnover", "coverage", "sample_count"]
              : ["factor_id", "factor_name", "sharpe", "max_drawdown", "win_rate", "trade_count", "coverage"]
          }
          description={tab === "cross" ? text.crossDesc : text.timingDesc}
          emptyDescription={text.emptyDesc}
          emptyTitle={text.emptyTitle}
          maxRows={50}
          rows={rows as PreviewRecord[]}
          title={tab === "cross" ? text.crossTitle : text.timingTitle}
        />
      </section>
    </main>
  );
}

function TabButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      className={`rounded px-3 py-1.5 font-body-sm ${
        active ? "bg-accent-success text-on-primary" : "text-text-secondary"
      }`}
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className="mt-1 break-all font-data-mono text-text-primary">{value}</div>
    </div>
  );
}
