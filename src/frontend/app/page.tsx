import Link from "next/link";
import {
  Bot,
  BriefcaseBusiness,
  Database,
  FlaskConical,
  LayoutDashboard,
  LineChart,
  Play,
  Settings,
} from "lucide-react";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import {
  Card,
  MetricStat,
  PageHeader,
  SectionTitle,
  StatusPill,
  TerminalTable,
  ToneBadge,
} from "@/components/ui/primitives";
import {
  formatMoney,
  formatPercent,
  getAgentCandidates,
  getBacktests,
  getFactors,
  getPaperRuns,
  getRecentRuns,
  getSymbols,
} from "@/lib/api";
import {
  dashboardRunHref,
  dashboardRunIconKind,
  dashboardRunKindLabel,
  dashboardRunSummary,
  formatCount,
} from "@/lib/dashboardRuns";
import { selectDisplayRun } from "@/lib/runSource";
import { getServerLocale } from "@/lib/serverLocale";
import { getCachedHealth } from "@/lib/serverApi";
import { localizePath } from "@/lib/locale";

const copy = {
  en: {
    pageEyebrow: "Workbench",
    pageTitle: "Dashboard",
    pageSubtitle: "Local API snapshot of factors, paper runs, and agent candidates. Paper-only research — no live trading.",
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
    runType: "Type",
    runId: "Run",
    runSummary: "Summary",
    created: "Created",
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
    pageEyebrow: "工作台",
    pageTitle: "仪表盘",
    pageSubtitle: "因子、模拟运行与智能体候选的本地接口快照。仅用于模拟研究，不涉及实盘交易。",
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
    runType: "类型",
    runId: "运行",
    runSummary: "摘要",
    created: "创建时间",
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

type DashboardCopy = (typeof copy)["en"] | (typeof copy)["zh"];

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

function RunKindIcon({ iconKind }: { iconKind: ReturnType<typeof dashboardRunIconKind> }) {
  if (iconKind === "backtest") {
    return <LineChart size={14} className="text-info" />;
  }
  if (iconKind === "factor") {
    return <FlaskConical size={14} className="text-warning" />;
  }
  if (iconKind === "replication") {
    return <Database size={14} className="text-info" />;
  }
  return <BriefcaseBusiness size={14} className="text-accent-success" />;
}

export default async function Dashboard() {
  const [health, symbols, factors, backtests, paperRuns, recentRuns, candidates, locale] = await Promise.all([
    getCachedHealth(),
    getSymbols(),
    getFactors(),
    getBacktests(),
    getPaperRuns(),
    getRecentRuns(6),
    getAgentCandidates(),
    getServerLocale(),
  ]);
  const text = copy[locale];
  const latestBacktest = selectDisplayRun(backtests.backtests);
  const latestPaper = selectDisplayRun(paperRuns.paper_runs);
  const paperSummary = latestPaper?.summary;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden xl:flex-row">
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-gutter lg:p-container-padding">
        <PageHeader
          eyebrow={text.pageEyebrow}
          title={text.pageTitle}
          subtitle={text.pageSubtitle}
          icon={<LayoutDashboard size={18} className="text-accent-success" />}
        />
        <ErrorBanner
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
        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <MetricStat
            label={text.kpiFactors}
            value={factors.factors.length}
            hint={text.kpiFactorsDetail}
            delta={text.kpiFactorsDetail}
          />
          <MetricStat
            label={text.kpiEquity}
            value={formatMoney(paperSummary?.final_equity)}
            tone="success"
            hint={text.kpiEquityDetail(paperRuns.paper_runs.length, latestPaper?.source)}
            delta={text.kpiEquityDetail(paperRuns.paper_runs.length, latestPaper?.source)}
          />
          <MetricStat
            label={text.kpiCandidates}
            value={candidates.candidates.length}
            hint={text.kpiCandidatesDetail}
            delta={text.kpiCandidatesDetail}
          />
          <MetricStat
            label={text.kpiSharpe}
            value={latestBacktest?.metrics?.sharpe?.toFixed(2) ?? "--"}
            hint={text.kpiSharpeDetail(
              formatPercent(latestBacktest?.metrics?.max_drawdown),
              latestBacktest?.source,
            )}
            delta={text.kpiSharpeDetail(
              formatPercent(latestBacktest?.metrics?.max_drawdown),
              latestBacktest?.source,
            )}
          />
        </section>

        <section>
          <SectionTitle
            title={text.recentOps}
            right={<span className="font-label-caps text-text-secondary">{text.snapshot}</span>}
          />

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Card padded>
              <div className="mb-3 flex items-center gap-2 font-label-caps text-text-secondary">
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
              <div className="mt-3 space-y-2 font-data-mono text-xs">
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
            </Card>

            <Card padded>
              <div className="mb-3 flex items-center gap-2 font-label-caps text-text-secondary">
                <Database size={14} className="text-warning" /> {text.symbols}
              </div>
              <h3 className="truncate font-body-md font-medium text-text-primary">
                {symbols.symbols.join(", ")}
              </h3>
              <p className="mt-3 font-data-mono text-xs text-text-secondary">
                source={symbols.source}; status={health.status}
              </p>
            </Card>

            <Card padded>
              <div className="mb-3 flex items-center gap-2 font-label-caps text-text-secondary">
                <BriefcaseBusiness size={14} className="text-accent-success" /> {text.paperRun}
              </div>
              <h3 className="truncate font-body-md font-medium text-text-primary">
                {latestPaper?.id ?? text.noPaper}
              </h3>
              {latestPaper?.source ? (
                <div className="mt-2">
                  <DataSourceBadge source={latestPaper.source} />
                </div>
              ) : null}
              <div className="mt-3 space-y-2 font-data-mono text-xs">
                <div className="flex justify-between">
                  <span className="text-text-secondary">{text.orders}</span>
                  <span className="text-text-primary">{paperSummary?.order_count ?? 0}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">{text.breaches}</span>
                  <span className="text-text-primary">{paperSummary?.risk_breach_count ?? 0}</span>
                </div>
              </div>
            </Card>

            <Card padded>
              <div className="mb-3 flex items-center gap-2 font-label-caps text-text-secondary">
                <Bot size={14} className="text-info" /> {text.agentPool}
              </div>
              <h3 className="truncate font-body-md font-medium text-text-primary">
                {candidates.candidates[0]?.candidate_id ?? text.noCandidate}
              </h3>
              <p className="mt-3 font-data-mono text-xs text-text-secondary">
                {text.candidatesReview(candidates.candidates.length)}
              </p>
            </Card>
          </div>
        </section>

        {recentRuns.runs.length > 0 ? (
          <section>
            <SectionTitle
              title={text.activityLog}
              right={
                <span className="font-data-mono text-xs text-text-secondary">
                  {formatCount(recentRuns.runs.length)} / {formatCount(recentRuns.total)}
                </span>
              }
            />
            <TerminalTable
              columns={[
                { label: text.runType, className: "w-[168px]" },
                { label: text.runId },
                { label: text.runSummary, className: "w-[280px]" },
                { label: text.created, align: "right", className: "w-[148px]" },
              ]}
              minWidth="920px"
            >
              {recentRuns.runs.map((run) => (
                <tr
                  key={`${run.kind}-${run.run_id}`}
                  className="border-b border-border-subtle/80 transition-colors last:border-b-0 hover:bg-bg-surface-muted/45"
                >
                  <td className="px-3 py-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <RunKindIcon iconKind={dashboardRunIconKind(run)} />{" "}
                      <ToneBadge tone="neutral">{dashboardRunKindLabel(run, locale)}</ToneBadge>
                      {run.source ? <DataSourceBadge source={run.source} /> : null}
                    </div>
                  </td>
                  <td className="px-3 py-3">
                    <Link
                      className="block truncate font-data-mono text-xs font-semibold text-text-primary transition-colors hover:text-info"
                      href={localizePath(dashboardRunHref(run), locale)}
                    >
                      {run.run_id}
                    </Link>
                  </td>
                  <td className="px-3 py-3 font-data-mono text-xs text-text-secondary">
                    {dashboardRunSummary(run)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-data-mono text-xs text-text-secondary">
                    {formatRunTimestamp(run.created_at)}
                  </td>
                </tr>
              ))}
            </TerminalTable>
          </section>
        ) : (
          <EmptyState
            title={text.activityLog}
            description={text.activityLogDesc}
          />
        )}
      </div>

      <aside className="flex w-full flex-shrink-0 flex-col gap-4 overflow-y-auto border-l border-border-subtle bg-bg-surface p-gutter lg:p-container-padding xl:w-[320px]">
        <div>
          <SectionTitle title={text.quickActions} />
          <div className="space-y-2">
            <Link
              href={localizePath("/backtest", locale)}
              className="flex w-full items-center gap-3 rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 text-left font-body-sm text-text-primary transition-colors hover:border-accent-success"
            >
              <Play size={14} className="text-accent-success" /> {text.startBacktest}
            </Link>
            <Link
              href={localizePath("/factor-lab", locale)}
              className="flex w-full items-center gap-3 rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 text-left font-body-sm text-text-primary transition-colors hover:border-warning"
            >
              <FlaskConical size={14} className="text-warning" /> {text.runFactor}
            </Link>
            <Link
              href={localizePath("/agent-studio", locale)}
              className="flex w-full items-center gap-3 rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 text-left font-body-sm text-text-primary transition-colors hover:border-info"
            >
              <Bot size={14} className="text-info" /> {text.newAgent}
            </Link>
            <Link
              href={localizePath("/settings", locale)}
              className="flex w-full items-center gap-3 rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 text-left font-body-sm text-text-primary transition-colors hover:border-text-primary"
            >
              <Settings size={14} className="text-text-secondary" /> {text.openSettings}
            </Link>
          </div>
        </div>

        <div>
          <SectionTitle title={text.envState} />
          <Card padded>
            <div className="space-y-2 font-body-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-text-secondary">{text.api}</span>
                <StatusPill
                  label=""
                  value={health.status}
                  tone={health.status === "ok" ? "success" : "warning"}
                />
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-text-secondary">{text.paperTrading}</span>
                <StatusPill
                  label=""
                  value={String(health.safety?.paper_trading)}
                  tone={health.safety?.paper_trading ? "success" : "neutral"}
                />
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-text-secondary">{text.liveTrading}</span>
                <StatusPill
                  label=""
                  value={String(health.safety?.live_trading_enabled)}
                  tone={health.safety?.live_trading_enabled ? "danger" : "neutral"}
                />
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-text-secondary">{text.killSwitch}</span>
                <StatusPill
                  label=""
                  value={health.safety?.kill_switch ? text.on : text.off}
                  tone={health.safety?.kill_switch ? "warning" : "neutral"}
                />
              </div>
            </div>
          </Card>
        </div>

        <EmptyState
          title={text.telemetry}
          description={text.telemetryDesc}
        />
      </aside>
    </div>
  );
}
