import Link from "next/link";
import {
  Activity,
  ArrowUpRight,
  Bot,
  BriefcaseBusiness,
  Database,
  FlaskConical,
  LineChart,
  Newspaper,
  ShieldCheck,
} from "lucide-react";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { ErrorBanner } from "@/components/ErrorBanner";
import {
  formatMoney,
  formatPercent,
  getAgentCandidates,
  getBacktests,
  getFactors,
  getPaperRuns,
  getRecentRuns,
  getSymbols,
  type RecentRun,
} from "@/lib/api";
import {
  dashboardRunHref,
  dashboardRunKindLabel,
  dashboardRunSummary,
  formatCount,
} from "@/lib/dashboardRuns";
import { localizePath } from "@/lib/locale";
import { selectDisplayRun } from "@/lib/runSource";
import { getCachedHealth } from "@/lib/serverApi";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    eyebrow: "Hermes trial",
    title: "Morning Brief",
    deck:
      "A template lede for the research day: one quiet read of factors, simulated capital, recent runs, and candidates awaiting human review.",
    factLine: "Compiled from platform facts",
    safetyContract: "Safety: paper-only research; live trading never implied active.",
    status: "Environment",
    api: "API",
    paperTrading: "Paper trading",
    liveTrading: "Live trading",
    killSwitch: "Kill switch",
    on: "on",
    off: "off",
    factorCount: "Registered factors",
    paperEquity: "Paper equity",
    latestSharpe: "Latest Sharpe",
    candidateQueue: "Candidate queue",
    candidateQueueDetail: "agent candidates",
    runs: "runs",
    source: "source",
    marketTape: "Artifact tape",
    symbols: "Symbols",
    backtest: "Latest backtest",
    paperRun: "Latest paper run",
    noBacktest: "No backtest run yet",
    noPaper: "No paper run yet",
    totalReturn: "Return",
    maxDrawdown: "Max DD",
    orders: "Orders",
    breaches: "Breaches",
    runLog: "Recent run log",
    runLogEmpty:
      "No recent runs yet. When the workbench writes read-only artifacts, they will appear here.",
    candidateBrief: "Candidate brief",
    noCandidate: "No candidate awaiting review.",
    candidateStatus: "Status",
    candidateGoal: "Goal",
    readOnly: "Read-only snapshot",
    candidateRef: "Artifact ref",
  },
  zh: {
    eyebrow: "Hermes 试跑",
    title: "晨报",
    deck: "一段 template lede：把因子、模拟资金、近期运行和待人工复核候选，压缩成开盘前的一屏研究摘要。",
    factLine: "Compiled from platform facts",
    safetyContract: "安全：仅模拟研究；live trading never implied active。",
    status: "环境",
    api: "接口",
    paperTrading: "模拟交易",
    liveTrading: "实盘交易",
    killSwitch: "熔断开关",
    on: "开",
    off: "关",
    factorCount: "已注册因子",
    paperEquity: "模拟权益",
    latestSharpe: "最新夏普",
    candidateQueue: "候选队列",
    candidateQueueDetail: "智能体候选",
    runs: "次运行",
    source: "来源",
    marketTape: "Artifact 轨迹",
    symbols: "标的",
    backtest: "最新回测",
    paperRun: "最新模拟运行",
    noBacktest: "暂无回测运行",
    noPaper: "暂无模拟运行",
    totalReturn: "收益",
    maxDrawdown: "最大回撤",
    orders: "订单",
    breaches: "风控触发",
    runLog: "近期运行日志",
    runLogEmpty: "暂无近期运行。工作台写入只读 artifact 后，会出现在这里。",
    candidateBrief: "候选简报",
    noCandidate: "暂无待复核候选。",
    candidateStatus: "状态",
    candidateGoal: "目标",
    readOnly: "只读快照",
    candidateRef: "Artifact 引用",
  },
} as const;

type BriefCopy = (typeof copy)["en"] | (typeof copy)["zh"];

function formatRunTimestamp(value?: string | null) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function boolLabel(value: boolean | undefined, text: BriefCopy) {
  if (value === undefined) {
    return "--";
  }
  return value ? text.on : text.off;
}

function runIcon(run: RecentRun) {
  if (run.kind === "backtest") {
    return <LineChart size={14} className="text-editorial-accent" />;
  }
  if (run.kind === "factor") {
    return <FlaskConical size={14} className="text-warning" />;
  }
  if (run.kind === "replication") {
    return <Database size={14} className="text-info" />;
  }
  return <BriefcaseBusiness size={14} className="text-editorial-up" />;
}

function StatLine({
  label,
  value,
  detail,
}: {
  label: string;
  value: string | number;
  detail?: string;
}) {
  return (
    <div className="min-w-0 border-t border-editorial-rule py-3 sm:py-4">
      <div className="font-label-caps text-ink-secondary">{label}</div>
      <div className="mt-2 truncate font-data-mono text-lg text-ink sm:text-xl">{value}</div>
      {detail ? <div className="mt-1 break-words font-data-mono text-xs text-ink-secondary">{detail}</div> : null}
    </div>
  );
}

function SafetyRow({
  label,
  value,
  emphasis,
}: {
  label: string;
  value: string;
  emphasis?: "safe" | "warn";
}) {
  const valueClass =
    emphasis === "safe"
      ? "text-editorial-up"
      : emphasis === "warn"
        ? "text-warning"
        : "text-ink";
  return (
    <div className="flex items-center justify-between gap-4 border-t border-editorial-rule py-3">
      <span className="font-label-caps text-ink-secondary">{label}</span>
      <span className={`font-data-mono text-sm ${valueClass}`}>{value}</span>
    </div>
  );
}

export default async function BriefPage() {
  const [health, symbols, factors, backtests, paperRuns, recentRuns, candidates, locale] =
    await Promise.all([
      getCachedHealth(),
      getSymbols(),
      getFactors(),
      getBacktests(),
      getPaperRuns(),
      getRecentRuns(8),
      getAgentCandidates(),
      getServerLocale(),
    ]);
  const text = copy[locale];
  const latestBacktest = selectDisplayRun(backtests.backtests);
  const latestPaper = selectDisplayRun(paperRuns.paper_runs);
  const paperSummary = latestPaper?.summary;
  const leadCandidate = candidates.candidates[0];

  return (
    <div className="h-full overflow-y-auto bg-paper-ink text-ink">
      <div className="mx-auto flex w-full max-w-[var(--spacing-editorial-column)] flex-col gap-5 px-4 py-5 md:gap-6 md:px-8 md:py-6 lg:px-10">
        <ErrorBanner
          locale={locale}
          messages={[
            health.apiError,
            symbols.apiError,
            factors.apiError,
            backtests.apiError,
            paperRuns.apiError,
            recentRuns.apiError,
            candidates.apiError,
          ]}
        />

        <header className="border-b border-editorial-rule pb-5 md:pb-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 font-label-caps text-ink-secondary">
              <Newspaper size={15} className="text-editorial-accent" />
              <span>{text.eyebrow}</span>
            </div>
            <div className="rounded-sm border border-editorial-rule px-2.5 py-1 font-data-mono text-xs text-ink-secondary">
              {text.readOnly}
            </div>
          </div>
          <div className="mt-4 grid gap-5 md:mt-5 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-end">
            <div>
              <h1 className="font-editorial-display text-4xl leading-[44px] text-ink sm:text-[46px] sm:leading-[54px]">
                {text.title}
              </h1>
              <p className="mt-3 max-w-3xl font-editorial-body text-lg leading-7 text-ink sm:mt-4 sm:text-[21px] sm:leading-8">
                {text.deck}
              </p>
              <div className="mt-4 flex flex-wrap items-center gap-3 font-data-mono text-xs text-ink-secondary sm:mt-5">
                <span>{text.factLine}</span>
                <span aria-hidden="true">/</span>
                <span>
                  {text.source}={symbols.source}
                </span>
              </div>
            </div>
            <aside className="border-t border-editorial-rule pt-4 lg:border-t-0 lg:pt-0">
              <div className="flex items-center gap-2 font-label-caps text-ink-secondary">
                <ShieldCheck size={15} className="text-editorial-up" />
                <span>{text.status}</span>
              </div>
              <p className="mt-3 font-data-mono text-xs text-ink-secondary">{text.safetyContract}</p>
            </aside>
          </div>
        </header>

        <main className="grid min-w-0 gap-5 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-6">
          <div className="min-w-0 space-y-5 md:space-y-6">
            <section aria-labelledby="brief-kpis" className="grid grid-cols-2 gap-3 md:gap-4 xl:grid-cols-4">
              <h2 id="brief-kpis" className="sr-only">
                {text.factLine}
              </h2>
              <StatLine
                label={text.factorCount}
                value={formatCount(factors.factors.length)}
                detail="/api/factors"
              />
              <StatLine
                label={text.paperEquity}
                value={formatMoney(paperSummary?.final_equity)}
                detail={`${formatCount(paperRuns.paper_runs.length)} ${text.runs}`}
              />
              <StatLine
                label={text.latestSharpe}
                value={latestBacktest?.metrics?.sharpe?.toFixed(2) ?? "--"}
                detail={`${text.maxDrawdown} ${formatPercent(latestBacktest?.metrics?.max_drawdown)}`}
              />
              <StatLine
                label={text.candidateQueue}
                value={formatCount(candidates.candidates.length)}
                detail={text.candidateQueueDetail}
              />
            </section>

            <section aria-labelledby="brief-market" className="border-y border-editorial-rule py-5">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <h2 id="brief-market" className="font-label-caps text-ink">
                  {text.marketTape}
                </h2>
                <div className="font-data-mono text-xs text-ink-secondary">
                  {text.symbols}: {symbols.symbols.join(", ") || "--"}
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <article className="bg-paper-surface p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2 font-label-caps text-ink-secondary">
                      <LineChart size={14} className="text-editorial-accent" />
                      <span>{text.backtest}</span>
                    </div>
                    {latestBacktest?.source ? <DataSourceBadge source={latestBacktest.source} /> : null}
                  </div>
                  <h3 className="mt-3 truncate font-data-mono text-sm text-ink">
                    {latestBacktest?.id ?? text.noBacktest}
                  </h3>
                  <dl className="mt-4 grid grid-cols-2 gap-3 font-data-mono text-xs">
                    <div>
                      <dt className="text-ink-secondary">{text.totalReturn}</dt>
                      <dd className="mt-1 text-ink">
                        {formatPercent(latestBacktest?.metrics?.total_return)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-ink-secondary">{text.maxDrawdown}</dt>
                      <dd className="mt-1 text-ink">
                        {formatPercent(latestBacktest?.metrics?.max_drawdown)}
                      </dd>
                    </div>
                  </dl>
                </article>

                <article className="bg-paper-surface p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2 font-label-caps text-ink-secondary">
                      <BriefcaseBusiness size={14} className="text-editorial-up" />
                      <span>{text.paperRun}</span>
                    </div>
                    {latestPaper?.source ? <DataSourceBadge source={latestPaper.source} /> : null}
                  </div>
                  <h3 className="mt-3 truncate font-data-mono text-sm text-ink">
                    {latestPaper?.id ?? text.noPaper}
                  </h3>
                  <dl className="mt-4 grid grid-cols-2 gap-3 font-data-mono text-xs">
                    <div>
                      <dt className="text-ink-secondary">{text.orders}</dt>
                      <dd className="mt-1 text-ink">{formatCount(paperSummary?.order_count)}</dd>
                    </div>
                    <div>
                      <dt className="text-ink-secondary">{text.breaches}</dt>
                      <dd className="mt-1 text-ink">{formatCount(paperSummary?.risk_breach_count)}</dd>
                    </div>
                  </dl>
                </article>
              </div>
            </section>

            <section aria-labelledby="brief-runs">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2 id="brief-runs" className="font-label-caps text-ink">
                  {text.runLog}
                </h2>
                <div className="flex items-center gap-2 font-data-mono text-xs text-ink-secondary">
                  <Activity size={14} />
                  <span>{formatCount(recentRuns.runs.length)}</span>
                </div>
              </div>
              {recentRuns.runs.length > 0 ? (
                <div className="overflow-x-auto border-y border-editorial-rule">
                  <table className="min-w-[760px] w-full border-collapse">
                    <tbody>
                      {recentRuns.runs.map((run) => (
                        <tr key={`${run.kind}-${run.run_id}`} className="border-b border-editorial-rule last:border-b-0">
                          <td className="w-[160px] py-3 pr-4">
                            <div className="flex items-center gap-2">
                              {runIcon(run)}
                              <span className="font-label-caps text-ink-secondary">
                                {dashboardRunKindLabel(run, locale)}
                              </span>
                            </div>
                          </td>
                          <td className="py-3 pr-4">
                            <Link
                              className="inline-flex max-w-[240px] items-center gap-1 truncate font-data-mono text-xs text-ink transition-colors hover:text-editorial-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-editorial-accent"
                              href={localizePath(dashboardRunHref(run), locale)}
                            >
                              <span className="truncate">{run.run_id}</span>
                              <ArrowUpRight size={12} aria-hidden="true" />
                            </Link>
                          </td>
                          <td className="whitespace-nowrap py-3 pr-4 font-data-mono text-xs text-ink-secondary">
                            {dashboardRunSummary(run)}
                          </td>
                          <td className="whitespace-nowrap py-3 text-right font-data-mono text-xs text-ink-secondary">
                            {formatRunTimestamp(run.created_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="border-y border-editorial-rule py-5 font-data-mono text-sm text-ink-secondary">
                  {text.runLogEmpty}
                </p>
              )}
            </section>
          </div>

          <aside className="min-w-0 space-y-6">
            <section aria-labelledby="brief-safety" className="bg-paper-surface p-4">
              <h2 id="brief-safety" className="mb-2 flex items-center gap-2 font-label-caps text-ink">
                <ShieldCheck size={15} className="text-editorial-up" />
                {text.status}
              </h2>
              <SafetyRow label={text.api} value={health.status} emphasis={health.status === "ok" ? "safe" : "warn"} />
              <SafetyRow
                label={text.paperTrading}
                value={boolLabel(health.safety?.paper_trading, text)}
                emphasis={health.safety?.paper_trading ? "safe" : undefined}
              />
              <SafetyRow
                label={text.liveTrading}
                value={boolLabel(health.safety?.live_trading_enabled, text)}
                emphasis={health.safety?.live_trading_enabled ? "warn" : undefined}
              />
              <SafetyRow
                label={text.killSwitch}
                value={boolLabel(health.safety?.kill_switch, text)}
                emphasis={health.safety?.kill_switch ? "warn" : undefined}
              />
            </section>

            <section aria-labelledby="brief-candidate" className="bg-paper-surface p-4">
              <h2 id="brief-candidate" className="mb-4 flex items-center gap-2 font-label-caps text-ink">
                <Bot size={15} className="text-editorial-accent" />
                {text.candidateBrief}
              </h2>
              {leadCandidate ? (
                <div>
                  <div className="truncate font-data-mono text-sm text-ink">{leadCandidate.candidate_id}</div>
                  <dl className="mt-4 space-y-3 font-data-mono text-xs">
                    <div>
                      <dt className="text-ink-secondary">{text.candidateStatus}</dt>
                      <dd className="mt-1 text-ink">{leadCandidate.status}</dd>
                    </div>
                    <div>
                      <dt className="text-ink-secondary">{text.candidateGoal}</dt>
                      <dd className="mt-1 text-ink-secondary">{leadCandidate.goal ?? "--"}</dd>
                    </div>
                    <div>
                      <dt className="text-ink-secondary">{text.candidateRef}</dt>
                      <dd className="mt-1 break-all text-ink-secondary">
                        /api/agent/candidates/{leadCandidate.candidate_id}
                      </dd>
                    </div>
                  </dl>
                </div>
              ) : (
                <p className="font-data-mono text-sm text-ink-secondary">{text.noCandidate}</p>
              )}
            </section>
          </aside>
        </main>
      </div>
    </div>
  );
}
