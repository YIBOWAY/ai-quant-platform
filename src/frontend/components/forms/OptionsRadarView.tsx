'use client';

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, RefreshCw, ShieldCheck } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";
import type {
  OptionsRadarCandidate,
  OptionsRadarDatesResponse,
  OptionsRefreshResponse,
  OptionsRadarRunResponse,
  OptionsRadarResponse,
} from "@/lib/api";
import { apiPost, apiRequest } from "@/lib/apiClient";
import { InfoTip, type GlossaryKey } from "@/components/InfoTip";
import { useIsHydrated } from "@/lib/hydration";
import { localizePath } from "@/lib/locale";

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };

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
    zh: "中文",
    details: "Details",
    openChain: "Open Chain",
    runSample: "Run Today's Scan",
    runDone: "Today's scan finished: {count} candidates saved for {date}.",
    running: "Running...",
    scanRunningTitle: "Scan in progress",
    scanRunningBody:
      "Futu scans can take several minutes. Keep this page open; the table will refresh when the saved snapshot is ready.",
    scanElapsed: "Elapsed",
    refresh: "Refresh List",
    refreshSource: "Refresh source",
    publicSource: "Public data",
    sampleSource: "Local sample",
    refreshUniverse: "Refresh Universe",
    refreshEarnings: "Refresh Earnings",
    refreshVix: "Refresh VIX",
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
    zh: "English",
    details: "详情",
    openChain: "查看期权链",
    runSample: "运行今日扫描",
    runDone: "今日扫描完成：已为 {date} 保存 {count} 个候选。",
    running: "运行中...",
    scanRunningTitle: "正在扫描",
    scanRunningBody: "Futu 扫描可能需要几分钟。请保持页面打开；快照保存后右侧表格会自动刷新。",
    scanElapsed: "已等待",
    refresh: "刷新列表",
    refreshSource: "刷新数据源",
    publicSource: "公开数据",
    sampleSource: "本地样例",
    refreshUniverse: "刷新标的池",
    refreshEarnings: "刷新财报日历",
    refreshVix: "刷新 VIX",
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
  const [scanStatus, setScanStatus] = useState<string | null>(null);
  const [scanStartedAt, setScanStartedAt] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const datesQuery = useQuery({
    queryKey: ["options-radar-dates"],
    enabled: hydrated,
    queryFn: () => apiRequest<OptionsRadarDatesResponse>("/api/options/daily-scan/dates"),
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
    queryFn: () => apiRequest<OptionsRadarResponse>(scanPath),
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
      apiPost<OptionsRadarRunResponse>("/api/options/daily-scan/run", {
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
          apiRequest<OptionsRadarResponse>(
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
    <div className="grid h-full min-h-0 grid-cols-[360px_1fr] overflow-hidden bg-base text-text-primary">
      <aside className="overflow-y-auto border-r border-border-subtle bg-bg-surface p-4">
        <h1 className="font-headline-lg text-text-primary">{text.title}</h1>
        <p className="mt-2 font-body-sm text-text-secondary">{text.intro}</p>
        <a
          className="mt-3 inline-flex whitespace-nowrap font-body-sm text-info"
          href={localizePath("/options-radar", locale === "zh" ? "en" : "zh")}
        >
          {text.zh}
        </a>
        <form className="mt-5 flex flex-col gap-4" onSubmit={(event) => event.preventDefault()}>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.date}
            <select
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary"
              onChange={(event) => setDate(event.target.value)}
              value={activeDate}
            >
              {datesQuery.data?.dates.map((item) => (
                <option key={item} style={optionStyle} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <p className="-mt-2 font-body-sm text-text-secondary">{text.dateHelp}</p>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.strategy}
            <select
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary"
              onChange={(event) => setStrategy(event.target.value)}
              value={strategy}
            >
              <option style={optionStyle} value="all">{text.all}</option>
              <option style={optionStyle} value="sell_put">{text.sellPut}</option>
              <option style={optionStyle} value="covered_call">{text.coveredCall}</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.sector}
            <select
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary"
              onChange={(event) => setSector(event.target.value)}
              value={sector}
            >
              <option style={optionStyle} value="">{text.all}</option>
              {sectors.map((item) => (
                <option key={item} style={optionStyle} value={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.dte}
            <select
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary"
              onChange={(event) => setDteBucket(event.target.value)}
              value={dteBucket}
            >
              <option style={optionStyle} value="">{text.all}</option>
              <option style={optionStyle} value="7-21">7-21</option>
              <option style={optionStyle} value="21-45">21-45</option>
              <option style={optionStyle} value="45-60">45-60</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.top}
            <input
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
              min={1}
              max={250}
              onChange={(event) => setTop(Number(event.target.value))}
              type="number"
              value={top}
            />
          </label>
          <div className="rounded border border-border-subtle bg-surface-muted p-3">
            <label className="flex flex-col gap-1 font-body-sm">
              {text.refreshSource}
              <select
                className="rounded border border-border-subtle bg-bg-surface px-3 py-2 text-text-primary"
                onChange={(event) => setRefreshSource(event.target.value)}
                value={refreshSource}
              >
                <option style={optionStyle} value="public">
                  {text.publicSource}
                </option>
                <option style={optionStyle} value="sample">
                  {text.sampleSource}
                </option>
              </select>
            </label>
            <div className="mt-3 grid grid-cols-1 gap-2">
              <button
                className="rounded border border-border-subtle px-3 py-2 font-body-sm text-text-primary disabled:opacity-50"
                disabled={!hydrated || refreshMutation.isPending}
                onClick={() => refreshMutation.mutate("universe")}
                type="button"
              >
                <RefreshCw className="mr-2 inline" size={16} />
                {text.refreshUniverse}
              </button>
              <button
                className="rounded border border-border-subtle px-3 py-2 font-body-sm text-text-primary disabled:opacity-50"
                disabled={!hydrated || refreshMutation.isPending}
                onClick={() => refreshMutation.mutate("earnings")}
                type="button"
              >
                <RefreshCw className="mr-2 inline" size={16} />
                {text.refreshEarnings}
              </button>
              <button
                className="rounded border border-border-subtle px-3 py-2 font-body-sm text-text-primary disabled:opacity-50"
                disabled={!hydrated || refreshMutation.isPending}
                onClick={() => refreshMutation.mutate("vix")}
                type="button"
              >
                <RefreshCw className="mr-2 inline" size={16} />
                {text.refreshVix}
              </button>
            </div>
            {refreshStatus ? (
              <div className="mt-3 rounded border border-accent-success/40 bg-accent-success/10 p-2 font-body-sm text-accent-success">
                {refreshStatus}
              </div>
            ) : null}
            {refreshMutation.error instanceof Error ? (
              <div className="mt-3 rounded border border-danger/40 bg-danger/10 p-2 font-body-sm text-danger">
                {refreshMutation.error.message}
              </div>
            ) : null}
          </div>
          <button
            className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:opacity-50"
            disabled={!hydrated || scanMutation.isPending}
            onClick={() => scanMutation.mutate()}
            type="button"
          >
            <RefreshCw className="mr-2 inline" size={16} />
            {scanMutation.isPending ? text.running : text.runSample}
          </button>
          <button
            className="rounded border border-border-subtle px-4 py-2 font-body-sm text-text-primary disabled:opacity-50"
            disabled={!hydrated || datesQuery.isFetching || scanQuery.isFetching}
            onClick={() => {
              void datesQuery.refetch();
              void scanQuery.refetch();
            }}
            type="button"
          >
            <RefreshCw className="mr-2 inline" size={16} />
            {text.refresh}
          </button>
          <button
            className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:opacity-50"
            disabled={!hydrated || !csv || candidates.length === 0}
            onClick={exportCsv}
            type="button"
          >
            <Download className="mr-2 inline" size={16} />
            {text.export}
          </button>
          {scanMutation.error instanceof Error ? (
            <div className="rounded border border-danger/40 bg-danger/10 p-3 font-body-sm text-danger">
              {scanMutation.error.message}
            </div>
          ) : null}
          {scanStatus ? (
            <div className="rounded border border-accent-success/40 bg-accent-success/10 p-3 font-body-sm text-accent-success">
              {scanStatus}
            </div>
          ) : null}
        </form>
      </aside>
      <main className="min-w-0 overflow-y-auto p-5">
        <div className="mb-4 flex items-center gap-2 rounded border border-warning/40 bg-warning/10 p-3 font-body-sm text-warning">
          <ShieldCheck size={18} />
          {text.safety}
        </div>
        {scanMutation.isPending ? (
          <section className="mb-4 rounded border border-info/40 bg-info/10 p-4 text-info">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-headline-lg text-info">{text.scanRunningTitle}</h2>
                <p className="mt-1 font-body-sm text-text-secondary">{text.scanRunningBody}</p>
              </div>
              <div className="rounded border border-info/30 px-3 py-2 font-data-mono text-sm">
                {text.scanElapsed}: {elapsedSeconds}s
              </div>
            </div>
          </section>
        ) : null}
        <RegimeBanner regime={regime} text={text} />
        {freshness ? (
          <div
            className={`mb-4 rounded border p-3 font-body-sm ${
              freshness.fresh
                ? "border-accent-success/40 bg-accent-success/10 text-accent-success"
                : "border-warning/40 bg-warning/10 text-warning"
            }`}
          >
            {freshness.message}
          </div>
        ) : null}
        {scanQuery.data?.is_stale ? (
          <div className="mb-4 rounded border border-danger/40 bg-danger/10 p-3 font-body-sm text-danger">
            <p className="font-semibold">{text.staleBlock}</p>
            <p className="mt-1">
              {text.expiredRows}: {scanQuery.data.expired_candidate_count ?? 0}
            </p>
          </div>
        ) : null}
        <section className="mb-4 grid grid-cols-3 gap-3">
          <Metric label={text.rows} value={String(candidates.length)} />
          <Metric label={text.scanned} value={String(scanQuery.data?.scanned_tickers ?? 0)} />
          <Metric label={text.failed} value={String(scanQuery.data?.failed_tickers.length ?? 0)} />
        </section>
        {(scanQuery.data?.scanned_tickers ?? 0) <= 1 && candidates.length > 0 ? (
          <div className="mb-4 rounded border border-warning/40 bg-warning/10 p-3 font-body-sm text-warning">
            {locale === "zh"
              ? "当前快照只包含很少标的，所以表格可能集中在单一股票。运行 quant-system options daily-scan --top 100 可生成更完整的全市场扫描。"
              : "This snapshot only scanned a very small universe, so the table may concentrate in one ticker. Run quant-system options daily-scan --top 100 for a broader market scan."}
          </div>
        ) : null}
        {scanQuery.isLoading ? (
          <div className="rounded border border-border-subtle bg-bg-surface p-6 font-body-sm text-text-secondary">
            Loading daily scan...
          </div>
        ) : scanQuery.isError || candidates.length === 0 ? (
          <div className="rounded border border-border-subtle bg-bg-surface p-6 font-body-sm text-text-secondary">
            {scanQuery.error instanceof Error ? scanQuery.error.message : text.noData}
          </div>
        ) : (
          <div className="overflow-x-auto rounded border border-border-subtle bg-bg-surface">
            <table className="w-full border-collapse text-left">
              <thead>
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
                            className="text-info"
                            onClick={() => setExpanded(expanded === candidate.symbol ? null : candidate.symbol)}
                            type="button"
                          >
                            {text.details}
                          </button>
                          <Link
                            className="inline-flex items-center gap-1 text-accent-success"
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
      </main>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-3">
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className="mt-2 font-data-mono text-lg font-bold text-text-primary">{value}</div>
    </div>
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
    Panic: "border-accent-danger/40 bg-accent-danger/10 text-accent-danger",
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
    <div className={`mb-4 rounded border p-3 font-body-sm ${palette[regime.label]}`}>
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
