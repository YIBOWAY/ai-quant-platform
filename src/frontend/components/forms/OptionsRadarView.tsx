'use client';

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  OptionsDailyScanResponse,
  OptionsDailyScanRunResponse,
  OptionsDailyScanStatusResponse,
  OptionsDailyTaskStatus,
  OptionsRadarCandidate,
  OptionsRefreshResponse,
} from "@/lib/api";
import { getOptionsRadarDates } from "@/lib/api";
import { apiPost, apiRequest } from "@/lib/apiClient";
import { InfoTip, type GlossaryKey } from "@/components/InfoTip";
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

// Maps radar column index to a glossary term so headers can show a hint.
const headingTips: Record<number, GlossaryKey> = {
  6: "apr",
  7: "ivRank",
  8: "ivRank",
  9: "delta",
  10: "openInterest",
  11: "spread",
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
type RefreshKind = "universe" | "earnings" | "vix";

const copy = {
  en: {
    title: "Options Radar",
    intro: "Daily read-only scan for seller option candidates. No orders, no account unlock, no live trading.",
    date: "Scan date (history)",
    dateHelp: "This is the day a scan was run and saved — NOT an option expiry. Only days you already scanned appear here. To see today's hottest sell-side options, click \"Run Today's Scan\" below.",
    freshToday: "Showing today's scan.",
    freshStale: "Showing the scan from {date} ({days} day(s) ago). Click \"Run Today's Scan\" for fresh data.",
    freshNone: "No scan has been run yet. Click \"Run Today's Scan\" to generate today's seller candidates.",
    staleBlock:
      "This is an old snapshot. Expired contracts are history only; run today's scan before using the table for current research.",
    expiredRows: "Expired rows in full snapshot",
    strategy: "Strategy",
    all: "All",
    sellPut: "Sell Put",
    coveredCall: "Covered Call",
    sector: "Sector",
    dte: "DTE bucket",
    top: "Top N",
    safety: "Read-only research output. These rows are not trade instructions and cannot place orders.",
    export: "Export CSV",
    noData: "No daily scan snapshot found. Run today's scan to create a current Futu-backed snapshot.",
    rows: "Rows",
    scanned: "Scanned",
    failed: "Failed",
    regime: "Market regime",
    regimeUnknown: "Unknown - run `quant-system options refresh-vix` then re-scan to populate VIX history.",
    regimeNormal: "Normal - recent three-month VIX/VIX3M cache shows no market-regime score penalty.",
    regimeElevated: "Elevated - recent three-month VIX/VIX3M cache applies a moderate seller score penalty.",
    regimePanic: "Panic - recent three-month VIX/VIX3M cache applies a heavy seller score penalty.",
    details: "Details",
    openChain: "Open Chain",
    runSample: "Run Today's Scan",
    runDone: "Today's scan finished: {count} candidates saved for {date}.",
    running: "Running...",
    scanRunningTitle: "Scan in progress",
    scanRunningBody:
      "Futu scans can take several minutes. Keep this page open; the table will refresh when the saved snapshot is ready.",
    scanElapsed: "Elapsed",
    scheduledTask: "Scheduled task",
    taskLoading: "Loading task status...",
    taskMissing: "No scheduled task status has been written yet.",
    taskCompleted: "Completed",
    taskFailed: "Failed",
    taskCandidateCount: "Candidates",
    taskFailedStep: "Failed step",
    taskFinishedAt: "Finished",
    taskProvider: "Provider",
    refresh: "Refresh List",
    refreshSource: "Refresh source",
    publicSource: "Public data",
    sampleSource: "Local sample",
    refreshUniverse: "Refresh Universe",
    refreshEarnings: "Refresh Earnings",
    refreshVix: "Refresh VIX",
    eyebrow: "Read-only · Paper research",
    advanced: "Advanced data sources",
    advancedHint: "Manual Futu refreshes — these trigger slow scans. Not needed for normal use.",
    statusState: "Scan",
    statusScanning: "Running",
    statusIdle: "Idle",
    statusScanDate: "Scan date",
    statusDataAsOf: "Data as of",
    statusNone: "None",
    candidatesTitle: "Seller candidates",
    candidatesHint: "Each row is research output, not a trade instruction.",
    headings: ["Symbol", "Sector", "Strategy", "Expiry", "Strike", "Mid", "APR", "IV", "IVR", "Delta", "OI", "Spread", "Earnings", "Score", "Rating", ""],
  },
  zh: {
    title: "期权雷达",
    intro: "每日只读扫描卖方期权候选。不会下单、不会解锁账户、不会接入实盘。",
    date: "扫描日期（历史快照）",
    dateHelp: "这是“运行并保存扫描”的那一天，不是期权到期日。这里只会出现你扫描过的日期。想看今天最值得当卖方的期权，请点下方的“运行今日扫描”。",
    freshToday: "正在显示今天的扫描结果。",
    freshStale: "正在显示 {date} 的扫描结果（{days} 天前）。点“运行今日扫描”获取最新数据。",
    freshNone: "还没有运行过扫描。点“运行今日扫描”生成今天的卖方候选。",
    staleBlock: "这是旧快照。过期合约只适合回看历史；做当前研究前请先运行今日扫描。",
    expiredRows: "完整快照中过期合约数",
    strategy: "策略",
    all: "全部",
    sellPut: "卖出看跌",
    coveredCall: "备兑看涨",
    sector: "行业",
    dte: "DTE 区间",
    top: "显示数量",
    safety: "仅用于研究筛选。这些结果不是交易指令，也不能发出真实订单。",
    export: "导出 CSV",
    noData: "还没有每日扫描快照。请运行今日扫描，生成当前 Futu 数据快照。",
    rows: "候选",
    scanned: "已扫描",
    failed: "失败",
    regime: "市场状态",
    regimeUnknown: "未知 - 请先运行 `quant-system options refresh-vix` 刷新 VIX 历史后再扫描。",
    regimeNormal: "Normal - 不施加市场状态扣分。",
    regimeElevated: "Elevated - 对卖方候选施加中等评分扣分。",
    regimePanic: "Panic - 对卖方候选施加较重评分扣分。",
    details: "详情",
    openChain: "查看期权链",
    runSample: "运行今日扫描",
    runDone: "今日扫描完成：已为 {date} 保存 {count} 个候选。",
    running: "运行中...",
    scanRunningTitle: "正在扫描",
    scanRunningBody: "Futu 扫描可能需要几分钟。请保持页面打开；快照保存后右侧表格会自动刷新。",
    scanElapsed: "已等待",
    scheduledTask: "定时任务",
    taskLoading: "正在读取任务状态...",
    taskMissing: "尚未写入定时任务状态。",
    taskCompleted: "已完成",
    taskFailed: "失败",
    taskCandidateCount: "候选",
    taskFailedStep: "失败步骤",
    taskFinishedAt: "完成时间",
    taskProvider: "数据源",
    refresh: "刷新列表",
    refreshSource: "刷新数据源",
    publicSource: "公开数据",
    sampleSource: "本地样例",
    refreshUniverse: "刷新标的池",
    refreshEarnings: "刷新财报日历",
    refreshVix: "刷新 VIX",
    eyebrow: "只读 · 模拟研究",
    advanced: "高级数据源",
    advancedHint: "手动触发 Futu 刷新——会启动较慢的扫描。日常使用无需操作。",
    statusState: "扫描",
    statusScanning: "进行中",
    statusIdle: "空闲",
    statusScanDate: "扫描日期",
    statusDataAsOf: "数据截至",
    statusNone: "无",
    candidatesTitle: "卖方候选",
    candidatesHint: "每一行都是研究筛选结果，不是交易指令。",
    headings: ["标的", "行业", "策略", "到期", "行权价", "中间价", "年化", "IV", "IVR", "Delta", "未平仓", "价差", "财报", "分数", "评级", ""],
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
  const [top, setTop] = useState(50);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [refreshSource, setRefreshSource] = useState("public");
  const [refreshStatus, setRefreshStatus] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [scanStatus, setScanStatus] = useState<string | null>(null);
  const [scanStartedAt, setScanStartedAt] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const datesQuery = useQuery({
    queryKey: ["options-radar-dates"],
    enabled: hydrated,
    queryFn: getOptionsRadarDates,
  });
  const taskStatusQuery = useQuery({
    queryKey: ["options-daily-task-status"],
    enabled: hydrated,
    queryFn: () =>
      apiRequest<OptionsDailyScanStatusResponse>("/api/options/daily-scan/status"),
  });

  const activeDate = date || datesQuery.data?.dates[0] || "";
  const scanPath = buildScanPath({
    date: activeDate,
    strategy,
    sector,
    dteBucket,
    top,
  });
  const scanQuery = useQuery({
    queryKey: ["options-radar", activeDate, strategy, sector, dteBucket, top],
    enabled: hydrated,
    queryFn: () => apiRequest<OptionsDailyScanResponse>(scanPath),
  });

  const candidates = useMemo(
    () => scanQuery.data?.candidates ?? [],
    [scanQuery.data?.candidates],
  );
  const csv = useMemo(() => buildCsv(candidates), [candidates]);
  const regime = useMemo(() => deriveRegime(candidates), [candidates]);
  const freshness = useMemo(
    () => deriveFreshness(activeDate, datesQuery.data?.dates ?? [], text),
    [activeDate, datesQuery.data?.dates, text],
  );
  const scanMutation = useMutation({
    mutationFn: () =>
      apiPost<OptionsDailyScanRunResponse>("/api/options/daily-scan/run", {
        provider: "futu",
        top,
        strategies: strategy === "all" ? ["sell_put", "covered_call"] : [strategy],
      }),
    onMutate: () => {
      setScanStatus(null);
      setScanStartedAt(Date.now());
      setElapsedSeconds(0);
    },
    onSuccess: async (payload) => {
      setDate(payload.run_date);
      setScanStatus(
        text.runDone
          .replace("{date}", payload.run_date)
          .replace("{count}", String(payload.candidate_count)),
      );
      await queryClient.invalidateQueries({ queryKey: ["options-radar-dates"] });
      await queryClient.fetchQuery({
        queryKey: ["options-radar", payload.run_date, strategy, sector, dteBucket, top],
        queryFn: () =>
          apiRequest<OptionsDailyScanResponse>(
            buildScanPath({
              date: payload.run_date,
              strategy,
              sector,
              dteBucket,
              top,
            }),
          ),
      });
      await queryClient.invalidateQueries({ queryKey: ["options-radar"] });
    },
    onSettled: () => {
      setScanStartedAt(null);
    },
  });
  const refreshMutation = useMutation({
    mutationFn: (kind: RefreshKind) =>
      apiPost<OptionsRefreshResponse>(`/api/options/refresh/${kind}`, {
        source: refreshSource,
        top,
      }),
    onSuccess: async (payload) => {
      const label = payload.kind === "vix" ? "VIX" : capitalize(payload.kind);
      setRefreshStatus(`${label} refreshed (${payload.row_count} rows)`);
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

  useEffect(() => {
    if (!scanMutation.isPending || scanStartedAt === null) {
      return;
    }
    const updateElapsed = () =>
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - scanStartedAt) / 1000)));
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [scanMutation.isPending, scanStartedAt]);

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
              onChange={(event) => setDate(event.target.value)}
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
                <option key={item} value={item}>{item}</option>
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
              <option value="7-21">7-21</option>
              <option value="21-45">21-45</option>
              <option value="45-60">45-60</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.top}
            <input
              className={`${selectClass} font-data-mono`}
              min={1}
              max={250}
              onChange={(event) => setTop(Number(event.target.value))}
              type="number"
              value={top}
            />
          </label>
          <TerminalToolbarButton
            className="h-10 w-full justify-center"
            disabled={!hydrated || scanMutation.isPending}
            onClick={() => scanMutation.mutate()}
            tone="info"
            type="button"
          >
            <RefreshCw className="mr-2 inline" size={16} />
            {scanMutation.isPending ? text.running : text.runSample}
          </TerminalToolbarButton>
          <div className="grid grid-cols-2 gap-2">
            <TerminalToolbarButton
              className="h-10 justify-center px-4"
              disabled={!hydrated || datesQuery.isFetching || scanQuery.isFetching}
              onClick={() => {
                void datesQuery.refetch();
                void scanQuery.refetch();
              }}
              tone="neutral"
              type="button"
            >
              <RefreshCw className="mr-2 inline" size={16} />
              {text.refresh}
            </TerminalToolbarButton>
            <TerminalToolbarButton
              className="h-10 justify-center px-4"
              disabled={!hydrated || !csv || candidates.length === 0}
              onClick={exportCsv}
              tone="info"
              type="button"
            >
              <Download className="mr-2 inline" size={16} />
              {text.export}
            </TerminalToolbarButton>
          </div>
          {scanMutation.error instanceof Error ? (
            <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 font-body-sm text-danger">
              {scanMutation.error.message}
            </div>
          ) : null}
          {scanStatus ? (
            <div className="rounded-lg border border-accent-success/40 bg-accent-success/10 p-3 font-body-sm text-accent-success">
              {scanStatus}
            </div>
          ) : null}
          <div className="mt-1 rounded-lg border border-border-subtle bg-bg-surface-muted">
            <button
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left font-label-caps text-text-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
              onClick={() => setAdvancedOpen((open) => !open)}
              type="button"
            >
              <span>{text.advanced}</span>
              {advancedOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
            {advancedOpen ? (
              <div className="border-t border-border-subtle p-3">
                <p className="mb-3 font-body-sm text-text-secondary">{text.advancedHint}</p>
                <label className="flex flex-col gap-1 font-body-sm">
                  {text.refreshSource}
                  <select
                    className={selectClass}
                    onChange={(event) => setRefreshSource(event.target.value)}
                    value={refreshSource}
                  >
                    <option value="public">
                      {text.publicSource}
                    </option>
                    <option value="sample">
                      {text.sampleSource}
                    </option>
                  </select>
                </label>
                <div className="mt-3 grid grid-cols-1 gap-2">
                  <TerminalToolbarButton
                    className="h-10 w-full justify-center"
                    disabled={!hydrated || refreshMutation.isPending}
                    onClick={() => refreshMutation.mutate("universe")}
                    tone="neutral"
                    type="button"
                  >
                    <RefreshCw className="mr-2 inline" size={16} />
                    {text.refreshUniverse}
                  </TerminalToolbarButton>
                  <TerminalToolbarButton
                    className="h-10 w-full justify-center"
                    disabled={!hydrated || refreshMutation.isPending}
                    onClick={() => refreshMutation.mutate("earnings")}
                    tone="neutral"
                    type="button"
                  >
                    <RefreshCw className="mr-2 inline" size={16} />
                    {text.refreshEarnings}
                  </TerminalToolbarButton>
                  <TerminalToolbarButton
                    className="h-10 w-full justify-center"
                    disabled={!hydrated || refreshMutation.isPending}
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
                    {refreshMutation.error.message}
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
                value={scanMutation.isPending ? `${text.statusScanning} ${elapsedSeconds}s` : text.statusIdle}
                tone={scanMutation.isPending ? "info" : "neutral"}
              />
              <StatusPill
                label={text.statusScanDate}
                value={activeDate || text.statusNone}
                tone="neutral"
              />
              <StatusPill
                label={text.statusDataAsOf}
                value={scanQuery.data?.run_date ?? activeDate ?? text.statusNone}
                tone={freshness?.fresh ? "success" : scanQuery.data?.is_stale ? "danger" : "neutral"}
              />
            </div>
          }
        />
        <ScheduledTaskStatusCard
          error={taskStatusQuery.error}
          isLoading={taskStatusQuery.isLoading}
          response={taskStatusQuery.data}
          text={text}
        />
        {scanMutation.isPending ? (
          <Card tone="info">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-label-caps text-info">{text.scanRunningTitle}</h2>
                <p className="mt-1 font-body-sm text-text-secondary">{text.scanRunningBody}</p>
              </div>
              <div className="rounded-lg border border-info/30 px-3 py-2 font-data-mono text-sm text-info">
                {text.scanElapsed}: {elapsedSeconds}s
              </div>
            </div>
          </Card>
        ) : null}
        <RegimeBanner regime={regime} text={text} />
        {freshness ? (
          <div
            className={`rounded-lg border p-3 font-body-sm ${
              freshness.fresh
                ? "border-accent-success/40 bg-accent-success/10 text-accent-success"
                : "border-warning/40 bg-warning/10 text-warning"
            }`}
          >
            {freshness.message}
          </div>
        ) : null}
        {scanQuery.data?.is_stale ? (
          <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 font-body-sm text-danger">
            <p className="font-semibold">{text.staleBlock}</p>
            <p className="mt-1">
              {text.expiredRows}: {scanQuery.data.expired_candidate_count ?? 0}
            </p>
          </div>
        ) : null}
        <section className="grid grid-cols-3 gap-3">
          <MetricStat label={text.rows} value={String(candidates.length)} tone="neutral" />
          <MetricStat label={text.scanned} value={String(scanQuery.data?.scanned_tickers ?? 0)} />
          <MetricStat
            label={text.failed}
            value={String(scanQuery.data?.failed_tickers.length ?? 0)}
            tone={(scanQuery.data?.failed_tickers.length ?? 0) > 0 ? "warning" : "neutral"}
          />
        </section>
        {(scanQuery.data?.scanned_tickers ?? 0) <= 1 && candidates.length > 0 ? (
          <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 font-body-sm text-warning">
            {locale === "zh"
              ? "当前快照只包含很少标的，所以表格可能集中在单一股票。运行 quant-system options daily-scan --top 100 可生成更完整的全市场扫描。"
              : "This snapshot only scanned a very small universe, so the table may concentrate in one ticker. Run quant-system options daily-scan --top 100 for a broader market scan."}
          </div>
        ) : null}
        <Card padded={false}>
          <div className="border-b border-border-subtle px-4 py-3">
            <SectionTitle title={text.candidatesTitle} hint={text.candidatesHint} />
          </div>
          {scanQuery.isLoading ? (
            <div className="p-6 font-body-sm text-text-secondary">Loading daily scan...</div>
          ) : scanQuery.isError || candidates.length === 0 ? (
            <div className="p-6 font-body-sm text-text-secondary">
              {scanQuery.error instanceof Error ? scanQuery.error.message : text.noData}
            </div>
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
              <tbody className="font-data-mono text-data-mono text-text-primary">
                {candidates.map((candidate) => (
                  <Fragment key={candidate.symbol}>
                    <tr className="border-b border-border-subtle/50">
                      <td className="px-3 py-2">{candidate.ticker}</td>
                      <td className="px-3 py-2">{candidate.sector ?? "--"}</td>
                      <td className="px-3 py-2">{candidate.strategy}</td>
                      <td className="px-3 py-2">{candidate.expiry}</td>
                      <td className="px-3 py-2">{fmt(candidate.strike)}</td>
                      <td className="px-3 py-2">{fmt(candidate.mid)}</td>
                      <td className="px-3 py-2">{pct(candidate.annualized_yield)}</td>
                      <td className="px-3 py-2">{pct(candidate.implied_volatility)}</td>
                      <td className="px-3 py-2">{fmt(candidate.iv_rank, 1)}</td>
                      <td className="px-3 py-2">{fmt(candidate.delta, 3)}</td>
                      <td className="px-3 py-2">{fmt(candidate.open_interest, 0)}</td>
                      <td className="px-3 py-2">{pct(candidate.spread_pct)}</td>
                      <td className="px-3 py-2">{candidate.earnings_in_window ? "Yes" : "No"}</td>
                      <td className="px-3 py-2">{fmt(candidate.global_score, 1)}</td>
                      <td className="px-3 py-2">{candidate.rating}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-3">
                          <button
                            className="rounded-md text-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
                            onClick={() => setExpanded(expanded === candidate.symbol ? null : candidate.symbol)}
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
                    {expanded === candidate.symbol ? (
                      <tr className="border-b border-border-subtle/50">
                        <td className="px-3 py-3 font-body-sm text-text-secondary" colSpan={16}>
                          {candidateDetail(candidate, locale)}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          )}
        </Card>
    </TerminalSplitShell>
  );
}

type RegimeInfo = {
  label: "Normal" | "Elevated" | "Panic" | "Unknown";
  penalty: number | null;
};
type RegimeCopy = {
  regime: string;
  regimeNormal: string;
  regimeElevated: string;
  regimePanic: string;
  regimeUnknown: string;
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

function deriveFreshness(
  activeDate: string,
  dates: string[],
  text: { freshToday: string; freshStale: string; freshNone: string },
): { fresh: boolean; message: string } | null {
  if (dates.length === 0) {
    return { fresh: false, message: text.freshNone };
  }
  if (!activeDate) return null;
  const today = new Date();
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  if (activeDate === todayIso) {
    return { fresh: true, message: text.freshToday };
  }
  const parsed = Date.parse(activeDate);
  let days = 0;
  if (!Number.isNaN(parsed)) {
    const diffMs = Date.parse(todayIso) - parsed;
    days = Math.max(0, Math.round(diffMs / 86_400_000));
  }
  return {
    fresh: false,
    message: text.freshStale.replace("{date}", activeDate).replace("{days}", String(days)),
  };
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

function ScheduledTaskStatusCard({
  error,
  isLoading,
  response,
  text,
}: {
  error: unknown;
  isLoading: boolean;
  response?: OptionsDailyScanStatusResponse;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  const status = response?.status ?? null;
  const state = status?.status ?? null;
  const tone: "danger" | "success" | "neutral" =
    state === "failed" ? "danger" : state === "completed" ? "success" : "neutral";
  const statusLabel =
    state === "failed"
      ? text.taskFailed
      : state === "completed"
        ? text.taskCompleted
        : state ?? "--";
  const candidateCount = taskCandidateCount(status);

  return (
    <Card tone={tone}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-label-caps text-text-primary">{text.scheduledTask}</h2>
          <p className="mt-1 font-body-sm text-text-secondary">
            {isLoading
              ? text.taskLoading
              : error instanceof Error
                ? error.message
                : response?.exists
                  ? `${statusLabel}${status?.run_date ? ` · ${status.run_date}` : ""}`
                  : text.taskMissing}
          </p>
        </div>
        {response?.exists && status ? (
          <div className="flex flex-wrap items-center gap-2 font-data-mono text-xs text-text-secondary">
            {status.provider ? <span>{text.taskProvider}: {status.provider}</span> : null}
            {candidateCount !== null ? (
              <span>{text.taskCandidateCount}: {candidateCount}</span>
            ) : null}
            {status.failed_step ? (
              <span className="text-danger">{text.taskFailedStep}: {status.failed_step}</span>
            ) : null}
            {status.finished_at ? (
              <span>{text.taskFinishedAt}: {formatTaskTime(status.finished_at)}</span>
            ) : null}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function taskCandidateCount(status: OptionsDailyTaskStatus | null): number | null {
  const scan = status?.steps?.scan;
  const value = scan?.candidate_count;
  return typeof value === "number" ? value : null;
}

function formatTaskTime(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function RegimeBanner({
  regime,
  text,
}: {
  regime: RegimeInfo;
  text: RegimeCopy;
}) {
  const palette: Record<RegimeInfo["label"], string> = {
    Normal: "border-accent-success/40 bg-accent-success/10 text-accent-success",
    Elevated: "border-warning/40 bg-warning/10 text-warning",
    Panic: "border-danger/40 bg-danger/10 text-danger",
    Unknown: "border-border-subtle bg-bg-surface text-text-secondary",
  };
  const detail =
    regime.label === "Normal"
      ? text.regimeNormal
      : regime.label === "Elevated"
        ? text.regimeElevated
        : regime.label === "Panic"
          ? text.regimePanic
          : text.regimeUnknown;
  return (
    <div className={`rounded-lg border p-3 font-body-sm ${palette[regime.label]}`}>
      <div className="flex items-center justify-between">
        <span className="font-label-caps">{text.regime}</span>
        <span className="font-data-mono text-sm font-bold">{regime.label}</span>
      </div>
      <p className="mt-1 leading-snug">{detail}</p>
    </div>
  );
}

function fmt(value?: number | null, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function pct(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "--";
}

function candidateDetail(candidate: OptionsRadarCandidate, locale: "en" | "zh") {
  if (candidate.notes.length) {
    return candidate.notes.join(" | ");
  }
  const parts = [
    locale === "zh" ? `合约 ${candidate.symbol}` : `Contract ${candidate.symbol}`,
    locale === "zh"
      ? `分数 ${fmt(candidate.global_score, 1)}`
      : `score ${fmt(candidate.global_score, 1)}`,
    locale === "zh"
      ? `市场状态 ${candidate.market_regime ?? "Unknown"}`
      : `market regime ${candidate.market_regime ?? "Unknown"}`,
    locale === "zh"
      ? `价差 ${pct(candidate.spread_pct)}`
      : `spread ${pct(candidate.spread_pct)}`,
    locale === "zh"
      ? `未平仓 ${fmt(candidate.open_interest, 0)}`
      : `open interest ${fmt(candidate.open_interest, 0)}`,
  ];
  return parts.join(" | ");
}

function buildCsv(candidates: OptionsRadarCandidate[]) {
  const headers = ["ticker", "sector", "strategy", "symbol", "expiry", "strike", "mid", "apr", "iv", "iv_rank", "delta", "oi", "spread", "earnings", "score", "rating"];
  const rows = candidates.map((item) =>
    [
      item.ticker,
      item.sector ?? "",
      item.strategy,
      item.symbol,
      item.expiry,
      item.strike,
      item.mid ?? "",
      item.annualized_yield ?? "",
      item.implied_volatility ?? "",
      item.iv_rank ?? "",
      item.delta ?? "",
      item.open_interest ?? "",
      item.spread_pct ?? "",
      item.earnings_in_window ? "yes" : "no",
      item.global_score,
      item.rating,
    ].join(","),
  );
  return [headers.join(","), ...rows].join("\n");
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
