import Link from "next/link";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { FactorRunForm } from "@/components/forms/FactorRunForm";
import { getFactorRunDetail, getFactorRuns, getFactors } from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };

const copy = {
  en: {
    factorDefinition: "Factor Definition",
    guideTitle: "What to use this for",
    guideBody:
      "Use this page to test whether a signal such as momentum or volatility has useful historical behavior before it becomes part of a strategy.",
    availableFactors: "AVAILABLE FACTORS",
    currentMetadata: "CURRENT METADATA",
    noFactorLoaded: "No factor loaded",
    latestRun: "LATEST RUN",
    noFactorRunYet: "No factor run yet",
    openRunAria: (id: string) => `Open ${id}`,
    openRun: "Open run",
    analysisConfig: "Analysis Config",
    factorValuesTitle: "Factor Values",
    factorValuesDesc: "Latest factor result rows from the API run.",
    factorValuesEmptyTitle: "Factor values not loaded",
    factorValuesEmptyDesc: "Run factor analysis to create a real factor result file.",
    signalScoresTitle: "Signal Scores",
    signalScoresDesc: "Latest combined score rows prepared for later strategy use.",
    signalScoresEmptyTitle: "Signals unavailable",
    signalScoresEmptyDesc: "Signals appear after a factor run completes.",
    icReportTitle: "IC Report",
    icReportDesc: "Information coefficient rows from the latest run.",
    icReportEmptyTitle: "IC report unavailable",
    icReportEmptyDesc: "IC and Rank IC require a completed factor run.",
    quantileReturnsTitle: "Quantile Returns",
    quantileReturnsDesc: "Grouped return rows from the latest run.",
    quantileReturnsEmptyTitle: "Quantile returns unavailable",
    quantileReturnsEmptyDesc: "Grouped returns are not shown until the backend produces them.",
    noRunsTitle: "No factor runs yet",
    noRunsDesc: "Use the form on the left to generate the first factor research result.",
  },
  zh: {
    factorDefinition: "因子定义",
    guideTitle: "这个页面用来做什么",
    guideBody:
      "这里用来验证一个信号，比如动量或波动率，过去是否真的有用；确认后才适合进入策略研究。",
    availableFactors: "可用因子",
    currentMetadata: "当前元数据",
    noFactorLoaded: "未加载因子",
    latestRun: "最新运行",
    noFactorRunYet: "暂无因子运行",
    openRunAria: (id: string) => `打开 ${id}`,
    openRun: "打开运行",
    analysisConfig: "分析配置",
    factorValuesTitle: "因子值",
    factorValuesDesc: "来自 API 运行的最新因子结果行。",
    factorValuesEmptyTitle: "未加载因子值",
    factorValuesEmptyDesc: "运行因子分析以生成真实的因子结果文件。",
    signalScoresTitle: "信号评分",
    signalScoresDesc: "为后续策略使用准备的最新综合评分行。",
    signalScoresEmptyTitle: "暂无信号",
    signalScoresEmptyDesc: "因子运行完成后才会出现信号。",
    icReportTitle: "IC 报告",
    icReportDesc: "来自最新运行的信息系数行。",
    icReportEmptyTitle: "IC 报告不可用",
    icReportEmptyDesc: "IC 与 Rank IC 需要已完成的因子运行。",
    quantileReturnsTitle: "分位收益",
    quantileReturnsDesc: "来自最新运行的分组收益行。",
    quantileReturnsEmptyTitle: "分位收益不可用",
    quantileReturnsEmptyDesc: "在后端生成之前不会显示分组收益。",
    noRunsTitle: "暂无因子运行",
    noRunsDesc: "使用左侧表单生成第一个因子研究结果。",
  },
};

export default async function FactorLab() {
  const locale = await getServerLocale();
  const text = copy[locale];
  const [factors, factorRuns] = await Promise.all([getFactors(), getFactorRuns()]);
  const latestRun = factorRuns.runs[0];
  const latestDetail = latestRun ? await getFactorRunDetail(latestRun.id) : null;
  const firstFactor = factors.factors[0];

  return (
    <main className="h-full overflow-y-auto p-container-padding">
      <div className="mb-4">
        <ErrorBanner
          messages={[factors.apiError, factorRuns.apiError, latestDetail?.apiError]}
        />
      </div>
      <div className="flex gap-6">
        <aside className="flex w-[300px] flex-shrink-0 flex-col gap-6">
          <div className="rounded border border-border-subtle bg-bg-surface p-4">
            <h2 className="mb-4 font-headline-lg text-text-primary">{text.factorDefinition}</h2>
            <div className="mb-4 rounded border border-info/30 bg-info/10 p-3">
              <div className="font-label-caps text-info">{text.guideTitle}</div>
              <p className="mt-1 font-body-sm text-text-secondary">{text.guideBody}</p>
            </div>
            <div className="flex flex-col gap-stack-gap">
              <div className="flex flex-col gap-1">
                <label className="font-label-caps text-text-secondary">{text.availableFactors}</label>
                <select className="w-full rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-mono focus:border-accent-success focus:outline-none">
                  {factors.factors.map((factor) => (
                    <option key={factor.factor_id} style={optionStyle}>
                      {factor.factor_id}
                    </option>
                  ))}
                </select>
              </div>
              <div className="mt-2 flex flex-col gap-1">
                <label className="font-label-caps text-text-secondary">{text.currentMetadata}</label>
                <pre className="rounded border border-border-subtle bg-surface-muted p-3 font-code-sm text-text-mono">
                  {firstFactor
                    ? JSON.stringify(
                        {
                          factor_id: firstFactor.factor_id,
                          lookback: firstFactor.lookback,
                          direction: firstFactor.direction,
                        },
                        null,
                        2,
                      )
                    : text.noFactorLoaded}
                </pre>
              </div>
              <div className="mt-2 flex flex-col gap-1">
                <label className="font-label-caps text-text-secondary">{text.latestRun}</label>
                <div className="rounded border border-border-subtle bg-surface-muted p-3 font-data-mono text-xs text-text-primary">
                  <div className="truncate">{latestRun?.id ?? text.noFactorRunYet}</div>
                  {latestRun?.source ? (
                    <div className="mt-2">
                      <DataSourceBadge source={latestRun.source} />
                    </div>
                  ) : null}
                  <div className="mt-2 text-text-secondary">
                    rows={latestRun?.row_count ?? 0} signals={latestRun?.signal_count ?? 0}
                  </div>
                  {latestRun ? (
                    <Link
                      aria-label={text.openRunAria(latestRun.id)}
                      className="mt-3 inline-flex rounded border border-border-subtle px-3 py-1.5 font-body-sm text-info"
                      href={`/factor-lab/${latestRun.id}`}
                    >
                      {text.openRun}
                    </Link>
                  ) : null}
                </div>
              </div>
            </div>
          </div>

          <div className="rounded border border-border-subtle bg-bg-surface p-4">
            <h2 className="mb-4 font-headline-lg text-text-primary">{text.analysisConfig}</h2>
            <FactorRunForm locale={locale} />
          </div>
        </aside>

        <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
          <DataPreviewTable
            title={text.factorValuesTitle}
            description={text.factorValuesDesc}
            rows={latestDetail?.factor_results ?? []}
            emptyTitle={text.factorValuesEmptyTitle}
            emptyDescription={text.factorValuesEmptyDesc}
            columns={["factor_id", "symbol", "signal_ts", "tradeable_ts", "value"]}
          />
          <DataPreviewTable
            title={text.signalScoresTitle}
            description={text.signalScoresDesc}
            rows={latestDetail?.signals ?? []}
            emptyTitle={text.signalScoresEmptyTitle}
            emptyDescription={text.signalScoresEmptyDesc}
            columns={["symbol", "signal_ts", "tradeable_ts", "score"]}
          />
          <DataPreviewTable
            title={text.icReportTitle}
            description={text.icReportDesc}
            rows={latestDetail?.information_coefficients ?? []}
            emptyTitle={text.icReportEmptyTitle}
            emptyDescription={text.icReportEmptyDesc}
          />
          <DataPreviewTable
            title={text.quantileReturnsTitle}
            description={text.quantileReturnsDesc}
            rows={latestDetail?.quantile_returns ?? []}
            emptyTitle={text.quantileReturnsEmptyTitle}
            emptyDescription={text.quantileReturnsEmptyDesc}
          />
          {!latestRun ? (
            <div className="lg:col-span-2">
              <EmptyState
                title={text.noRunsTitle}
                description={text.noRunsDesc}
              />
            </div>
          ) : null}
        </div>
      </div>
    </main>
  );
}
