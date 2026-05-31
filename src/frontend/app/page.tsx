import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import {
  Bot,
  BriefcaseBusiness,
  Database,
  FlaskConical,
  LineChart,
  Play,
  Settings,
} from "lucide-react";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import {
  formatMoney,
  formatPercent,
  getAgentCandidates,
  getBacktests,
  getFactors,
  getHealth,
  getPaperRuns,
  getSymbols,
} from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    kpiFactors: "Registered Factors",
    kpiFactorsDetail: "from /api/factors",
    kpiEquity: "Paper Equity",
    kpiEquityDetail: (n: number, source?: string) => `${n} paper runs; source=${source ?? "none"}`,
    kpiCandidates: "Agent Candidates",
    kpiCandidatesDetail: "from /api/agent/candidates",
    kpiSharpe: "Latest Sharpe",
    kpiSharpeDetail: (dd: string, source?: string) => `max drawdown ${dd}; source=${source ?? "none"}`,
    recentOps: "Recent Operations",
    snapshot: "local API snapshot",
    backtest: "Backtest",
    noBacktest: "No backtest run yet",
    ret: "Return",
    maxDd: "Max DD",
    symbols: "Symbols",
    paperRun: "Paper Run",
    noPaper: "No paper run yet",
    orders: "Orders",
    breaches: "Breaches",
    agentPool: "Agent Pool",
    noCandidate: "No candidate yet",
    candidatesReview: (n: number) => `${n} candidates require manual review.`,
    activityLog: "Activity log",
    activityLogDesc: "No recent research activity to show yet. Runs you start from the workbench pages will appear here.",
    quickActions: "QUICK ACTIONS",
    startBacktest: "Start New Backtest",
    runFactor: "Run Factor Analysis",
    newAgent: "New Agent Task",
    openSettings: "Open Settings",
    envState: "ENVIRONMENT STATE",
    api: "API",
    paperTrading: "paper trading",
    liveTrading: "live trading",
    killSwitch: "kill switch",
    on: "on",
    off: "off",
    telemetry: "System telemetry unavailable",
    telemetryDesc: "CPU and memory telemetry are not part of the current local API.",
  },
  zh: {
    kpiFactors: "已注册因子",
    kpiFactorsDetail: "来自 /api/factors",
    kpiEquity: "模拟权益",
    kpiEquityDetail: (n: number, source?: string) => `${n} 次模拟运行；来源=${source ?? "无"}`,
    kpiCandidates: "智能体候选",
    kpiCandidatesDetail: "来自 /api/agent/candidates",
    kpiSharpe: "最新夏普比率",
    kpiSharpeDetail: (dd: string, source?: string) => `最大回撤 ${dd}；来源=${source ?? "无"}`,
    recentOps: "最近操作",
    snapshot: "本地接口快照",
    backtest: "回测",
    noBacktest: "还没有回测记录",
    ret: "收益",
    maxDd: "最大回撤",
    symbols: "标的",
    paperRun: "模拟运行",
    noPaper: "还没有模拟运行",
    orders: "订单",
    breaches: "风控触发",
    agentPool: "智能体池",
    noCandidate: "还没有候选",
    candidatesReview: (n: number) => `有 ${n} 个候选需要人工复核。`,
    activityLog: "活动日志",
    activityLogDesc: "暂时还没有研究活动。你在各工作台页面发起的运行会显示在这里。",
    quickActions: "快捷操作",
    startBacktest: "新建回测",
    runFactor: "运行因子分析",
    newAgent: "新建智能体任务",
    openSettings: "打开设置",
    envState: "环境状态",
    api: "接口",
    paperTrading: "模拟交易",
    liveTrading: "实盘交易",
    killSwitch: "熔断开关",
    on: "开",
    off: "关",
    telemetry: "系统遥测不可用",
    telemetryDesc: "当前本地接口不包含 CPU 与内存遥测数据。",
  },
};

function KpiCard({
  title,
  value,
  detail,
  icon: Icon,
}: {
  title: string;
  value: string | number;
  detail: string;
  icon: LucideIcon;
}) {
  return (
    <div className="flex min-h-28 flex-col justify-between rounded border border-border-subtle bg-bg-surface p-4">
      <div className="flex items-start justify-between">
        <h3 className="font-label-caps uppercase text-text-secondary">{title}</h3>
        <Icon size={14} className="text-primary" />
      </div>
      <div>
        <div className="font-data-mono text-headline-xl text-text-primary">{value}</div>
        <div className="font-data-mono text-[10px] text-text-secondary">{detail}</div>
      </div>
    </div>
  );
}

export default async function Dashboard() {
  const [health, symbols, factors, backtests, paperRuns, candidates, locale] = await Promise.all([
    getHealth(),
    getSymbols(),
    getFactors(),
    getBacktests(),
    getPaperRuns(),
    getAgentCandidates(),
    getServerLocale(),
  ]);
  const text = copy[locale];
  const latestBacktest = backtests.backtests[0];
  const latestPaper = paperRuns.paper_runs[0];
  const paperSummary = latestPaper?.summary;

  return (
    <div className="flex h-full flex-col overflow-hidden xl:flex-row">
      <div className="flex-1 space-y-6 overflow-y-auto p-gutter lg:p-container-padding">
        <ErrorBanner
          messages={[
            health.apiError,
            symbols.apiError,
            factors.apiError,
            backtests.apiError,
            paperRuns.apiError,
            candidates.apiError,
          ]}
        />
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            title={text.kpiFactors}
            value={factors.factors.length}
            detail={text.kpiFactorsDetail}
            icon={FlaskConical}
          />
          <KpiCard
            title={text.kpiEquity}
            value={formatMoney(paperSummary?.final_equity)}
            detail={text.kpiEquityDetail(paperRuns.paper_runs.length, latestPaper?.source)}
            icon={BriefcaseBusiness}
          />
          <KpiCard
            title={text.kpiCandidates}
            value={candidates.candidates.length}
            detail={text.kpiCandidatesDetail}
            icon={Bot}
          />
          <KpiCard
            title={text.kpiSharpe}
            value={latestBacktest?.metrics?.sharpe?.toFixed(2) ?? "--"}
            detail={text.kpiSharpeDetail(
              formatPercent(latestBacktest?.metrics?.max_drawdown),
              latestBacktest?.source,
            )}
            icon={LineChart}
          />
        </section>

        <section className="space-y-4">
          <div className="flex items-center justify-between border-b border-border-subtle pb-2">
            <h2 className="font-headline-lg text-text-primary">{text.recentOps}</h2>
            <span className="font-label-caps text-text-secondary">{text.snapshot}</span>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded border border-border-subtle bg-bg-surface p-4">
              <div className="mb-4 flex items-center gap-2 font-label-caps text-text-secondary">
                <LineChart size={14} className="text-info" /> {text.backtest}
              </div>
              <h3 className="truncate font-body-md font-medium text-text-primary">
                {latestBacktest?.id ?? text.noBacktest}
              </h3>
              {latestBacktest?.source ? (
                <div className="mt-2">
                  <DataSourceBadge source={latestBacktest.source} />
                </div>
              ) : null}
              <div className="mt-4 space-y-2 font-data-mono text-xs">
                <div className="flex justify-between">
                  <span className="text-text-secondary">{text.ret}</span>
                  <span className="text-text-primary">
                    {formatPercent(latestBacktest?.metrics?.total_return)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">{text.maxDd}</span>
                  <span className="text-text-primary">
                    {formatPercent(latestBacktest?.metrics?.max_drawdown)}
                  </span>
                </div>
              </div>
            </div>

            <div className="rounded border border-border-subtle bg-bg-surface p-4">
              <div className="mb-4 flex items-center gap-2 font-label-caps text-text-secondary">
                <Database size={14} className="text-warning" /> {text.symbols}
              </div>
              <h3 className="truncate font-body-md font-medium text-text-primary">
                {symbols.symbols.join(", ")}
              </h3>
              <p className="mt-4 font-data-mono text-xs text-text-secondary">
                source={symbols.source}; status={health.status}
              </p>
            </div>

            <div className="rounded border border-border-subtle bg-bg-surface p-4">
              <div className="mb-4 flex items-center gap-2 font-label-caps text-text-secondary">
                <BriefcaseBusiness size={14} className="text-primary" /> {text.paperRun}
              </div>
              <h3 className="truncate font-body-md font-medium text-text-primary">
                {latestPaper?.id ?? text.noPaper}
              </h3>
              {latestPaper?.source ? (
                <div className="mt-2">
                  <DataSourceBadge source={latestPaper.source} />
                </div>
              ) : null}
              <div className="mt-4 space-y-2 font-data-mono text-xs">
                <div className="flex justify-between">
                  <span className="text-text-secondary">{text.orders}</span>
                  <span className="text-text-primary">{paperSummary?.order_count ?? 0}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">{text.breaches}</span>
                  <span className="text-text-primary">{paperSummary?.risk_breach_count ?? 0}</span>
                </div>
              </div>
            </div>

            <div className="rounded border border-border-subtle bg-bg-surface p-4">
              <div className="mb-4 flex items-center gap-2 font-label-caps text-text-secondary">
                <Bot size={14} className="text-info" /> {text.agentPool}
              </div>
              <h3 className="truncate font-body-md font-medium text-text-primary">
                {candidates.candidates[0]?.candidate_id ?? text.noCandidate}
              </h3>
              <p className="mt-4 font-data-mono text-xs text-text-secondary">
                {text.candidatesReview(candidates.candidates.length)}
              </p>
            </div>
          </div>
        </section>

        <EmptyState
          title={text.activityLog}
          description={text.activityLogDesc}
        />
      </div>

      <aside className="flex w-full flex-shrink-0 flex-col gap-6 overflow-y-auto border-l border-border-subtle bg-bg-surface p-6 xl:w-[320px]">
        <div>
          <h3 className="mb-4 border-b border-border-subtle pb-2 font-label-caps text-text-secondary">
            {text.quickActions}
          </h3>
          <div className="space-y-3">
            <Link
              href="/backtest"
              className="flex w-full items-center gap-3 rounded border border-border-subtle bg-bg-surface-muted px-4 py-2 text-left font-body-sm text-text-primary transition-colors hover:border-primary"
            >
              <Play size={14} className="text-primary" /> {text.startBacktest}
            </Link>
            <Link
              href="/factor-lab"
              className="flex w-full items-center gap-3 rounded border border-border-subtle bg-bg-surface-muted px-4 py-2 text-left font-body-sm text-text-primary transition-colors hover:border-warning"
            >
              <FlaskConical size={14} className="text-warning" /> {text.runFactor}
            </Link>
            <Link
              href="/agent-studio"
              className="flex w-full items-center gap-3 rounded border border-border-subtle bg-bg-surface-muted px-4 py-2 text-left font-body-sm text-text-primary transition-colors hover:border-info"
            >
              <Bot size={14} className="text-info" /> {text.newAgent}
            </Link>
            <Link
              href="/settings"
              className="flex w-full items-center gap-3 rounded border border-border-subtle bg-bg-surface-muted px-4 py-2 text-left font-body-sm text-text-primary transition-colors hover:border-text-primary"
            >
              <Settings size={14} className="text-text-secondary" /> {text.openSettings}
            </Link>
          </div>
        </div>

        <div>
          <h3 className="mb-4 border-b border-border-subtle pb-2 font-label-caps text-text-secondary">
            {text.envState}
          </h3>
          <div className="space-y-3 font-body-sm">
            <div className="flex justify-between">
              <span className="text-text-secondary">{text.api}</span>
              <span className="font-data-mono text-text-primary">{health.status}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-secondary">{text.paperTrading}</span>
              <span className="font-data-mono text-text-primary">
                {String(health.safety?.paper_trading)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-secondary">{text.liveTrading}</span>
              <span className="font-data-mono text-text-primary">
                {String(health.safety?.live_trading_enabled)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-secondary">{text.killSwitch}</span>
              <span className="font-data-mono text-warning">
                {health.safety?.kill_switch ? text.on : text.off}
              </span>
            </div>
          </div>
        </div>

        <EmptyState
          title={text.telemetry}
          description={text.telemetryDesc}
        />
      </aside>
    </div>
  );
}
