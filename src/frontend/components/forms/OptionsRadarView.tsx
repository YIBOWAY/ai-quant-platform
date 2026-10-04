'use client';

import Link from "next/link";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  Download,
  ExternalLink,
  RefreshCw,
  Radar,
  ShieldCheck,
} from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";
import type {
  OptionsDailyScanRunResponse,
  OptionsDailyScanResponse,
  OptionsDailyScanStatusResponse,
  OptionsDailyTaskStatus,
  OptionsRadarCandidate,
  OptionsRefreshResponse,
} from "@/lib/api";
import { getOptionsRadarDates } from "@/lib/api";
import { ApiClientError, apiPost, apiRequest } from "@/lib/apiClient";
import { optionsErrorMessage, optionsReasonLabel } from "@/lib/optionsErrorPresentation";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { InfoTip, type GlossaryKey } from "@/components/InfoTip";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { useIsHydrated } from "@/lib/hydration";
import { localizePath } from "@/lib/locale";
import {
  Card,
  MetricStat,
  PageHeader,
  SectionTitle,
  StatusPill,
  TerminalSplitShell,
  TerminalToolbarButton,
  terminalInputClass,
} from "@/components/ui/primitives";

const selectClass = terminalInputClass;
const recommendationLimit = 20;
const curatedUniverseSize = 34;

// Maps radar column index to a glossary term so headers can show a hint.
const headingTips: Record<number, GlossaryKey> = {
  5: "apr",
  6: "delta",
  7: "ivRank",
};
const sectors = [
  "Communication Services",
  "Consumer Discretionary",
  "Consumer Staples",
  "Energy",
  "Financials",
  "Health Care",
  "Healthcare",
  "Industrials",
  "Information Technology",
  "Materials",
  "Real Estate",
  "Technology",
  "Utilities",
  "ETF",
];
type RefreshKind = "earnings" | "vix";

const copy = {
  en: {
    title: "Options Recommendations",
    intro: "Compare seller opportunities across 34 tracked symbols, ranked by expected value and liquidity. At most two contracts per symbol.",
    date: "Scan date (history)",
    dateHelp: "This is the day a curated scan was saved — NOT an option expiry. Updates run automatically at 22:00 every day, or you can update now.",
    freshToday: "Showing the latest accepted market-session data.",
    freshStale: "Showing the scan from {date} ({days} day(s) ago). Wait for the next scheduled curated scan for fresh data.",
    freshNone: "No scheduled curated scan has been saved yet.",
    staleBlock:
      "This is an old snapshot. Expired contracts are history only; wait for the next scheduled curated scan before current research.",
    expiredRows: "Expired rows in full snapshot",
    strategy: "Strategy",
    all: "All",
    sellPut: "Sell Put",
    coveredCall: "Covered Call",
    sector: "Sector",
    dte: "DTE bucket",
    safety: "Read-only research output. These rows are not trade instructions and cannot place orders.",
    export: "Export CSV",
    noData: "No recommendation rows are available yet.",
    emptyRecommendations: "No compliant recommendations. The scan completed, but no contract passed every hard gate.",
    filteredEmpty: "No recommendations match the current filters.",
    unavailableRecommendations: "Recommendations unavailable",
    unavailableRecommendationsBody: "No Futu-backed recommendation rows are shown because the saved response is unavailable or not backed by the real Futu provider.",
    shortfall: "{count} fewer than the 20-row maximum.",
    shortfallReasons: "Exclusion reasons",
    partialUniverse: "This snapshot scanned only {count} of {total} selected symbols. Recommendations are unavailable; wait for the next scheduled curated scan.",
    rows: "Rows",
    scanned: "Scanned",
    failed: "Failed",
    regime: "Market regime",
    regimeUnknown: "Unknown - the scheduled input refresh has not provided usable VIX history.",
    regimeNormal: "Normal - recent three-month VIX/VIX3M cache shows no market-regime score penalty.",
    regimeElevated: "Elevated - recent three-month VIX/VIX3M cache applies a moderate seller score penalty.",
    regimePanic: "Panic - recent three-month VIX/VIX3M cache applies a heavy seller score penalty.",
    details: "Details",
    openChain: "Open Chain",
    scheduledTask: "Scheduled task",
    taskLoading: "Loading task status...",
    taskMissing: "No scheduled task status has been written yet.",
    taskCompleted: "Completed",
    taskCompletedWithWarnings: "Completed with warnings",
    taskDataUnavailable: "No usable data",
    taskFailed: "Failed",
    taskQueued: "Queued",
    taskRunning: "Updating",
    taskTargetSession: "Target session",
    taskProgress: "Progress",
    taskElapsed: "Elapsed",
    taskCanLeave: "You can leave this page; the update will continue in the background.",
    taskCandidateCount: "Candidates",
    taskFailedStep: "Failed step",
    taskFinishedAt: "Finished",
    taskProvider: "Provider",
    summaryAvailable: "Today's scan found {count} qualifying opportunity row(s).",
    summaryPartialTitle: "Partially completed",
    summaryPartial: "Scanned {scanned}/{total}. Showing results from successful symbols; {failed} symbol(s) failed.",
    summaryWarnings: "The update completed with warnings. Scanned {scanned}/{total}; successful results are shown.",
    summaryFailed: "The latest update failed. The last valid result remains visible; you can retry now.",
    summaryDataUnavailable: "The latest update found no usable market data. The last valid result remains visible; you can retry now.",
    summaryEmpty: "The scan completed across {scanned} symbols, but no contract passed every required condition.",
    summaryOld: "This is an old snapshot. Update now before using this page for current research.",
    summaryStaleSnapshot:
      "Snapshot is stale; there are no fresh tradeable recommendations today, and these results were cleared. Update now (the automatic job runs daily at 22:00).",
    summaryLegacy: "This is a legacy snapshot. Update now to create a current recommendation snapshot.",
    summaryNone: "No recommendation data exists yet. Start an update now; daily automatic updates run at 22:00.",
    scanDetails: "View scan details",
    hideScanDetails: "Hide scan details",
    lastResult: "Previous valid result remains below",
    oldRowsHidden: "Historical or unsupported snapshot rows are not shown as current recommendations.",
    refresh: "Update Today's Recommendations Now",
    refreshRunning: "Updating recommendations...",
    refreshEarnings: "Refresh Earnings",
    refreshVix: "Refresh VIX",
    eyebrow: "Read-only · Paper research",
    advanced: "Advanced data sources",
    advancedHint: "Public earnings and VIX refreshes for the curated recommendation scan. Local sample inputs are not accepted here.",
    statusState: "Scan",
    statusIdle: "Idle",
    statusScanDate: "Scan date",
    statusDataAsOf: "Data as of",
    statusProvider: "Snapshot provider",
    statusNone: "None",
    statusAvailable: "Available",
    statusEmpty: "No recommendations",
    statusWaiting: "Update needed",
    statusLoading: "Loading",
    candidatesTitle: "Seller recommendations",
    candidatesHint: "At most 2 contracts per symbol, 20 total. Qualified contracts retain their EV ranking; an incomplete scan does not guarantee a diversified portfolio.",
    headings: ["Symbol", "Strategy", "Expiry / DTE", "Strike", "Premium", "Annualized yield", "Delta", "IVR", "Liquidity", "Events", "Details"],
  },
  zh: {
    title: "期权推荐",
    intro: "每日扫描跟踪的 34 个标的，筛选适合卖出期权的机会。不会下单、不会解锁账户、不会接入实盘。",
    date: "扫描日期（历史快照）",
    dateHelp: "这是推荐数据保存的日期，不是期权到期日。每天 22:00 自动更新，也可以现在更新。",
    freshToday: "正在显示最新可接受的美股交易 session 数据。",
    freshStale: "正在显示 {date} 的扫描结果（{days} 天前）。请等待下一次定时策展扫描。",
    freshNone: "还没有保存过定时策展扫描。",
    staleBlock: "这是旧快照。过期合约只适合回看历史；做当前研究前请等待下一次定时策展扫描。",
    expiredRows: "完整快照中过期合约数",
    strategy: "策略",
    all: "全部",
    sellPut: "卖出看跌",
    coveredCall: "备兑看涨",
    sector: "行业",
    dte: "剩余天数",
    safety: "仅用于研究筛选。这些结果不是交易指令，也不能发出真实订单。",
    export: "导出 CSV",
    noData: "暂无可展示的推荐行。",
    emptyRecommendations: "没有合规推荐。扫描已经完成，但没有合约通过全部硬门。",
    filteredEmpty: "当前筛选条件下没有推荐。",
    unavailableRecommendations: "推荐不可用",
    unavailableRecommendationsBody: "保存结果不可用或并非真实 Futu 数据，因此不会展示任何推荐行。",
    shortfall: "比最多 20 条少 {count} 条。",
    shortfallReasons: "排除原因",
    partialUniverse: "该快照只扫描了 {total} 个选定标的中的 {count} 个，推荐不可用；请等待下一次定时策展扫描。",
    rows: "候选",
    scanned: "已扫描",
    failed: "失败",
    regime: "市场状态",
    regimeUnknown: "未知 - 定时输入刷新尚未提供可用的 VIX 历史。",
    regimeNormal: "平稳 - 不施加市场状态扣分。",
    regimeElevated: "偏高 - 对卖方候选施加中等评分扣分。",
    regimePanic: "恐慌 - 对卖方候选施加较重评分扣分。",
    details: "详情",
    openChain: "查看期权链",
    scheduledTask: "定时任务",
    taskLoading: "正在读取任务状态...",
    taskMissing: "尚未写入定时任务状态。",
    taskCompleted: "已完成",
    taskCompletedWithWarnings: "已完成，但有部分失败",
    taskDataUnavailable: "未获取到可用数据",
    taskFailed: "失败",
    taskQueued: "已排队",
    taskRunning: "正在更新",
    taskTargetSession: "目标交易日",
    taskProgress: "进度",
    taskElapsed: "耗时",
    taskCanLeave: "可以离开本页，更新会在后台继续。",
    taskCandidateCount: "候选",
    taskFailedStep: "失败步骤",
    taskFinishedAt: "完成时间",
    taskProvider: "数据源",
    summaryAvailable: "今日扫描发现 {count} 条符合条件的机会。",
    summaryPartialTitle: "部分完成",
    summaryPartial: "已扫描 {scanned}/{total}，保留成功标的的结果；{failed} 个标的失败。",
    summaryWarnings: "本次更新带有警告。已扫描 {scanned}/{total}，下方保留成功结果。",
    summaryFailed: "本次更新失败，仍显示上一份有效结果；可以现在重试。",
    summaryDataUnavailable: "本次更新没有获取到可用行情，仍显示上一份有效结果；可以现在重试。",
    summaryEmpty: "已扫描 {scanned} 个标的，但没有合约通过全部必要条件。",
    summaryOld: "这是旧快照。用于当前研究前，请立即更新。",
    summaryStaleSnapshot: "快照已过期，今日尚无新鲜可交易推荐；本次结果已清空，请立即更新（自动流程每日 22:00 运行）。",
    summaryLegacy: "这是旧版快照。立即更新后会生成当前版本的推荐快照。",
    summaryNone: "还没有推荐数据。可以现在开始更新，之后每天 22:00 也会自动更新。",
    scanDetails: "查看扫描详情",
    hideScanDetails: "收起扫描详情",
    lastResult: "下方保留上一份有效结果",
    oldRowsHidden: "历史或不受支持的快照不会当作当前推荐展示。",
    refresh: "立即更新今日推荐",
    refreshRunning: "正在更新推荐…",
    refreshEarnings: "刷新财报日历",
    refreshVix: "刷新 VIX",
    eyebrow: "只读 · 模拟研究",
    advanced: "高级数据源",
    advancedHint: "为推荐扫描刷新公开财报与 VIX 数据；这里不接受本地样例输入。",
    statusState: "扫描",
    statusIdle: "空闲",
    statusScanDate: "扫描日期",
    statusDataAsOf: "数据截至",
    statusProvider: "快照数据源",
    statusNone: "无",
    statusAvailable: "可用",
    statusEmpty: "暂无推荐",
    statusWaiting: "需要更新",
    statusLoading: "加载中",
    candidatesTitle: "今日机会",
    candidatesHint: "每个标的最多 2 条，总计最多 20 条。合格合约按期望收益与流动性排序；这是机会比较，实际组合仍需考虑相关性。",
    headings: ["标的", "策略", "到期/剩余天数", "行权价", "权利金", "年化收益", "Delta", "IVR", "流动性", "事件", "详情"],
  },
};

export function OptionsRadarView({
  initialDate = "",
  locale = "en",
}: {
  initialDate?: string;
  locale?: "en" | "zh";
}) {
  const hydrated = useIsHydrated();
  const queryClient = useQueryClient();
  const text = copy[locale];
  const [date, setDate] = useState(initialDate);
  const [strategy, setStrategy] = useState("all");
  const [sector, setSector] = useState("");
  const [dteBucket, setDteBucket] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [refreshStatus, setRefreshStatus] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [scanDetailsOpen, setScanDetailsOpen] = useState(false);
  const [terminalBaseline, setTerminalBaseline] = useState<string | null | undefined>(undefined);
  const [latestDetectedTarget, setLatestDetectedTarget] = useState<string | null>(null);

  const datesQuery = useQuery({
    queryKey: ["options-radar-dates"],
    enabled: hydrated,
    queryFn: getOptionsRadarDates,
    placeholderData: keepPreviousData,
  });
  const taskStatusQuery = useQuery({
    queryKey: ["options-daily-task-status"],
    enabled: hydrated,
    queryFn: () =>
      apiRequest<OptionsDailyScanStatusResponse>("/api/options/daily-scan/status"),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      isActiveScanState(
        (query.state.data as OptionsDailyScanStatusResponse | undefined)?.status?.status,
      )
        ? 2_500
        : 60_000,
    refetchIntervalInBackground: true,
  });
  const runScanMutation = useMutation({
    mutationFn: () =>
      apiPost<OptionsDailyScanRunResponse>("/api/options/daily-scan/run", {}),
    onSuccess: async (payload) => {
      queryClient.setQueryData<OptionsDailyScanStatusResponse>(
        ["options-daily-task-status"],
        (previous) => ({
          ...previous,
          exists: true,
          status_path: previous?.status_path ?? "daily_task_status.json",
          status: payload,
        }),
      );
      await taskStatusQuery.refetch();
    },
    onError: async () => {
      await taskStatusQuery.refetch();
    },
  });
  const taskState = taskStatusQuery.data?.status?.status ?? null;
  const taskTargetSession = taskStatusQuery.data?.status?.target_session ?? null;
  const terminalSignature = successfulTerminalSignature(taskStatusQuery.data?.status);
  const isNewSuccessfulTerminal =
    terminalBaseline !== undefined &&
    terminalSignature !== null &&
    terminalSignature !== terminalBaseline;
  const scanIsActive = runScanMutation.isPending || isActiveScanState(taskState);

  useEffect(() => {
    if (!taskStatusQuery.isFetched || terminalBaseline !== undefined) return;
    const timer = window.setTimeout(() => setTerminalBaseline(terminalSignature), 0);
    return () => window.clearTimeout(timer);
  }, [taskStatusQuery.isFetched, terminalBaseline, terminalSignature]);

  useEffect(() => {
    if (
      !isNewSuccessfulTerminal ||
      !terminalSignature ||
      !taskTargetSession
    ) return;
    const timer = window.setTimeout(() => {
      setTerminalBaseline(terminalSignature);
      setLatestDetectedTarget(taskTargetSession);
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["options-radar-dates"] }),
        queryClient.invalidateQueries({ queryKey: ["options-radar"] }),
      ]);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [isNewSuccessfulTerminal, queryClient, taskTargetSession, terminalSignature]);

  const detectedTargetSession =
    isNewSuccessfulTerminal && taskTargetSession ? taskTargetSession : latestDetectedTarget;
  const activeDate = detectedTargetSession || date || datesQuery.data?.dates[0] || "";
  const scanPath = buildScanPath({
    date: activeDate,
    strategy,
    sector,
    dteBucket,
    top: recommendationLimit,
  });
  const scanQuery = useQuery({
    queryKey: ["options-radar", activeDate, strategy, sector, dteBucket, recommendationLimit],
    enabled: hydrated,
    queryFn: () => apiRequest<OptionsDailyScanResponse>(scanPath),
    // Keep prior filter/date rows visible while the next scan key loads (RQ v5).
    placeholderData: keepPreviousData,
  });
  const recommendationStatus = scanQuery.data
    ? scanQuery.data.provider === "futu" && !scanQuery.data.is_stale
      ? scanQuery.data.status
      : "unavailable"
    : undefined;

  const candidates = useMemo(
    () =>
      recommendationStatus === "available" && scanQuery.data
        ? scanQuery.data.candidates.slice(0, recommendationLimit)
        : [],
    [recommendationStatus, scanQuery.data],
  );
  const displayedStatus =
    recommendationStatus === "available" && candidates.length === 0
      ? "empty"
      : recommendationStatus;
  const legacySnapshot = Object.prototype.hasOwnProperty.call(
    scanQuery.data?.shortfall_reasons ?? {},
    "legacy_snapshot_contract",
  );
  const noSnapshot = !scanQuery.data?.run_date && !scanQuery.data?.provider;
  // Initial cold load only — filter/date switches keep previous data via placeholderData.
  const scanInitialLoading = scanQuery.isLoading && !scanQuery.data;
  const scanRefetching = scanQuery.isFetching && Boolean(scanQuery.data);
  const displayedStatusLabel = scanInitialLoading
    ? text.statusLoading
    : legacySnapshot || displayedStatus === "unavailable"
      ? text.statusWaiting
      : displayedStatus === "available"
        ? text.statusAvailable
        : displayedStatus === "empty"
          ? text.statusEmpty
          : text.statusIdle;
  const filtersActive = strategy !== "all" || Boolean(sector) || Boolean(dteBucket);
  const csv = useMemo(() => buildCsv(candidates), [candidates]);
  const regime = useMemo(() => deriveRegime(candidates), [candidates]);
  const refreshMutation = useMutation({
    mutationFn: (kind: RefreshKind) =>
      apiPost<OptionsRefreshResponse>(`/api/options/refresh/${kind}`, {
        source: "public",
        top: curatedUniverseSize,
    }),
    onSuccess: async (payload) => {
      const label =
        payload.kind === "vix"
          ? "VIX"
          : locale === "zh"
            ? "财报日历"
            : capitalize(payload.kind);
      setRefreshStatus(
        locale === "zh"
          ? `${label} 已刷新（${payload.row_count} 行）`
          : `${label} refreshed (${payload.row_count} rows)`,
      );
      await queryClient.invalidateQueries({ queryKey: ["options-radar-dates"] });
      await queryClient.invalidateQueries({ queryKey: ["options-radar"] });
    },
  });

  function exportCsv() {
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `options-radar-${scanQuery.data?.run_date ?? "latest"}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <TerminalSplitShell
      sidebar={
        <>
        <div className="flex items-center gap-2">
          <Radar className="text-info" size={18} />
          <h1 className="font-headline-lg text-text-primary">{text.title}</h1>
        </div>
        <p className="mt-1 font-label-caps uppercase text-text-secondary">{text.eyebrow}</p>
        <p className="mt-2 font-body-sm text-text-secondary">{text.intro}</p>
        <form className="mt-5 flex flex-col gap-4" onSubmit={(event) => event.preventDefault()}>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.date}
            <select
              className={selectClass}
              onChange={(event) => {
                setTerminalBaseline(terminalSignature);
                setLatestDetectedTarget(null);
                setDate(event.target.value);
              }}
              value={activeDate}
            >
              {datesQuery.data?.dates.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <p className="-mt-2 font-body-sm text-text-secondary">{text.dateHelp}</p>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.strategy}
            <select
              className={selectClass}
              onChange={(event) => setStrategy(event.target.value)}
              value={strategy}
            >
              <option value="all">{text.all}</option>
              <option value="sell_put">{text.sellPut}</option>
              <option value="covered_call">{text.coveredCall}</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.sector}
            <select
              className={selectClass}
              onChange={(event) => setSector(event.target.value)}
              value={sector}
            >
              <option value="">{text.all}</option>
              {sectors.map((item) => (
                <option key={item} value={item}>{sectorLabel(item, locale)}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.dte}
            <select
              className={selectClass}
              onChange={(event) => setDteBucket(event.target.value)}
              value={dteBucket}
            >
              <option value="">{text.all}</option>
              <option value="5-21">5-21</option>
              <option value="21-45">21-45</option>
              <option value="45-60">45-60</option>
            </select>
          </label>
          <div className="grid grid-cols-1 gap-2">
            <TerminalToolbarButton
              className="h-10 w-full justify-center px-4"
              disabled={!hydrated || scanIsActive || datesQuery.isFetching || scanQuery.isFetching}
              onClick={() => {
                runScanMutation.mutate();
              }}
              tone="info"
              type="button"
            >
              <RefreshCw className="mr-2 inline" size={16} />
              {scanIsActive ? text.refreshRunning : text.refresh}
            </TerminalToolbarButton>
            <TerminalToolbarButton
              className="h-10 justify-center px-4"
              disabled={!hydrated || !csv || candidates.length === 0}
              onClick={exportCsv}
              tone="neutral"
              type="button"
            >
              <Download className="mr-2 inline" size={16} />
              {text.export}
            </TerminalToolbarButton>
          </div>
          {runScanMutation.error && !scanIsActive ? (
            <p className="-mt-2 font-body-sm text-danger" role="alert">
              {isAlreadyRunningError(runScanMutation.error)
                ? text.refreshRunning
                : optionsErrorMessage(runScanMutation.error, locale)}
            </p>
          ) : null}
          <div className="mt-1 rounded-lg border border-border-subtle bg-bg-surface-muted">
            <button
              aria-expanded={advancedOpen}
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left font-label-caps text-text-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
              onClick={() => setAdvancedOpen((open) => !open)}
              type="button"
            >
              <span>{text.advanced}</span>
              {advancedOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
            {advancedOpen ? (
              <div className="motion-panel-enter border-t border-border-subtle p-3">
                <p className="mb-3 font-body-sm text-text-secondary">{text.advancedHint}</p>
                <div className="mt-3 grid grid-cols-1 gap-2">
                  <TerminalToolbarButton
                    className="h-10 w-full justify-center"
                    disabled={!hydrated || scanIsActive || refreshMutation.isPending}
                    onClick={() => refreshMutation.mutate("earnings")}
                    tone="neutral"
                    type="button"
                  >
                    <RefreshCw className="mr-2 inline" size={16} />
                    {text.refreshEarnings}
                  </TerminalToolbarButton>
                  <TerminalToolbarButton
                    className="h-10 w-full justify-center"
                    disabled={!hydrated || scanIsActive || refreshMutation.isPending}
                    onClick={() => refreshMutation.mutate("vix")}
                    tone="neutral"
                    type="button"
                  >
                    <RefreshCw className="mr-2 inline" size={16} />
                    {text.refreshVix}
                  </TerminalToolbarButton>
                </div>
                {refreshStatus ? (
                  <div className="mt-3 rounded-lg border border-accent-success/40 bg-accent-success/10 p-2 font-body-sm text-accent-success">
                    {refreshStatus}
                  </div>
                ) : null}
                {refreshMutation.error instanceof Error ? (
                  <div className="mt-3 rounded-lg border border-danger/40 bg-danger/10 p-2 font-body-sm text-danger">
                    {optionsErrorMessage(refreshMutation.error, locale)}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </form>
        </>
      }
      sidebarClassName="p-4 lg:w-[360px]"
    >
        <PageHeader
          eyebrow={text.eyebrow}
          title={text.title}
          subtitle={text.safety}
          icon={<ShieldCheck className="text-warning" size={20} />}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill
                label={text.statusState}
                value={displayedStatusLabel}
                tone={
                  displayedStatus === "available"
                    ? "success"
                    : displayedStatus === "unavailable"
                      ? "danger"
                      : "neutral"
                }
              />
              <StatusPill
                label={text.statusScanDate}
                value={activeDate || text.statusNone}
                tone="neutral"
              />
              <StatusPill
                label={text.statusDataAsOf}
                value={
                  scanQuery.data?.as_of
                    ? locale === "zh"
                      ? formatDateTime(scanQuery.data.as_of, locale)
                      : scanQuery.data.as_of
                    : text.statusNone
                }
                tone={
                  scanQuery.data?.as_of
                    ? scanQuery.data.is_stale
                      ? "danger"
                      : "success"
                    : "neutral"
                }
              />
              {scanQuery.data?.provider ? (
                <span className="flex items-center gap-1.5 font-body-sm text-text-secondary">
                  {text.statusProvider}: <DataSourceBadge source={scanQuery.data.provider} />
                </span>
              ) : null}
            </div>
          }
        />
        <OptionsScanStatusCard
          candidatesCount={candidates.length}
          detailsOpen={scanDetailsOpen}
          error={taskStatusQuery.error}
          isLoading={taskStatusQuery.isLoading}
          legacySnapshot={legacySnapshot}
          locale={locale}
          onToggleDetails={() => setScanDetailsOpen((open) => !open)}
          regime={regime}
          response={taskStatusQuery.data}
          scan={scanQuery.data}
          scanError={scanQuery.error}
          text={text}
        />
        {scanQuery.data?.run_date ? <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <MetricStat label={text.rows} value={String(candidates.length)} tone="neutral" />
          <MetricStat label={locale === "zh" ? "覆盖标的" : "Distinct symbols"} value={String(new Set(candidates.map((candidate) => candidate.ticker)).size)} />
          <MetricStat label={text.scanned} value={String(scanQuery.data?.scanned_tickers ?? 0)} />
          <MetricStat
            label={text.failed}
            value={String(scanQuery.data?.failed_tickers.length ?? 0)}
            tone={(scanQuery.data?.failed_tickers.length ?? 0) > 0 ? "warning" : "neutral"}
          />
        </section> : null}
        <Card padded={false}>
          <div className="border-b border-border-subtle px-4 py-3">
            <SectionTitle title={text.candidatesTitle} hint={text.candidatesHint} />
          </div>
          <div
            aria-busy={scanRefetching || scanInitialLoading}
            className="motion-data-hold"
            data-fetching={scanRefetching ? "true" : "false"}
          >
          {scanInitialLoading ? (
            <div className="p-4">
              <LoadingSkeleton rows={6} />
            </div>
          ) : scanQuery.isError && !scanQuery.data ? (
            <div className="p-6 font-body-sm text-text-secondary">
              {isNoSnapshotError(scanQuery.error)
                ? text.noData
                : optionsErrorMessage(scanQuery.error, locale)}
            </div>
          ) : displayedStatus === "empty" ? (
            <div className="p-6 font-body-sm text-text-secondary">
              {filtersActive ? text.filteredEmpty : text.emptyRecommendations}
            </div>
          ) : recommendationStatus === "unavailable" ? (
            <div className="p-6 font-body-sm text-text-secondary">
              {noSnapshot
                ? text.summaryNone
                : legacySnapshot || scanQuery.data?.is_stale
                  ? text.oldRowsHidden
                  : text.unavailableRecommendationsBody}
            </div>
          ) : candidates.length === 0 ? (
            <div className="p-6 font-body-sm text-text-secondary">{text.noData}</div>
          ) : (
            <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead className="sticky top-0 z-10 bg-bg-surface">
                <tr className="border-b border-border-subtle">
                  {text.headings.map((heading, index) => (
                    <th className="px-3 py-2 font-label-caps text-text-secondary" key={heading}>
                      <span className="inline-flex items-center gap-1">
                        {heading}
                        {headingTips[index] ? <InfoTip term={headingTips[index]} locale={locale} /> : null}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="font-body-sm text-text-primary">
                {candidates.map((candidate, index) => {
                  const rowKey = candidateRowKey(candidate);
                  const detailId = `option-candidate-detail-${index}`;
                  const isExpanded = expanded === rowKey;
                  return (
                  <Fragment key={rowKey}>
                    <tr className="border-b border-border-subtle/50">
                      <td className="px-3 py-2">{candidate.ticker}</td>
                      <td className="px-3 py-2">{strategyLabel(candidate.strategy, locale)}</td>
                      <td className="whitespace-nowrap px-3 py-2">
                        {formatDate(candidate.expiry, locale)} · {fmt(candidate.days_to_expiry, 0)}{locale === "zh" ? "天" : "d"}
                      </td>
                      <td className="px-3 py-2">{fmt(candidate.strike)}</td>
                      <td className="px-3 py-2">${fmt(candidate.mid)}</td>
                      <td className="px-3 py-2">{pct(candidate.gross_annualized_yield)}</td>
                      <td className="px-3 py-2">{fmt(candidate.delta, 3)}</td>
                      <td className="whitespace-nowrap px-3 py-2">{ivRankLabel(candidate, locale)}</td>
                      <td className="px-3 py-2">{pct(candidate.liquidity_factor)}</td>
                      <td className="whitespace-nowrap px-3 py-2">{eventSummary(candidate, locale)}</td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <div className="flex items-center gap-3">
                          <button
                            aria-controls={detailId}
                            aria-expanded={isExpanded}
                            className="rounded-md text-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
                            onClick={() => setExpanded(isExpanded ? null : rowKey)}
                            type="button"
                          >
                            {text.details}
                          </button>
                          <Link
                            className="inline-flex items-center gap-1 rounded-md text-info hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
                            href={localizePath(`/options-radar/${candidate.ticker}?date=${scanQuery.data?.run_date ?? activeDate}&expiry=${candidate.expiry}&option_type=${candidate.strategy === "sell_put" ? "PUT" : "CALL"}`, locale)}
                          >
                            {text.openChain}
                            <ExternalLink size={12} />
                          </Link>
                        </div>
                      </td>
                    </tr>
                    {isExpanded ? (
                      <tr className="border-b border-border-subtle/50" id={detailId}>
                        <td className="px-3 py-3 font-body-sm text-text-secondary" colSpan={11}>
                          <span className="motion-panel-enter break-words">{candidateDetail(candidate, locale)}</span>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          )}
          </div>
        </Card>
    </TerminalSplitShell>
  );
}

type RegimeInfo = {
  label: "Normal" | "Elevated" | "Panic" | "Unknown";
  penalty: number | null;
};

function deriveRegime(candidates: OptionsRadarCandidate[]): RegimeInfo {
  for (const candidate of candidates) {
    if (candidate.market_regime) {
      return {
        label: candidate.market_regime as RegimeInfo["label"],
        penalty: candidate.market_regime_penalty ?? null,
      };
    }
  }
  return { label: "Unknown", penalty: null };
}

// Row identity: the contract symbol can repeat across expiries/strikes in a
// snapshot, so expansion and React keys use the stable contract tuple.
export function candidateRowKey(candidate: OptionsRadarCandidate) {
  return [candidate.symbol, candidate.expiry, candidate.strike, candidate.strategy].join("|");
}

function buildScanPath({
  date,
  strategy,
  sector,
  dteBucket,
  top,
}: {
  date: string;
  strategy: string;
  sector: string;
  dteBucket: string;
  top: number;
}) {
  const params = new URLSearchParams({
    strategy,
    top: String(top),
  });
  if (date) params.set("date", date);
  if (sector) params.set("sector", sector);
  if (dteBucket) params.set("dte_bucket", dteBucket);
  return `/api/options/daily-scan?${params.toString()}`;
}

type ScanViewState =
  | "no_snapshot"
  | "scanning"
  | "legacy"
  | "stale_snapshot"
  | "old"
  | "empty"
  | "partial"
  | "failed"
  | "data_unavailable"
  | "unavailable"
  | "available";

function OptionsScanStatusCard({
  candidatesCount,
  detailsOpen,
  error,
  isLoading,
  legacySnapshot,
  locale,
  onToggleDetails,
  regime,
  response,
  scan,
  scanError,
  text,
}: {
  candidatesCount: number;
  detailsOpen: boolean;
  error: unknown;
  isLoading: boolean;
  legacySnapshot: boolean;
  locale: "en" | "zh";
  onToggleDetails: () => void;
  regime: RegimeInfo;
  response?: OptionsDailyScanStatusResponse;
  scan?: OptionsDailyScanResponse;
  scanError: unknown;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  const status = response?.status ?? null;
  const state = status?.status ?? null;
  const viewState = deriveScanViewState({
    candidatesCount,
    legacySnapshot,
    scan,
    scanError,
    taskState: state,
  });
  const tone: "danger" | "success" | "warning" | "info" | "neutral" =
    viewState === "failed" || viewState === "data_unavailable" || viewState === "unavailable"
      ? "danger"
      : viewState === "partial" || viewState === "legacy" || viewState === "old" || viewState === "stale_snapshot"
        ? "warning"
        : viewState === "available"
          ? "success"
          : viewState === "scanning"
            ? "info"
            : "neutral";
  // One candidate count on screen: the rows the user can actually see. The
  // task status count is only a fallback while no snapshot listing is loaded.
  const candidateCount = scan?.run_date ? candidatesCount : taskCandidateCount(status);
  const active = isActiveScanState(state);
  const [clockNow, setClockNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setClockNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [active]);
  const stepLabel = active ? taskStepLabel(status?.current_step, text) : null;
  const progress = taskProgress(status);
  const elapsed = active
    ? formatElapsed(status?.started_at ?? status?.queued_at, clockNow)
    : null;
  const summary = scanStateSummary({
    candidatesCount,
    isLoading,
    scan,
    state: viewState,
    stepLabel,
    taskStatus: status,
    text,
  });
  const hasDetails = Boolean(
    scan?.run_date ||
      status?.provider ||
      status?.failed_step ||
      status?.error ||
      Object.keys(scan?.shortfall_reasons ?? {}).length ||
      scan?.failed_tickers.length,
  );

  return (
    <Card tone={tone}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div aria-atomic="true" aria-live="polite" role="status">
          <h2 className="font-label-caps text-text-primary">{summary.title}</h2>
          <p className="mt-1 font-body-sm text-text-secondary">
            {error instanceof Error && !scan
              ? optionsErrorMessage(error, locale)
              : summary.body}
          </p>
        </div>
        {response?.exists && status ? (
          <div className="flex flex-wrap items-center gap-2 font-data-mono text-xs text-text-secondary">
            {status.target_session ? (
              <span>{text.taskTargetSession} {status.target_session}</span>
            ) : null}
            {progress ? <span>{text.taskProgress} {progress}</span> : null}
            {elapsed ? <span aria-live="off">{text.taskElapsed} {elapsed}</span> : null}
            {status.provider ? (
              <span className="flex items-center gap-1.5">
                {text.taskProvider}: <DataSourceBadge source={status.provider} />
              </span>
            ) : null}
            {candidateCount !== null ? (
              <span>{text.taskCandidateCount}: {candidateCount}</span>
            ) : null}
            {status.failed_step ? (
              <span className="text-danger">{text.taskFailedStep}: {status.failed_step}</span>
            ) : null}
            {status.finished_at ? (
              <span>{text.taskFinishedAt}: {formatTaskTime(status.finished_at, locale)}</span>
            ) : null}
          </div>
        ) : null}
      </div>
      {hasDetails ? (
        <div className="mt-3 border-t border-border-subtle pt-3">
          <button
            aria-controls="options-scan-details"
            aria-expanded={detailsOpen}
            className="app-touch-target inline-flex items-center gap-1 rounded-md font-body-sm text-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
            onClick={onToggleDetails}
            type="button"
          >
            {detailsOpen ? text.hideScanDetails : text.scanDetails}
            {detailsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
          {detailsOpen ? (
            <div className="motion-panel-enter mt-3 space-y-1 font-body-sm text-text-secondary" id="options-scan-details">
              {scan?.run_date ? <p>{text.statusScanDate}: {scan.run_date}</p> : null}
              {scan?.as_of ? <p>{text.statusDataAsOf}: {formatDateTime(scan.as_of, locale)}</p> : null}
              {scan?.provider ? <p>{text.statusProvider}: {scan.provider}</p> : null}
              {scan && scan.universe_size > 0 ? (
                <p>{text.scanned}: {scan.scanned_tickers}/{scan.universe_size} · {text.failed}: {scan.failed_tickers.length}</p>
              ) : null}
              {regime.label !== "Unknown" ? (
                <p>{text.regime}: {marketRegimeLabel(regime.label, locale)}</p>
              ) : null}
              {(scan?.shortfall_count ?? 0) > 0 ? (
                <p>{text.shortfall.replace("{count}", String(scan?.shortfall_count ?? 0))}</p>
              ) : null}
              {Object.keys(scan?.shortfall_reasons ?? {}).length > 0 ? (
                <p>
                  {text.shortfallReasons}: {Object.entries(scan?.shortfall_reasons ?? {})
                    .map(([reason, count]) => `${scanReasonLabel(reason, locale)}${count > 1 ? ` (${count})` : ""}`)
                    .join(" · ")}
                </p>
              ) : null}
              {scan?.failed_tickers.map(([ticker, reason]) => (
                <p key={`${ticker}-${reason}`}>{ticker}: {scanReasonLabel(reason, locale)}</p>
              ))}
              {status?.failed_step ? <p>{text.taskFailedStep}: {taskStepLabel(status.failed_step, text)}</p> : null}
              {status?.error ? <p>{optionsErrorMessage(status.error, locale)}</p> : null}
              {status?.finished_at ? <p>{text.taskFinishedAt}: {formatTaskTime(status.finished_at, locale)}</p> : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

function deriveScanViewState({
  candidatesCount,
  legacySnapshot,
  scan,
  scanError,
  taskState,
}: {
  candidatesCount: number;
  legacySnapshot: boolean;
  scan?: OptionsDailyScanResponse;
  scanError: unknown;
  taskState: string | null;
}): ScanViewState {
  if (isActiveScanState(taskState)) return "scanning";
  if (taskState === "failed") return "failed";
  if (taskState === "data_unavailable") return "data_unavailable";
  if (scanError) return isNoSnapshotError(scanError) ? "no_snapshot" : "unavailable";
  if (!scan || (!scan.run_date && !scan.provider)) return "no_snapshot";
  if (legacySnapshot) return "legacy";
  // The API clears candidates and tags the reason when the snapshot is stale:
  // say so plainly instead of the generic "old snapshot" line.
  if (scan.is_stale && Object.prototype.hasOwnProperty.call(scan.shortfall_reasons ?? {}, "snapshot_stale")) {
    return "stale_snapshot";
  }
  if (scan.is_stale) return "old";
  if (scan.provider !== "futu" || scan.status === "unavailable") return "unavailable";
  if (
    taskState === "completed_with_warnings" ||
    scan.failed_tickers.length > 0 ||
    scan.scanned_tickers < scan.universe_size
  ) return "partial";
  if (scan.status === "empty" || candidatesCount === 0) return "empty";
  return "available";
}

function scanStateSummary({
  candidatesCount,
  isLoading,
  scan,
  state,
  stepLabel,
  taskStatus,
  text,
}: {
  candidatesCount: number;
  isLoading: boolean;
  scan?: OptionsDailyScanResponse;
  state: ScanViewState;
  stepLabel: string | null;
  taskStatus: OptionsDailyTaskStatus | null;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  if (isLoading && !taskStatus) return { title: text.statusLoading, body: text.taskLoading };
  if (state === "scanning") {
    return {
      title: text.taskRunning,
      body: `${stepLabel ?? text.taskQueued}${taskStatus?.target_session ? ` · ${text.taskTargetSession} ${taskStatus.target_session}` : ""} · ${text.taskCanLeave}`,
    };
  }
  if (state === "failed") return { title: text.taskFailed, body: text.summaryFailed };
  if (state === "data_unavailable") return { title: text.taskDataUnavailable, body: text.summaryDataUnavailable };
  if (state === "partial") {
    const bodyTemplate =
      taskStatus?.status === "completed_with_warnings"
        ? text.summaryWarnings
        : text.summaryPartial;
    return {
      title: text.summaryPartialTitle,
      body: bodyTemplate
        .replace("{scanned}", String(scan?.scanned_tickers ?? 0))
        .replace("{total}", String(scan?.universe_size ?? 0))
        .replace("{failed}", String(scan?.failed_tickers.length ?? 0)),
    };
  }
  if (state === "legacy") return { title: text.statusWaiting, body: text.summaryLegacy };
  if (state === "stale_snapshot") return { title: text.statusWaiting, body: text.summaryStaleSnapshot };
  if (state === "old") return { title: text.statusWaiting, body: text.summaryOld };
  if (state === "no_snapshot") return { title: text.statusNone, body: text.summaryNone };
  if (state === "empty") {
    return {
      title: text.statusEmpty,
      body: text.summaryEmpty.replace("{scanned}", String(scan?.scanned_tickers ?? 0)),
    };
  }
  if (state === "available") {
    return {
      title: text.statusAvailable,
      body: text.summaryAvailable.replace("{count}", String(candidatesCount)),
    };
  }
  return { title: text.unavailableRecommendations, body: text.unavailableRecommendationsBody };
}

function scanReasonLabel(reason: string, locale: "en" | "zh") {
  return optionsReasonLabel(reason, locale);
}

function isNoSnapshotError(error: unknown) {
  return error instanceof ApiClientError && error.status === 404;
}

function isActiveScanState(state: string | null | undefined) {
  return state === "queued" || state === "running";
}

function isSuccessfulScanState(state: string | null | undefined) {
  return state === "completed" || state === "completed_with_warnings";
}

function successfulTerminalSignature(status: OptionsDailyTaskStatus | null | undefined) {
  if (
    !isSuccessfulScanState(status?.status) ||
    !status?.target_session ||
    !status.finished_at
  ) return null;
  return `${status.target_session}|${status.finished_at}`;
}

function isAlreadyRunningError(error: unknown) {
  return error instanceof Error && error.message.includes("options_scan_already_running");
}

function taskStateLabel(
  state: string | null,
  text: (typeof copy)["en"] | (typeof copy)["zh"],
) {
  if (state === "queued") return text.taskQueued;
  if (state === "running") return text.taskRunning;
  if (state === "completed") return text.taskCompleted;
  if (state === "completed_with_warnings") return text.taskCompletedWithWarnings;
  if (state === "data_unavailable") return text.taskDataUnavailable;
  if (state === "failed") return text.taskFailed;
  return state ?? "--";
}

function taskStepLabel(
  step: string | null | undefined,
  text: (typeof copy)["en"] | (typeof copy)["zh"],
) {
  const zh = text === copy.zh;
  const labels: Record<string, [string, string]> = {
    queued: ["Queued", "排队中"],
    universe: ["Preparing symbols", "准备标的"],
    earnings: ["Refreshing earnings", "更新财报日历"],
    dividends: ["Refreshing dividends", "更新除息数据"],
    vix: ["Refreshing market volatility", "更新市场波动"],
    scan: ["Scanning options", "扫描期权"],
  };
  const label = step ? labels[step] : undefined;
  return label ? label[zh ? 1 : 0] : step ?? null;
}

function taskProgress(status: OptionsDailyTaskStatus | null) {
  if (!status) return null;
  const completed = status.scanned_tickers;
  const total = status.total_tickers;
  return typeof completed === "number" && typeof total === "number" && total > 0
    ? `${completed}/${total}`
    : null;
}

function formatElapsed(value: string | null | undefined, now = Date.now()) {
  if (!value) return null;
  const started = new Date(value).getTime();
  if (!Number.isFinite(started)) return null;
  const seconds = Math.max(0, Math.floor((now - started) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function taskCandidateCount(status: OptionsDailyTaskStatus | null): number | null {
  const scan = status?.steps?.scan;
  const value = scan?.candidate_count;
  return typeof value === "number" ? value : null;
}

function formatTaskTime(value: string, locale: "en" | "zh") {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function fmt(value?: number | null, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function pct(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "--";
}

function candidateDetail(candidate: OptionsRadarCandidate, locale: "en" | "zh") {
  const parts = [
    locale === "zh" ? `合约 ${candidate.symbol}` : `Contract ${candidate.symbol}`,
    locale === "zh"
      ? `行业 ${sectorLabel(candidate.sector ?? null, locale)}`
      : `sector ${sectorLabel(candidate.sector ?? null, locale)}`,
    locale === "zh"
      ? `分数 ${fmt(candidate.global_score, 1)}`
      : `score ${fmt(candidate.global_score, 1)}`,
    locale === "zh"
      ? `市场状态 ${marketRegimeLabel(candidate.market_regime, locale)}`
      : `market regime ${candidate.market_regime ?? "Unknown"}`,
    locale === "zh" ? `盈利概率 ${pct(candidate.pop)}` : `POP ${pct(candidate.pop)}`,
    locale === "zh" ? `虚值幅度 ${pct(candidate.otm_pct)}` : `OTM ${pct(candidate.otm_pct)}`,
    locale === "zh"
      ? `价差 ${pct(candidate.spread_pct)}`
      : `spread ${pct(candidate.spread_pct)}`,
    locale === "zh"
      ? `未平仓 ${fmt(candidate.open_interest, 0)}`
      : `open interest ${fmt(candidate.open_interest, 0)}`,
    locale === "zh"
      ? `盈亏平衡 ${fmt(candidate.breakeven)}`
      : `breakeven ${fmt(candidate.breakeven)}`,
    locale === "zh"
      ? `50% 止盈价 ${fmt(candidate.take_profit_50_price)}`
      : `50% take-profit ${fmt(candidate.take_profit_50_price)}`,
    locale === "zh"
      ? `21 DTE 管理日 ${formatDate(candidate.manage_at_21_dte, locale)}`
      : `manage at 21 DTE ${candidate.manage_at_21_dte}`,
    locale === "zh"
      ? `超额年化期望值 ${pct(candidate.excess_annualized_ev)}`
      : `excess annualized EV ${pct(candidate.excess_annualized_ev)}`,
    locale === "zh"
      ? `报价时间 ${formatDateTime(candidate.quote_as_of, locale)}`
      : `quote time ${candidate.quote_as_of}`,
  ];
  return parts.join(" | ");
}

function strategyLabel(strategy: OptionsRadarCandidate["strategy"], locale: "en" | "zh") {
  if (strategy === "sell_put") return locale === "zh" ? "卖出看跌" : "Sell Put";
  if (strategy === "covered_call") return locale === "zh" ? "备兑看涨" : "Covered Call";
  return strategy;
}

function sectorLabel(sector: string | null, locale: "en" | "zh") {
  if (!sector) return locale === "zh" ? "未分类" : "Unclassified";
  if (locale === "en") return sector;
  const labels: Record<string, string> = {
    "Communication Services": "通信服务",
    "Consumer Discretionary": "可选消费",
    "Consumer Staples": "日常消费",
    Energy: "能源",
    Financials: "金融",
    "Health Care": "医疗保健",
    Healthcare: "医疗健康",
    Industrials: "工业",
    "Information Technology": "信息技术",
    Materials: "原材料",
    "Real Estate": "房地产",
    Technology: "科技",
    Utilities: "公用事业",
    ETF: "指数基金",
  };
  return labels[sector] ?? sector;
}

function marketRegimeLabel(value: string | null | undefined, locale: "en" | "zh") {
  if (locale === "en") return value ?? "Unknown";
  if (value === "Normal") return "平稳";
  if (value === "Elevated") return "偏高";
  if (value === "Panic") return "恐慌";
  return "未知";
}

function ivRankLabel(candidate: OptionsRadarCandidate, locale: "en" | "zh") {
  if (
    candidate.iv_rank_status === "warming" ||
    (candidate.iv_rank_status !== "ready" && typeof candidate.iv_history_samples === "number")
  ) {
    const samples = Math.max(0, Math.min(30, candidate.iv_history_samples ?? 0));
    return locale === "zh" ? `积累中 ${samples}/30` : `Warming ${samples}/30`;
  }
  if (typeof candidate.iv_rank === "number" && Number.isFinite(candidate.iv_rank)) {
    return fmt(candidate.iv_rank, 1);
  }
  return "--";
}

function eventSummary(candidate: OptionsRadarCandidate, locale: "en" | "zh") {
  const earnings = candidate.earnings_date
    ? formatDate(candidate.earnings_date, locale)
    : locale === "zh"
      ? "无财报"
      : "No earnings";
  const dividend = candidate.ex_dividend_date
    ? formatDate(candidate.ex_dividend_date, locale)
    : locale === "zh"
      ? "无除息"
      : "No ex-div";
  const warning = candidate.earnings_in_window || candidate.ex_dividend_in_window ? " !" : "";
  return `${earnings} · ${dividend}${warning}`;
}

function formatDate(value: string, locale: "en" | "zh") {
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  return locale === "zh"
    ? new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(parsed)
    : value.slice(0, 10);
}

function formatDateTime(value: string, locale: "en" | "zh") {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function buildCsv(candidates: OptionsRadarCandidate[]) {
  const headers = ["ticker", "strategy", "symbol", "expiry", "dte", "strike", "mid", "gross_annualized_yield", "delta", "pop", "otm_pct", "iv_rank", "oi", "spread", "earnings_date", "ex_dividend_date", "breakeven", "take_profit_50_price", "manage_at_21_dte", "expected_value", "excess_annualized_ev", "liquidity_factor"];
  const rows = candidates.map((item) =>
    [
      item.ticker,
      item.strategy,
      item.symbol,
      item.expiry,
      item.days_to_expiry,
      item.strike,
      item.mid ?? "",
      item.gross_annualized_yield,
      item.delta ?? "",
      item.pop,
      item.otm_pct,
      item.iv_rank ?? "",
      item.open_interest ?? "",
      item.spread_pct ?? "",
      item.earnings_date ?? "",
      item.ex_dividend_date ?? "",
      item.breakeven,
      item.take_profit_50_price,
      item.manage_at_21_dte,
      item.expected_value,
      item.excess_annualized_ev,
      item.liquidity_factor,
    ].join(","),
  );
  return [headers.join(","), ...rows].join("\n");
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
