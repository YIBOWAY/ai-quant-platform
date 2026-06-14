import Link from "next/link";
import { FlaskConical } from "lucide-react";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge, SyntheticMetricsWarning } from "@/components/DataSourceBadge";
import { ErrorBanner } from "@/components/ErrorBanner";
import { ICLineChart, QuantileReturnChart } from "@/components/FactorRunCharts";
import { MetricStat, PageHeader, StatusPill } from "@/components/ui/primitives";
import { getFactorRunDetail } from "@/lib/api";
import { localizePath } from "@/lib/locale";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    eyebrow: "Factor Lab",
    title: "Factor Run Detail",
    back: "Back to Factor Lab",
    intro:
      "A saved factor research run: factor values, signal scores, per-date IC and quantile returns for the symbols you chose.",
    rows: "Rows",
    signals: "Signals",
    icRows: "IC Rows",
    runNotes: "Run notes",
    factorValues: "Factor Values",
    factorValuesDesc: "Factor value rows saved by this run.",
    factorValuesEmpty: "No factor result rows were saved for this run.",
    signalScores: "Signal Scores",
    signalScoresDesc: "Signal score rows saved by this run.",
    signalScoresEmpty: "No signal rows were saved for this run.",
    icReport: "IC Report",
    icReportDesc: "Per-date information coefficients (charted above).",
    icReportEmpty: "No IC rows were saved for this run.",
    quantileReturns: "Quantile Returns",
    quantileReturnsDesc: "Per-quantile forward returns (charted above).",
    quantileReturnsEmpty: "No quantile return rows were saved for this run.",
    metadata: "Metadata",
    metadataDesc: "Run request and saved output paths.",
    metadataEmpty: "Metadata is empty for this run.",
    columns: {
      factor_id: "Factor",
      symbol: "Symbol",
      signal_ts: "Signal Date",
      tradeable_ts: "Tradeable",
      value: "Value",
      score: "Score",
      ic: "IC",
      rank_ic: "Rank IC",
      n: "N",
      quantile: "Quantile",
      mean_forward_return: "Mean Fwd Return",
      median_forward_return: "Median Fwd Return",
      count: "Count",
      key: "Key",
      value_meta: "Value",
    } as Record<string, string>,
    params: {
      symbols: "Symbols",
      start: "Start",
      end: "End",
      provider: "Provider",
      lookback: "Lookback",
      quantiles: "Quantiles",
    } as Record<string, string>,
  },
  zh: {
    eyebrow: "因子实验室",
    title: "因子运行详情",
    back: "返回因子实验室",
    intro: "一次已保存的因子研究运行：你所选标的的因子值、信号评分、逐日 IC 与分位收益。",
    rows: "数据行",
    signals: "信号数",
    icRows: "IC 行数",
    runNotes: "运行提示",
    factorValues: "因子值",
    factorValuesDesc: "本次运行保存的因子值。",
    factorValuesEmpty: "本次运行没有保存因子值数据。",
    signalScores: "信号评分",
    signalScoresDesc: "本次运行保存的信号评分。",
    signalScoresEmpty: "本次运行没有保存信号数据。",
    icReport: "IC 报告",
    icReportDesc: "逐日信息系数（上方已绘制成图）。",
    icReportEmpty: "本次运行没有保存 IC 数据。",
    quantileReturns: "分位收益",
    quantileReturnsDesc: "各分位组的未来收益（上方已绘制成图）。",
    quantileReturnsEmpty: "本次运行没有保存分位收益数据。",
    metadata: "元数据",
    metadataDesc: "运行请求与保存路径。",
    metadataEmpty: "本次运行没有元数据。",
    columns: {
      factor_id: "因子",
      symbol: "标的",
      signal_ts: "信号日期",
      tradeable_ts: "可交易日",
      value: "数值",
      score: "评分",
      ic: "IC",
      rank_ic: "Rank IC",
      n: "样本数",
      quantile: "分位",
      mean_forward_return: "平均未来收益",
      median_forward_return: "中位未来收益",
      count: "数量",
      key: "键",
      value_meta: "值",
    } as Record<string, string>,
    params: {
      symbols: "标的",
      start: "开始",
      end: "结束",
      provider: "数据源",
      lookback: "回看",
      quantiles: "分位数",
    } as Record<string, string>,
  },
} as const;

type FactorRunDetailPageProps = {
  params?: Promise<{ runId?: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function FactorRunDetailPage({ params, searchParams }: FactorRunDetailPageProps) {
  const runId = (await params)?.runId ?? "";
  const query = (await searchParams) ?? {};
  const locale = await getServerLocale(query);
  const text = copy[locale];
  const detail = await getFactorRunDetail(runId);
  const metadata = detail.metadata ?? {};
  const source = typeof metadata.source === "string" ? metadata.source : undefined;
  const warnings = arrayOfStrings(metadata.warnings);
  const request =
    typeof metadata.request === "object" && metadata.request !== null
      ? (metadata.request as Record<string, unknown>)
      : null;

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto bg-bg-base p-5">
      <ErrorBanner locale={locale} messages={[detail.apiError]} />
      <PageHeader
        eyebrow={text.eyebrow}
        icon={<FlaskConical size={18} className="text-accent-success" />}
        title={text.title}
        subtitle={text.intro}
        actions={
          <Link
            className="rounded-lg border border-border-subtle px-3 py-2 font-body-sm text-text-primary transition-colors hover:bg-bg-surface-muted"
            href={localizePath("/factor-lab", locale)}
          >
            {text.back}
          </Link>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-data-mono text-xs text-text-secondary">{runId}</span>
        {source ? <DataSourceBadge source={source} /> : null}
      </div>
      <SyntheticMetricsWarning source={source} locale={locale} />

      {request ? (
        <div className="flex flex-wrap gap-2">
          {Object.entries(text.params).map(([key, label]) => {
            const raw = request[key];
            if (raw === undefined || raw === null || raw === "") return null;
            const value = Array.isArray(raw) ? raw.join(",") : String(raw);
            return <StatusPill key={key} label={label} value={value} tone="neutral" />;
          })}
        </div>
      ) : null}

      <section className="grid gap-3 md:grid-cols-3">
        <MetricStat label={text.rows} value={String(metadata.row_count ?? detail.factor_results.length)} />
        <MetricStat label={text.signals} value={String(metadata.signal_count ?? detail.signals.length)} />
        <MetricStat label={text.icRows} value={String(detail.information_coefficients.length)} />
      </section>
      <WarningsPanel title={text.runNotes} warnings={warnings} />

      <section className="grid gap-4 xl:grid-cols-2">
        <ICLineChart locale={locale} rows={detail.information_coefficients} />
        <QuantileReturnChart locale={locale} rows={detail.quantile_returns} />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <DataPreviewTable
          columns={["factor_id", "symbol", "signal_ts", "tradeable_ts", "value"]}
          columnLabels={text.columns}
          description={text.factorValuesDesc}
          emptyDescription={text.factorValuesEmpty}
          emptyTitle={text.factorValues}
          locale={locale}
          maxRows={15}
          rows={detail.factor_results}
          title={text.factorValues}
        />
        <DataPreviewTable
          columns={["symbol", "signal_ts", "tradeable_ts", "score"]}
          columnLabels={text.columns}
          description={text.signalScoresDesc}
          emptyDescription={text.signalScoresEmpty}
          emptyTitle={text.signalScores}
          locale={locale}
          maxRows={15}
          rows={detail.signals}
          title={text.signalScores}
        />
        <DataPreviewTable
          columnLabels={text.columns}
          description={text.icReportDesc}
          emptyDescription={text.icReportEmpty}
          emptyTitle={text.icReport}
          locale={locale}
          maxRows={15}
          rows={detail.information_coefficients}
          title={text.icReport}
        />
        <DataPreviewTable
          columnLabels={text.columns}
          description={text.quantileReturnsDesc}
          emptyDescription={text.quantileReturnsEmpty}
          emptyTitle={text.quantileReturns}
          locale={locale}
          maxRows={15}
          rows={detail.quantile_returns}
          title={text.quantileReturns}
        />
        <div className="lg:col-span-2">
          <DataPreviewTable
            columnLabels={{ key: text.columns.key, value: text.columns.value_meta }}
            description={text.metadataDesc}
            emptyDescription={text.metadataEmpty}
            emptyTitle={text.metadata}
            locale={locale}
            maxRows={20}
            rows={objectRows(metadata)}
            title={text.metadata}
          />
        </div>
      </section>
    </div>
  );
}

function WarningsPanel({ title, warnings }: { title: string; warnings: string[] }) {
  if (!warnings.length) {
    return null;
  }
  return (
    <section className="rounded-lg border border-warning/40 bg-warning/10 p-4 text-warning">
      <h2 className="font-label-caps">{title}</h2>
      <ul className="mt-2 space-y-1 font-body-sm">
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
    </section>
  );
}

function arrayOfStrings(value: unknown) {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function objectRows(value: unknown) {
  if (typeof value !== "object" || value === null) {
    return [];
  }
  return Object.entries(value as Record<string, unknown>).map(([key, item]) => ({
    key,
    value: typeof item === "object" && item !== null ? JSON.stringify(item) : item,
  }));
}
