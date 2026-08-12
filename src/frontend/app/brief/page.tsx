import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { ErrorBanner } from "@/components/ErrorBanner";
import { BriefArchiveSidebar } from "@/components/brief/BriefArchiveSidebar";
import { BriefDailyChange } from "@/components/brief/BriefDailyChange";
import { BriefPerformanceChart } from "@/components/brief/BriefPerformanceChart";
import { BriefPerformanceRangeSelector } from "@/components/brief/BriefPerformanceRangeSelector";
import { PaperEquityFigureState } from "@/components/brief/PaperEquityFigureState";
import {
  formatMoney,
  formatPercent,
  getAgentCandidates,
  getBacktests,
  getFactors,
  getNewsItems,
  getNewsMarketTopics,
  getOptionsDailyScanStatus,
  getPaperRuns,
  getRecentRuns,
  getSymbols,
  type AccountPositionResponse,
  type MarketDataHistoryResponse,
  type OptionsDailyScanStatusResponse,
  type RecentRun,
} from "@/lib/api";
import { buildAsiaRadarNote } from "@/lib/briefAsiaRadarNote";
import {
  dashboardRunHref,
  dashboardRunKindLabel,
  dashboardRunSummary,
  formatCount,
} from "@/lib/dashboardRuns";
import { isSampleSource } from "@/lib/runSource";
import { localizePath } from "@/lib/locale";
import type { BriefArchivePayload } from "@/lib/briefArchive";
import { buildBriefAiNewsDigest, mapDigestToBriefAiNews } from "@/lib/briefAiNewsDigest";
import { briefDateKey } from "@/lib/briefDate";
import {
  parseBriefPerformanceRange,
  selectBriefPerformanceResponse,
  type BriefPerformanceRange,
} from "@/lib/briefPerformance";
import {
  getCachedAsiaRadarSummary,
  getCachedBriefMarketDataHistory,
  getCachedBriefPaperAccount,
  getCachedBriefPaperAccountEquityCurve,
  getCachedBriefPaperAccountPerformance,
  getCachedSettings,
} from "@/lib/serverApi";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    volume: "VOL. CXXIII",
    edition: "U.S. research edition",
    title: "Daily Morning Brief",
    subtitle: "HERMES MORNING BRIEF · A QUANTITATIVE LETTER",
    author: "Platform factual desk",
    subscriber: "subscriber one · private use",
    safetyLine: "paper-only journal · dry-run rehearsal · live trading never implied active",
    ledeByline: "Compiled from platform facts",
    account: "Account",
    accountEn: "THE ACCOUNT",
    equity: "Equity",
    cash: "Cash",
    invested: "Invested",
    priceSource: "Price source",
    symbol: "Symbol",
    qty: "Qty",
    avg: "Avg",
    last: "Last",
    marketValue: "Market value",
    dayChange: "Daily",
    emptyPositions: "No current positions",
    accountSource: "source: local paper account engine",
    accountUnavailable: "Paper account unavailable; factual archive is blocked.",
    backtest: "Paper Return",
    backtestEn: "PAPER VS SPY · QQQ",
    figureTitle: "Figure 1 · cumulative return rebased to 0%",
    chartSource: "source: paper-account ledger + Futu QFQ daily closes",
    latestRun: "paper account",
    cumulativeReturn: "selected return",
    sharpe: "sessions",
    maxDrawdown: "latest equity",
    chartNote: "Paper is replayed from the account ledger; SPY and QQQ use the same completed Futu trading sessions. Every visible line starts at 0%.",
    noChart: "No aligned paper / SPY / QQQ sessions are available.",
    chartUnavailable: "Paper-account performance data unavailable.",
    market: "Market",
    marketEn: "THE MARKET",
    marketSummary: "Market summary",
    marketUnavailable: "market move unavailable",
    topics: "Market Topics",
    topicsEn: "MARKET TOPICS WIRE",
    noTopics: "No market topics are available from the news lane.",
    topicsUnconfigured:
      "Market news feed is not configured; topics omitted this issue.",
    quote:
      "Market data is incomplete; waiting for fresh SPY, QQQ, SOXX, and IGV daily bars before forming a full market read.",
    quoteSig: "Platform market note",
    digest: "AI Intelligence Digest",
    digestEn: "INTELLIGENCE DIGEST",
    noDigest: "No AI intelligence items are available from the local feed.",
    score: "score",
    log: "Run Record",
    logEn: "THE LOG · ERRATA STYLE",
    noRuns: "No recent runs yet.",
    footer: "private quant research journal · paper trading · not investment advice · printed locally",
    liveTrading: "live trading",
    neverActive: "never implied active",
    on: "on",
    off: "off",
    unavailable: "unavailable",
  },
  zh: {
    volume: "VOL. CXXIII",
    edition: "美股研究版",
    title: "每日晨报",
    subtitle: "HERMES MORNING BRIEF · A QUANTITATIVE LETTER",
    author: "平台事实台",
    subscriber: "订户一人 · 自用",
    safetyLine: "本刊为模拟盘刊物 · DRY-RUN 演练 · live trading never implied active",
    ledeByline: "导语由平台事实排印",
    account: "账户",
    accountEn: "THE ACCOUNT",
    equity: "权益",
    cash: "现金",
    invested: "已投入",
    priceSource: "价格源",
    symbol: "标的",
    qty: "数量",
    avg: "均价",
    last: "现价",
    marketValue: "市值",
    dayChange: "日涨跌",
    emptyPositions: "当前空仓",
    accountSource: "资料来源：本地模拟盘引擎",
    accountUnavailable: "模拟账户不可用，已禁止保存事实归档。",
    backtest: "模拟盘收益",
    backtestEn: "PAPER VS SPY · QQQ",
    figureTitle: "图一 · 累计收益统一归零比较",
    chartSource: "来源：模拟账户账本 + Futu 前复权日线收盘",
    latestRun: "模拟账户",
    cumulativeReturn: "所选区间收益",
    sharpe: "交易日",
    maxDrawdown: "最新权益",
    chartNote: "模拟盘由账户账本逐日回放；SPY 与 QQQ 使用相同的 Futu 已完成交易日，三条可用曲线首日统一为 0%。",
    noChart: "暂无可对齐的模拟盘、SPY 与 QQQ 交易日。",
    chartUnavailable: "模拟盘收益数据不可用。",
    market: "市场",
    marketEn: "THE MARKET",
    marketSummary: "市场概括",
    marketUnavailable: "市场涨跌数据不足",
    topics: "市场要闻",
    topicsEn: "MARKET TOPICS WIRE",
    noTopics: "市场新闻源暂无可匹配要闻。",
    topicsUnconfigured: "市场新闻源未配置，本期要闻略。",
    quoteSig: "平台市场手记",
    quote:
      "市场涨跌数据暂不完整；待 SPY、QQQ、SOXX、IGV 四组日线全部刷新后再形成完整判断。",
    digest: "AI 情报摘要",
    digestEn: "INTELLIGENCE DIGEST",
    noDigest: "本地 AI 情报源暂无条目。",
    score: "评分",
    log: "运行记录",
    logEn: "THE LOG · 勘误式",
    noRuns: "暂无近期运行。",
    footer: "一人量化研究刊物 · 模拟盘 · 非投资建议 · 印刷于本地",
    liveTrading: "live trading",
    neverActive: "never implied active",
    on: "开",
    off: "关",
    unavailable: "不可用",
  },
} as const;

type BriefCopy = (typeof copy)["en"] | (typeof copy)["zh"];
type MarketSnapshot = {
  symbol: "SPY" | "QQQ" | "SOXX" | "IGV";
  last?: number;
  changePct?: number;
  source?: string;
  asOf?: string;
};

type BriefLogEntry = {
  timestamp?: string | null;
  status: "ok" | "warn";
  text: string;
  href?: string;
  summary?: string;
};

function formatDate(value: Date, locale: "en" | "zh") {
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(value);
}

function formatTimestamp(value?: string | null) {
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

function formatLogTime(value: string | null | undefined, locale: "en" | "zh") {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatSignedPointReturn(value: number | undefined) {
  if (value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return `${value >= 0 ? "▲ " : "▼ "}${Math.abs(value).toFixed(2)}%`;
}

function formatPrice(value: number | undefined) {
  if (value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return `$${value.toFixed(2)}`;
}

function performanceRangeLabel(
  range: BriefPerformanceRange,
  locale: "en" | "zh",
) {
  const labels =
    locale === "zh"
      ? { "7d": "近 7 日", "1m": "近一月", "3m": "近三月" }
      : { "7d": "7-day", "1m": "1-month", "3m": "3-month" };
  return labels[range];
}

function safeExternalUrl(value: string | null | undefined) {
  if (!value) {
    return "";
  }
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

function marketSnapshot(symbol: MarketSnapshot["symbol"], data: MarketDataHistoryResponse): MarketSnapshot {
  const rows = data.rows.filter((row) => Number.isFinite(row.close));
  const latest = rows.at(-1);
  const previous = rows.at(-2);
  const changePct =
    latest && previous?.close
      ? (latest.close / previous.close - 1)
      : undefined;
  return {
    symbol,
    last: latest?.close,
    changePct,
    source: data.source,
    asOf: latest?.timestamp,
  };
}

function marketTone(changePct: number | undefined): "neutral" | "up" | "down" {
  if (changePct === undefined) {
    return "neutral";
  }
  return changePct >= 0 ? "up" : "down";
}

function formatMarketChange(changePct: number | undefined) {
  if (changePct === undefined) {
    return "--";
  }
  return `${changePct >= 0 ? "▲ " : "▼ "}${formatPercent(Math.abs(changePct))}`;
}

function buildMarketNote(markets: MarketSnapshot[], text: BriefCopy) {
  const complete = markets.filter((item) => item.changePct !== undefined);
  if (complete.length < 4) {
    return text.quote;
  }
  const strongest = [...complete].sort((a, b) => (b.changePct ?? 0) - (a.changePct ?? 0))[0];
  const weakest = [...complete].sort((a, b) => (a.changePct ?? 0) - (b.changePct ?? 0))[0];
  const positiveCount = complete.filter((item) => (item.changePct ?? 0) >= 0).length;
  const soxx = complete.find((item) => item.symbol === "SOXX");
  const igv = complete.find((item) => item.symbol === "IGV");
  const relativeNote = _semisVsSoftwareNote(soxx, igv, text === copy.zh);
  if (text === copy.zh) {
    return (
      `今日四个观察指数中 ${positiveCount}/4 收涨，` +
      `${strongest.symbol} 最强（${formatMarketChange(strongest.changePct)}），` +
      `${weakest.symbol} 最弱（${formatMarketChange(weakest.changePct)}）` +
      `${relativeNote}。`
    );
  }
  return (
    `${positiveCount}/4 watched ETFs are up today; ` +
    `${strongest.symbol} leads (${formatMarketChange(strongest.changePct)}) while ` +
    `${weakest.symbol} lags (${formatMarketChange(weakest.changePct)})` +
    `${relativeNote}.`
  );
}

function _semisVsSoftwareNote(
  soxx: MarketSnapshot | undefined,
  igv: MarketSnapshot | undefined,
  zh: boolean,
): string {
  if (soxx?.changePct === undefined || igv?.changePct === undefined) {
    return "";
  }
  const diff = soxx.changePct - igv.changePct;
  if (Math.abs(diff) < 0.002) {
    return zh
      ? "；半导体（SOXX）与软件（IGV）涨跌接近"
      : "; semis (SOXX) and software (IGV) moved roughly in line";
  }
  if (diff > 0) {
    return zh
      ? `；半导体（SOXX）相对软件（IGV）偏强 ${formatPercent(Math.abs(diff))}`
      : `; semis (SOXX) outperformed software (IGV) by ${formatPercent(Math.abs(diff))}`;
  }
  return zh
    ? `；软件（IGV）相对半导体（SOXX）偏强 ${formatPercent(Math.abs(diff))}`
    : `; software (IGV) outperformed semis (SOXX) by ${formatPercent(Math.abs(diff))}`;
}

// Asia Radar note builder lives in lib/briefAsiaRadarNote.ts so spread_pct
// (already percentage points) is never double-scaled by formatPercent.

function buildLede({
  text,
  equity,
  paperReturn,
  performanceLabel,
  marketNote,
  asiaRadarNote,
  digestCount,
}: {
  text: BriefCopy;
  equity: string;
  paperReturn: string;
  performanceLabel: string;
  marketNote: string;
  asiaRadarNote: string;
  digestCount: number;
}) {
  if (text === copy.zh) {
    return (
      <>
        今晨，模拟盘权益报 <strong>{equity}</strong>，{performanceLabel}收益{" "}
        <strong>{paperReturn}</strong>；平台市场手记：{marketNote} {asiaRadarNote}{" "}
        另整理 <strong>{formatCount(digestCount)}</strong> 条 AI 业内情报。
      </>
    );
  }
  return (
    <>
      This morning, paper equity prints at <strong>{equity}</strong> with a{" "}
      <strong>{paperReturn}</strong> {performanceLabel} paper return; platform market note: {marketNote}{" "}
      {asiaRadarNote} It has set{" "}
      <strong>{formatCount(digestCount)}</strong> AI intelligence items in type.
    </>
  );
}

function SectionHeader({ title, en }: { title: string; en: string }) {
  return (
    <div className="mb-4 flex flex-col items-start gap-1 sm:flex-row sm:items-baseline sm:gap-3">
      <h2 className="shrink-0 font-editorial-display text-2xl leading-8 text-ink">{title}</h2>
      <span className="font-editorial-caps text-sm text-ink-secondary">{en}</span>
      <span className="mt-2 h-px w-full flex-1 bg-editorial-rule sm:mt-0" />
    </div>
  );
}

function AccountTable({
  positions,
  text,
}: {
  positions: AccountPositionResponse[];
  text: BriefCopy;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[620px] border-collapse text-right font-data-mono text-xs text-ink">
        <thead>
          <tr className="border-b-2 border-ink text-[10px] uppercase text-ink-secondary">
            <th className="py-2 pr-3 text-left">{text.symbol}</th>
            <th className="px-3 py-2">{text.qty}</th>
            <th className="px-3 py-2">{text.avg}</th>
            <th className="px-3 py-2">{text.last}</th>
            <th className="px-3 py-2">{text.marketValue}</th>
            <th className="py-2 pl-3">{text.dayChange}</th>
          </tr>
        </thead>
        <tbody>
          {positions.length ? (
            positions.map((position) => (
              <tr key={position.symbol} className="border-b border-editorial-rule">
                <td className="py-2 pr-3 text-left font-semibold text-ink">
                  {position.symbol}
                </td>
                <td className="px-3 py-2">{formatCount(position.quantity)}</td>
                <td className="px-3 py-2">{formatMoney(position.avg_cost)}</td>
                <td className="px-3 py-2">{formatMoney(position.last_price)}</td>
                <td className="px-3 py-2">{formatMoney(position.market_value)}</td>
                <td className="py-2 pl-3">
                  <BriefDailyChange value={position.day_change_ratio} />
                </td>
              </tr>
            ))
          ) : (
            <tr>
              <td className="py-8 text-center text-ink-secondary" colSpan={6}>
                {text.emptyPositions}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="mt-2 text-right font-data-mono text-[11px] text-ink-secondary">
        {text.accountSource}
      </div>
    </div>
  );
}

function MarketCell({
  title,
  value,
  detail,
  tone = "neutral",
}: {
  title: string;
  value: string;
  detail: string;
  tone?: "neutral" | "up" | "down" | "accent";
}) {
  const toneClass =
    tone === "up"
      ? "text-editorial-up"
      : tone === "down"
        ? "text-editorial-down"
        : tone === "accent"
          ? "text-editorial-accent"
          : "text-ink";
  return (
    <div className="border-t-2 border-ink pt-2">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-lg font-bold leading-7 text-ink [font-family:var(--font-editorial-serif)]">{title}</h3>
        <span className={`font-data-mono text-sm ${toneClass}`}>{value}</span>
      </div>
      <div className="mt-1 font-data-mono text-xs text-ink-secondary">{detail}</div>
    </div>
  );
}

function buildRunAction(run: RecentRun, locale: "en" | "zh"): BriefLogEntry {
  const kindLabel = dashboardRunKindLabel(run, locale);
  const summary = dashboardRunSummary(run);
  const inlineSummary = summary.replaceAll(" | ", " · ");
  // SAMPLE/demo provenance must not be presented as a platform-recorded run.
  const sample = isSampleSource(run.source);
  let text = `${kindLabel} · ${run.run_id}`;
  if (locale === "zh") {
    const prefix = sample ? "SAMPLE · 演示数据 · 非真实回测" : "平台记录回测";
    if (run.kind === "backtest") {
      text = `${prefix} · ${inlineSummary}`;
    } else if (run.kind === "factor") {
      text = sample ? `SAMPLE · 演示因子分析 · ${inlineSummary}` : `平台记录因子分析 · ${inlineSummary}`;
    } else if (run.kind === "replication") {
      text = sample ? `SAMPLE · 演示策略复现 · ${inlineSummary}` : `平台记录策略复现 · ${inlineSummary}`;
    } else {
      text = sample ? `SAMPLE · 演示模拟盘运行 · ${inlineSummary}` : `平台记录模拟盘运行 · ${inlineSummary}`;
    }
  } else if (run.kind === "backtest") {
    text = sample ? `SAMPLE · demo backtest (not real) · ${inlineSummary}` : `Platform recorded backtest · ${inlineSummary}`;
  } else if (run.kind === "factor") {
    text = sample ? `SAMPLE · demo factor analysis · ${inlineSummary}` : `Platform recorded factor analysis · ${inlineSummary}`;
  } else if (run.kind === "replication") {
    text = sample ? `SAMPLE · demo strategy replication · ${inlineSummary}` : `Platform recorded strategy replication · ${inlineSummary}`;
  } else {
    text = sample ? `SAMPLE · demo paper run · ${inlineSummary}` : `Platform recorded paper run · ${inlineSummary}`;
  }
  return {
    timestamp: run.created_at,
    status: sample ? "warn" : "ok",
    text,
    href: dashboardRunHref(run),
    summary: run.run_id,
  };
}

function buildBriefLogEntries({
  runs,
  candidates,
  optionsStatus,
  locale,
}: {
  runs: RecentRun[];
  candidates: {
    candidate_id: string;
    artifact_type?: string | null;
    status?: string | null;
    goal?: string | null;
  }[];
  optionsStatus: OptionsDailyScanStatusResponse;
  locale: "en" | "zh";
}) {
  const entries = runs.slice(0, 5).map((run) => buildRunAction(run, locale));
  const status = optionsStatus.status;
  if (status) {
    const strategies = status.strategies?.length ? status.strategies.join(" / ") : "--";
    entries.push({
      timestamp: status.finished_at ?? status.started_at,
      status: status.status === "completed" ? "ok" : "warn",
      text:
        locale === "zh"
          ? `期权每日扫描${status.status === "completed" ? "完成" : "更新"} · ${strategies}`
          : `Options daily scan ${status.status ?? "updated"} · ${strategies}`,
      summary: status.provider ? `provider=${status.provider}` : undefined,
    });
  }
  for (const candidate of candidates.slice(0, 2)) {
    const artifactType = candidate.artifact_type ?? "unknown";
    entries.push({
      timestamp: null,
      status: candidate.status === "pending" ? "warn" : "ok",
      text:
        locale === "zh"
          ? `研究候选可见 ${artifactType} · ${candidate.candidate_id}`
          : `Research candidate visible ${artifactType} · ${candidate.candidate_id}`,
      summary: candidate.goal ?? `status=${candidate.status ?? "unknown"}`,
    });
  }
  entries.push({
    timestamp: new Date().toISOString(),
    status: "warn",
    text: locale === "zh" ? "晨报已排印 · 当日事实" : "Morning brief printed · same-day facts",
  });
  return entries.slice(0, 8);
}

function RunLog({
  entries,
  locale,
  text,
}: {
  entries: BriefLogEntry[];
  locale: "en" | "zh";
  text: BriefCopy;
}) {
  if (!entries.length) {
    return <p className="font-data-mono text-sm text-ink-secondary">{text.noRuns}</p>;
  }
  return (
    <div className="font-data-mono text-xs text-ink-secondary">
      {entries.map((entry, index) => (
        <div className="flex gap-4 border-b border-dotted border-editorial-rule py-1.5" key={`${entry.text}-${index}`}>
          <span className="w-[72px] shrink-0 text-ink-secondary">{formatLogTime(entry.timestamp, locale)}</span>
          <span className={entry.status === "ok" ? "text-editorial-up" : "text-warning"}>
            {entry.status === "ok" ? "✓" : "△"}
          </span>
          {entry.href ? (
            <Link
              className="min-w-0 flex-1 text-ink transition-colors hover:text-editorial-accent"
              href={localizePath(entry.href, locale)}
            >
              {entry.text}
              <ArrowUpRight className="ml-1 inline h-3 w-3" aria-hidden="true" />
            </Link>
          ) : (
            <span className="min-w-0 flex-1 text-ink">{entry.text}</span>
          )}
          {entry.summary ? <span className="hidden max-w-[360px] truncate lg:inline">{entry.summary}</span> : null}
        </div>
      ))}
    </div>
  );
}

function DigestArticle({
  item,
  index,
  text,
}: {
  item: BriefArchivePayload["ai_news"][number];
  index: number;
  text: BriefCopy;
}) {
  const sourceUrl = safeExternalUrl(item.url);

  return (
    <article className="mb-5 break-inside-avoid">
      <div className="font-data-mono text-[10px] font-bold uppercase tracking-[0.12em] text-editorial-down">
        {item.source} · {item.category ?? "feed"}
      </div>
      <h3 className="mt-1 text-lg font-bold leading-6 text-ink [font-family:var(--font-editorial-serif)]">
        {sourceUrl ? (
          <a
            className="transition-colors hover:text-editorial-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-editorial-accent"
            href={sourceUrl}
            rel="noreferrer noopener"
            target="_blank"
          >
            {item.title}
          </a>
        ) : (
          item.title
        )}
      </h3>
      <div className="mt-1 font-data-mono text-[11px] text-ink-secondary">
        {formatTimestamp(item.published_at)} · {text.score} {item.score ?? "--"}
      </div>
      <p className={index === 0 ? "mt-1 first-letter:float-left first-letter:pr-2 first-letter:font-editorial-display first-letter:text-4xl first-letter:font-bold first-letter:text-editorial-accent" : "mt-1"}>
        {item.summary ?? item.url}
      </p>
    </article>
  );
}

type BriefPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function BriefPage({ searchParams }: BriefPageProps) {
  const query = await searchParams;
  const selectedRange = parseBriefPerformanceRange(query?.range);
  const today = new Date();
  const marketStart = new Date(today.getTime() - 14 * 24 * 60 * 60 * 1000);
  const locale = await getServerLocale();
  const [
    settings,
    symbols,
    factors,
    backtests,
    paperRuns,
    paperAccount,
    paperEquityCurve,
    masterPerformance,
    recentRuns,
    candidates,
    digest,
    marketTopics,
    optionsStatus,
    spyHistory,
    qqqHistory,
    soxxHistory,
    igvHistory,
    asiaRadar,
  ] = await Promise.all([
    getCachedSettings(),
    getSymbols(),
    getFactors(),
    getBacktests(),
    getPaperRuns(),
    getCachedBriefPaperAccount(),
    getCachedBriefPaperAccountEquityCurve(),
    getCachedBriefPaperAccountPerformance(),
    getRecentRuns(8),
    getAgentCandidates(),
    getNewsItems({ take: 6, preference: "auto" }),
    getNewsMarketTopics({ take: 6 }),
    getOptionsDailyScanStatus(),
    getCachedBriefMarketDataHistory("SPY", briefDateKey(marketStart), briefDateKey(today), "1d"),
    getCachedBriefMarketDataHistory("QQQ", briefDateKey(marketStart), briefDateKey(today), "1d"),
    getCachedBriefMarketDataHistory("SOXX", briefDateKey(marketStart), briefDateKey(today), "1d"),
    getCachedBriefMarketDataHistory("IGV", briefDateKey(marketStart), briefDateKey(today), "1d"),
    getCachedAsiaRadarSummary(),
  ]);
  const selectedPerformance = selectBriefPerformanceResponse(
    masterPerformance,
    selectedRange,
  );
  const text = copy[locale];
  const settingsSafety =
    settings.apiError || !settings.safety ? null : settings.safety;
  const settingsStatus = settingsSafety ? "available" : "unavailable";
  const liveTradingStatus =
    settingsSafety === null
      ? text.unavailable
      : settingsSafety.live_trading_enabled
        ? text.on
        : text.off;
  const selectedPaperSeries = selectedPerformance.series.find(
    (series) => series.id === "paper",
  );
  const marketSnapshots = [
    marketSnapshot("SPY", spyHistory),
    marketSnapshot("QQQ", qqqHistory),
    marketSnapshot("SOXX", soxxHistory),
    marketSnapshot("IGV", igvHistory),
  ];
  const marketNote = buildMarketNote(marketSnapshots, text);
  const asiaRadarNote = buildAsiaRadarNote(asiaRadar, locale);
  const logEntries = buildBriefLogEntries({
    runs: recentRuns.runs,
    candidates: candidates.candidates,
    optionsStatus,
    locale,
  });
  const paperPeriodReturn =
    selectedPaperSeries?.points.at(-1)?.return_ratio !== undefined
      ? selectedPaperSeries.points.at(-1)!.return_ratio * 100
      : undefined;
  const rangeLabel = performanceRangeLabel(selectedRange, locale);
  const { items: digestItems } = buildBriefAiNewsDigest(digest);
  const marketTopicItems = mapDigestToBriefAiNews(marketTopics);

  return (
    <div className="flex h-full bg-paper-ink text-ink">
      <BriefArchiveSidebar locale={locale} />
      <div className="h-full min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[var(--spacing-editorial-column)] px-4 pb-12 md:px-8 lg:px-10">
        <ErrorBanner
          locale={locale}
          messages={[
            settings.apiError,
            symbols.apiError,
            factors.apiError,
            backtests.apiError,
            paperRuns.apiError,
            paperAccount.apiError,
            paperEquityCurve.apiError,
            selectedPerformance.apiError,
            masterPerformance.apiError,
            recentRuns.apiError,
            candidates.apiError,
            digest.apiError,
            optionsStatus.apiError,
            spyHistory.apiError,
            qqqHistory.apiError,
            soxxHistory.apiError,
            igvHistory.apiError,
          ]}
        />

        <header className="border-b-[3px] border-double border-ink py-8 text-center">
          <div className="mb-3 font-data-mono text-[11px] uppercase tracking-[0.24em] text-ink-secondary">
            {text.volume} · {text.edition} · {formatDate(today, locale)}
          </div>
          <h1 className="font-editorial-display text-[42px] leading-none text-ink md:text-[54px]">
            {text.title}
          </h1>
          <div className="mt-2 font-editorial-caps text-base text-ink-secondary">{text.subtitle}</div>
          <div className="mt-5 border-t border-editorial-rule pt-3 font-data-mono text-xs text-ink-secondary">
            {text.author} · {text.subscriber}
          </div>
        </header>

        <div className="border-b border-editorial-rule py-2 text-center font-data-mono text-[11px] uppercase tracking-[0.14em] text-ink-secondary">
          {text.safetyLine} · API {settingsStatus}
        </div>

        <section className="border-b border-editorial-rule px-0 py-7 text-center md:px-14">
          <p className="font-editorial-body text-xl leading-9 text-ink">
            {buildLede({
              text,
              equity: paperAccount.apiError ? "--" : formatMoney(paperAccount.equity),
              paperReturn: formatSignedPointReturn(paperPeriodReturn),
              performanceLabel: rangeLabel,
              marketNote,
              asiaRadarNote,
              digestCount: digestItems.length,
            })}
          </p>
          <div className="mt-3 font-data-mono text-xs text-ink-secondary">
            {text.ledeByline} · {paperAccount.price_source?.as_of ?? formatDate(today, locale)}
          </div>
        </section>

        <section className="border-b border-editorial-rule py-7">
          <SectionHeader title={text.account} en={text.accountEn} />
          <div className="grid gap-8 lg:grid-cols-[1.2fr_2fr]">
            <div>
              <div className="font-data-mono text-[11px] uppercase tracking-[0.18em] text-ink-secondary">
                {text.equity}
              </div>
              <div className="mt-1 font-editorial-display text-5xl leading-tight text-ink">
                {paperAccount.apiError ? "--" : formatMoney(paperAccount.equity)}
              </div>
              {paperAccount.apiError ? (
                <div className="font-data-mono text-sm text-warning">{text.accountUnavailable}</div>
              ) : (
                <div className={paperAccount.pnl_abs >= 0 ? "font-data-mono text-sm text-editorial-up" : "font-data-mono text-sm text-editorial-down"}>
                  {paperAccount.pnl_abs >= 0 ? "▲ " : "▼ "}
                  {formatMoney(Math.abs(paperAccount.pnl_abs))} ({formatPercent(paperAccount.pnl_pct)})
                </div>
              )}
              <dl className="mt-4 space-y-1 font-data-mono text-xs text-ink-secondary">
                <div>
                  {text.cash} <span className="text-ink">{paperAccount.apiError ? "--" : formatMoney(paperAccount.cash)}</span>
                </div>
                <div>
                  {text.invested} <span className="text-ink">{paperAccount.apiError ? "--" : formatPercent(paperAccount.invested_pct)}</span>
                </div>
                <div>
                  {text.priceSource} <span className="text-ink">{paperAccount.apiError ? "--" : paperAccount.price_source?.kind ?? "--"}</span>
                </div>
              </dl>
            </div>
            <AccountTable positions={paperAccount.positions} text={text} />
          </div>
        </section>

        <section className="border-b border-editorial-rule py-7">
          <SectionHeader title={text.backtest} en={text.backtestEn} />
          <figure>
            <div className="mb-3 flex flex-col gap-3 font-data-mono text-[11px] text-ink-secondary sm:flex-row sm:items-center sm:justify-between">
              <span>
                {text.figureTitle} · {rangeLabel}
              </span>
              <BriefPerformanceRangeSelector
                locale={locale}
                selectedRange={selectedRange}
              />
            </div>
            <div className="mb-2 flex justify-end font-data-mono text-[11px] text-ink-secondary">
              <span>
                {selectedPerformance.apiError
                  ? text.chartUnavailable
                  : text.chartSource}
              </span>
            </div>
            <PaperEquityFigureState
              unavailableLabel={text.chartUnavailable}
              unavailableReason={selectedPerformance.apiError ?? null}
            >
              <BriefPerformanceChart
                ariaLabel={`${text.figureTitle} · ${rangeLabel}`}
                emptyLabel={text.noChart}
                series={selectedPerformance.series}
              />
              <figcaption className="mt-2 text-center font-editorial-caps text-sm text-ink-secondary">
                {text.latestRun} <strong className="text-ink">{paperAccount.account_id}</strong> ·{" "}
                {text.cumulativeReturn} <strong className="text-ink">{formatSignedPointReturn(paperPeriodReturn)}</strong> ·{" "}
                {text.sharpe} <strong className="text-ink">{formatCount(selectedPaperSeries?.points.length ?? 0)}</strong> ·{" "}
                {selectedPerformance.actual_start ?? "--"} → {selectedPerformance.actual_end ?? "--"} · {text.maxDrawdown}{" "}
                <strong className="text-ink">{formatMoney(paperAccount.equity)}</strong>
              </figcaption>
              <p className="mt-2 text-center font-data-mono text-[11px] text-ink-secondary">{text.chartNote}</p>
            </PaperEquityFigureState>
          </figure>
        </section>

        <section className="border-b border-editorial-rule py-7">
          <SectionHeader title={text.market} en={text.marketEn} />
          <div className="grid gap-5 md:grid-cols-4">
            {marketSnapshots.map((snapshot) => (
              <MarketCell
                detail={`${formatPrice(snapshot.last)} · source=${snapshot.source ?? "--"} · ${snapshot.asOf?.slice(0, 10) ?? "--"}`}
                key={snapshot.symbol}
                title={snapshot.symbol}
                tone={marketTone(snapshot.changePct)}
                value={formatMarketChange(snapshot.changePct)}
              />
            ))}
          </div>
          <div className="mt-6 border-t border-editorial-rule pt-4">
            <div className="mb-2 font-data-mono text-[11px] uppercase tracking-[0.18em] text-ink-secondary">
              {text.topics} · {text.topicsEn}
              {marketTopics.apiError
                ? ""
                : ` · ${marketTopics.provider}/${marketTopics.served_from ?? "primary"}`}
            </div>
            {marketTopics.apiError ? (
              <p className="font-data-mono text-sm text-ink-secondary">{text.topicsUnconfigured}</p>
            ) : marketTopicItems.length ? (
              <ul className="space-y-1.5">
                {marketTopicItems.slice(0, 3).map((item) => {
                  const topicUrl = safeExternalUrl(item.url);
                  return (
                    <li className="font-editorial-body text-sm leading-6 text-ink" key={item.id}>
                      {topicUrl ? (
                        <a
                          className="transition-colors hover:text-editorial-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-editorial-accent"
                          href={topicUrl}
                          rel="noreferrer noopener"
                          target="_blank"
                        >
                          {item.title}
                        </a>
                      ) : (
                        item.title
                      )}
                      <span className="ml-2 font-data-mono text-[11px] text-ink-secondary">
                        {item.source} · {formatTimestamp(item.published_at)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="font-data-mono text-sm text-ink-secondary">{text.noTopics}</p>
            )}
          </div>
        </section>

        <aside className="mx-auto my-7 max-w-3xl border-l-4 border-editorial-accent bg-paper-surface px-6 py-4">
          <p className="font-editorial-body text-base italic leading-7 text-ink">“{marketNote}”</p>
          <div className="mt-2 font-data-mono text-xs text-ink-secondary">-- {text.quoteSig}</div>
        </aside>

        <section className="border-b border-editorial-rule py-7">
          <SectionHeader title={text.digest} en={text.digestEn} />
          {digestItems.length ? (
            <div className="gap-8 text-sm leading-7 text-ink-secondary md:columns-2 md:[column-rule:1px_solid_var(--color-editorial-rule)]">
              {digestItems.map((item, index) => (
                <DigestArticle index={index} item={item} key={item.id} text={text} />
              ))}
            </div>
          ) : (
            <p className="font-data-mono text-sm text-ink-secondary">{text.noDigest}</p>
          )}
        </section>

        <section className="border-b border-editorial-rule py-7">
          <SectionHeader title={text.log} en={text.logEn} />
          <RunLog entries={logEntries} locale={locale} text={text} />
        </section>

        <footer className="py-8 text-center font-data-mono text-[11px] uppercase tracking-[0.14em] text-ink-secondary">
          HERMES MORNING BRIEF
          <br />
          {text.footer}
          <br />
          {text.liveTrading}: {liveTradingStatus} · {text.neverActive}
        </footer>
      </div>
      </div>
    </div>
  );
}
