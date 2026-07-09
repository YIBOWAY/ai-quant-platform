import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { ErrorBanner } from "@/components/ErrorBanner";
import {
  formatMoney,
  formatPercent,
  getAgentCandidates,
  getAiHotItems,
  getBacktests,
  getFactors,
  getLatestBriefIssue,
  getMarketDataHistory,
  getOptionsDailyScanStatus,
  getPaperAccount,
  getPaperAccountEquityCurve,
  getPaperRuns,
  getRecentRuns,
  getSymbols,
  type AccountPositionResponse,
  type AiHotItem,
  type MarketDataHistoryResponse,
  type OptionsDailyScanStatusResponse,
  type PaperAccountEquityCurveResponse,
  type RecentRun,
} from "@/lib/api";
import {
  dashboardRunHref,
  dashboardRunKindLabel,
  dashboardRunSummary,
  formatCount,
} from "@/lib/dashboardRuns";
import { localizePath } from "@/lib/locale";
import { getCachedHealth } from "@/lib/serverApi";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    stripTitle: "Daily Morning Brief",
    stripPreview: "trial",
    stripSource: "local backend facts",
    volume: "VOL. CXXIII",
    edition: "U.S. research edition",
    title: "Daily Morning Brief",
    subtitle: "HERMES MORNING BRIEF · A QUANTITATIVE LETTER",
    author: "Editor Hermes · arranged by the local agent overnight",
    subscriber: "subscriber one · private use",
    safetyLine: "paper-only journal · dry-run rehearsal · live trading never implied active",
    archiveCta: "Open archived issue",
    ledeByline: "Compiled from platform facts · template lede",
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
    weight: "Weight",
    emptyPositions: "No current positions",
    accountSource: "source: local paper account engine",
    backtest: "Paper Return",
    backtestEn: "ONE-WEEK PAPER RETURN",
    figureTitle: "Figure 1 · paper account one-week return from account ledger",
    chartSource: "source: /api/paper/account/equity-curve account ledger + current quote",
    latestRun: "paper account",
    cumulativeReturn: "one-week return",
    sharpe: "points",
    maxDrawdown: "latest equity",
    chartNote: "Historical points are replayed from the paper-account ledger; the final mark uses the latest paper quote.",
    noChart: "No paper account equity curve has been written yet.",
    market: "Market",
    marketEn: "THE MARKET",
    marketSummary: "Market summary",
    marketUnavailable: "market move unavailable",
    quote:
      "Market data is incomplete; Hermes is holding the daily read to paper evidence until SPY, QQQ, SOXX, and IGV all publish fresh bars.",
    quoteSig: "Hermes note · editor's margin",
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
  },
  zh: {
    stripTitle: "每日晨报",
    stripPreview: "试跑稿",
    stripSource: "数据来自本地后端",
    volume: "VOL. CXXIII",
    edition: "美股研究版",
    title: "每日晨报",
    subtitle: "HERMES MORNING BRIEF · A QUANTITATIVE LETTER",
    author: "主笔 Hermes · 由本地代理彻夜整理",
    subscriber: "订户一人 · 自用",
    safetyLine: "本刊为模拟盘刊物 · DRY-RUN 演练 · live trading never implied active",
    archiveCta: "查看归档版",
    ledeByline: "导语由平台事实模板排印",
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
    weight: "权重",
    emptyPositions: "当前空仓",
    accountSource: "资料来源：本地模拟盘引擎",
    backtest: "模拟盘收益",
    backtestEn: "ONE-WEEK PAPER RETURN",
    figureTitle: "图一 · 模拟盘近 7 日权益曲线",
    chartSource: "来源：/api/paper/account/equity-curve 账户账本 + 当前报价",
    latestRun: "模拟账户",
    cumulativeReturn: "一周收益",
    sharpe: "点数",
    maxDrawdown: "最新权益",
    chartNote: "历史点由模拟账户账本回放，最后一点使用最新纸面报价。",
    noChart: "尚未写入模拟盘权益曲线。",
    market: "市场",
    marketEn: "THE MARKET",
    marketSummary: "市场概括",
    marketUnavailable: "市场涨跌数据不足",
    quoteSig: "Hermes 市场手记",
    quote:
      "市场涨跌数据暂不完整；Hermes 先把每日判断压回纸面证据，等待 SPY、QQQ、SOXX、IGV 四组日线全部刷新。",
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
  },
} as const;

type BriefCopy = (typeof copy)["en"] | (typeof copy)["zh"];
type ChartPoint = { x: string; y: number };
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

function ymd(value: Date) {
  return value.toISOString().slice(0, 10);
}

function normalizePaperEquityCurve(curve: PaperAccountEquityCurveResponse): ChartPoint[] {
  const points = curve.points
    .map((row) => ({
      x: row.timestamp,
      y: row.equity,
    }))
    .filter((row) => {
      const time = new Date(row.x).getTime();
      return Boolean(row.x) && Number.isFinite(row.y) && !Number.isNaN(time);
    })
    .sort((a, b) => new Date(a.x).getTime() - new Date(b.x).getTime())
    .slice(-24);
  if (!points.length) {
    return [];
  }
  const first = points[0]?.y;
  if (!first) {
    return [];
  }
  return points.map((row) => ({ x: row.x, y: (row.y / first - 1) * 100 }));
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
  if (text === copy.zh) {
    return `今日四个观察指数中 ${positiveCount}/4 收涨，${strongest.symbol} 最强（${formatMarketChange(strongest.changePct)}），${weakest.symbol} 最弱（${formatMarketChange(weakest.changePct)}）；Hermes 建议先看半导体与软件的相对强弱，再决定是否扩大风险敞口。`;
  }
  return `${positiveCount}/4 watched ETFs are up today; ${strongest.symbol} leads (${formatMarketChange(strongest.changePct)}) while ${weakest.symbol} lags (${formatMarketChange(weakest.changePct)}). Hermes would read semis versus software before expanding risk.`;
}

function buildLede({
  text,
  equity,
  paperWeekReturn,
  marketNote,
  digestCount,
}: {
  text: BriefCopy;
  equity: string;
  paperWeekReturn: string;
  marketNote: string;
  digestCount: number;
}) {
  if (text === copy.zh) {
    return (
      <>
        今晨，模拟盘权益报 <strong>{equity}</strong>，近 7 日权益收益{" "}
        <strong>{paperWeekReturn}</strong>；Hermes 手记：{marketNote} 另整理{" "}
        <strong>{formatCount(digestCount)}</strong> 条 AI 业内情报。
      </>
    );
  }
  return (
    <>
      This morning, paper equity prints at <strong>{equity}</strong> with a{" "}
      <strong>{paperWeekReturn}</strong> seven-day paper return; Hermes note: {marketNote} It has set{" "}
      <strong>{formatCount(digestCount)}</strong> AI intelligence items in type.
    </>
  );
}

function SectionHeader({ title, en }: { title: string; en: string }) {
  return (
    <div className="mb-4 flex items-baseline gap-3">
      <h2 className="font-editorial-display text-2xl leading-8 text-ink">{title}</h2>
      <span className="font-editorial-caps text-sm text-ink-secondary">{en}</span>
      <span className="h-px flex-1 bg-editorial-rule" />
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
            <th className="py-2 pl-3">{text.weight}</th>
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
                <td className="py-2 pl-3 text-ink-secondary">{formatPercent(position.weight, 3)}</td>
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

function EditorialChart({
  series,
  benchmark,
  text,
}: {
  series: ChartPoint[];
  benchmark: ChartPoint[];
  text: BriefCopy;
}) {
  const all = [...series, ...benchmark];
  if (!all.length) {
    return (
      <div className="flex h-[280px] items-center justify-center border border-editorial-rule bg-paper-surface font-data-mono text-sm text-ink-secondary">
        {text.noChart}
      </div>
    );
  }

  const width = 800;
  const height = 240;
  const padX = 38;
  const padY = 24;
  const yValues = all.map((point) => point.y);
  const minY = Math.min(0, ...yValues);
  const maxY = Math.max(1, ...yValues);
  const spanY = maxY - minY || 1;
  const maxLen = Math.max(series.length, benchmark.length, 2);
  const xFor = (index: number) => padX + (index / (maxLen - 1)) * (width - padX * 2);
  const yFor = (value: number) => height - padY - ((value - minY) / spanY) * (height - padY * 2);
  const pointsFor = (points: ChartPoint[]) =>
    points.map((point, index) => `${xFor(index).toFixed(1)},${yFor(point.y).toFixed(1)}`).join(" ");
  const gridRows = [0, 0.25, 0.5, 0.75, 1].map((ratio) => minY + spanY * ratio);

  return (
    <div className="border border-editorial-rule bg-paper-surface p-3">
      <svg aria-label={text.figureTitle} className="h-[280px] w-full" role="img" viewBox={`0 0 ${width} ${height}`}>
        {gridRows.map((value) => (
          <g key={value.toFixed(4)}>
            <line
              className="stroke-editorial-rule"
              strokeOpacity="0.65"
              x1={padX}
              x2={width - padX}
              y1={yFor(value)}
              y2={yFor(value)}
            />
            <text className="fill-ink-secondary font-data-mono text-[10px]" x={padX - 8} y={yFor(value) + 3} textAnchor="end">
              {value.toFixed(1)}%
            </text>
          </g>
        ))}
        {benchmark.length ? (
          <polyline
            className="fill-none stroke-editorial-down"
            points={pointsFor(benchmark)}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="2"
          />
        ) : null}
        {series.length ? (
          <polyline
            className="fill-none stroke-editorial-accent"
            points={pointsFor(series)}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="2.5"
          />
        ) : null}
        <text className="fill-editorial-accent font-data-mono text-[11px] font-bold" x={width - 92} y={28}>
          paper
        </text>
        {benchmark.length ? (
          <text className="fill-editorial-down font-data-mono text-[11px] font-bold" x={width - 92} y={44}>
            benchmark
          </text>
        ) : null}
      </svg>
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
  let text = `${kindLabel} · ${run.run_id}`;
  if (locale === "zh") {
    if (run.kind === "backtest") {
      text = `Hermes 完成回测 · ${inlineSummary}`;
    } else if (run.kind === "factor") {
      text = `Hermes 完成因子分析 · ${inlineSummary}`;
    } else if (run.kind === "replication") {
      text = `Hermes 添加/复现策略 · ${inlineSummary}`;
    } else {
      text = `Hermes 完成模拟盘运行 · ${inlineSummary}`;
    }
  } else if (run.kind === "backtest") {
    text = `Hermes completed backtest · ${inlineSummary}`;
  } else if (run.kind === "factor") {
    text = `Hermes completed factor analysis · ${inlineSummary}`;
  } else if (run.kind === "replication") {
    text = `Hermes added/replicated strategy · ${inlineSummary}`;
  } else {
    text = `Hermes completed paper run · ${inlineSummary}`;
  }
  return {
    timestamp: run.created_at,
    status: "ok",
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
  candidates: { candidate_id: string; artifact_type: string; status: string; goal?: string }[];
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
    entries.push({
      timestamp: null,
      status: candidate.status === "pending" ? "warn" : "ok",
      text:
        locale === "zh"
          ? `Hermes 产出候选 ${candidate.artifact_type} · ${candidate.candidate_id}`
          : `Hermes produced candidate ${candidate.artifact_type} · ${candidate.candidate_id}`,
      summary: candidate.goal ?? `status=${candidate.status}`,
    });
  }
  entries.push({
    timestamp: new Date().toISOString(),
    status: "warn",
    text: locale === "zh" ? "晨报已排印 · 导语由主笔撰写" : "Morning brief printed · lede prepared by Hermes",
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
  item: AiHotItem;
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

export default async function BriefPage() {
  const today = new Date();
  const marketStart = new Date(today);
  marketStart.setDate(today.getDate() - 14);
  const locale = await getServerLocale();
  const [
    health,
    symbols,
    factors,
    backtests,
    paperRuns,
    paperAccount,
    paperEquityCurve,
    recentRuns,
    candidates,
    digest,
    optionsStatus,
    spyHistory,
    qqqHistory,
    soxxHistory,
    igvHistory,
    archivedEnvelope,
  ] = await Promise.all([
    getCachedHealth(),
    getSymbols(),
    getFactors(),
    getBacktests(),
    getPaperRuns(),
    getPaperAccount(),
    getPaperAccountEquityCurve(7),
    getRecentRuns(8),
    getAgentCandidates(),
    getAiHotItems({ take: 6 }),
    getOptionsDailyScanStatus(),
    getMarketDataHistory("SPY", ymd(marketStart), ymd(today), "1d"),
    getMarketDataHistory("QQQ", ymd(marketStart), ymd(today), "1d"),
    getMarketDataHistory("SOXX", ymd(marketStart), ymd(today), "1d"),
    getMarketDataHistory("IGV", ymd(marketStart), ymd(today), "1d"),
    getLatestBriefIssue({ locale }),
  ]);
  const text = copy[locale];
  const archivedIssuePublicId =
    archivedEnvelope.issue.status !== "unavailable" &&
    archivedEnvelope.issue.public_id.trim().length > 0
      ? archivedEnvelope.issue.public_id
      : null;
  const paperCurve = normalizePaperEquityCurve(paperEquityCurve);
  const marketSnapshots = [
    marketSnapshot("SPY", spyHistory),
    marketSnapshot("QQQ", qqqHistory),
    marketSnapshot("SOXX", soxxHistory),
    marketSnapshot("IGV", igvHistory),
  ];
  const marketNote = buildMarketNote(marketSnapshots, text);
  const logEntries = buildBriefLogEntries({
    runs: recentRuns.runs,
    candidates: candidates.candidates,
    optionsStatus,
    locale,
  });
  const paperWeekReturn = paperCurve.at(-1)?.y;
  const digestItems = digest.items.slice(0, 6);

  return (
    <div className="h-full overflow-y-auto bg-paper-ink text-ink">
      <div className="border-b border-editorial-rule bg-paper-ink px-4 py-1.5 text-center font-data-mono text-[11px] text-ink-secondary">
        <strong className="text-ink">{text.stripTitle}</strong>
        <span className="px-2">·</span>
        <span>{text.stripPreview}</span>
        <span className="px-2">·</span>
        <span>{text.stripSource}</span>
      </div>

      <div className="mx-auto max-w-[var(--spacing-editorial-column)] px-4 pb-12 md:px-8 lg:px-10">
        <ErrorBanner
          locale={locale}
          messages={[
            health.apiError,
            symbols.apiError,
            factors.apiError,
            backtests.apiError,
            paperRuns.apiError,
            paperAccount.apiError,
            paperEquityCurve.apiError,
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
          <div className="mb-3 flex justify-center gap-6 font-data-mono text-[11px] uppercase tracking-[0.24em] text-ink-secondary">
            <span>{text.volume}</span>
            <span>{text.edition}</span>
          </div>
          <h1 className="font-editorial-display text-[42px] leading-none text-ink md:text-[54px]">
            {text.title}
          </h1>
          <div className="mt-2 font-editorial-caps text-base text-ink-secondary">{text.subtitle}</div>
          <div className="mt-5 flex flex-col justify-between gap-2 border-t border-editorial-rule pt-3 font-data-mono text-xs text-ink-secondary md:flex-row">
            <span>{formatDate(today, locale)}</span>
            <span>{text.author}</span>
            <span>{text.subscriber}</span>
          </div>
          {archivedIssuePublicId ? (
            <div className="mt-3">
              <Link
                href={localizePath(`/brief/${archivedIssuePublicId}`, locale)}
                className="text-ink-secondary underline decoration-editorial-rule underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-editorial-accent"
              >
                {text.archiveCta}
              </Link>
            </div>
          ) : null}
        </header>

        <div className="border-b border-editorial-rule py-2 text-center font-data-mono text-[11px] uppercase tracking-[0.14em] text-ink-secondary">
          {text.safetyLine} · API {health.status}
        </div>

        <section className="border-b border-editorial-rule px-0 py-7 text-center md:px-14">
          <p className="font-editorial-body text-xl leading-9 text-ink">
            {buildLede({
              text,
              equity: formatMoney(paperAccount.equity),
              paperWeekReturn: formatSignedPointReturn(paperWeekReturn),
              marketNote,
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
                {formatMoney(paperAccount.equity)}
              </div>
              <div className={paperAccount.pnl_abs >= 0 ? "font-data-mono text-sm text-editorial-up" : "font-data-mono text-sm text-editorial-down"}>
                {paperAccount.pnl_abs >= 0 ? "▲ " : "▼ "}
                {formatMoney(Math.abs(paperAccount.pnl_abs))} ({formatPercent(paperAccount.pnl_pct)})
              </div>
              <dl className="mt-4 space-y-1 font-data-mono text-xs text-ink-secondary">
                <div>
                  {text.cash} <span className="text-ink">{formatMoney(paperAccount.cash)}</span>
                </div>
                <div>
                  {text.invested} <span className="text-ink">{formatPercent(paperAccount.invested_pct)}</span>
                </div>
                <div>
                  {text.priceSource} <span className="text-ink">{paperAccount.price_source?.kind ?? "--"}</span>
                </div>
              </dl>
            </div>
            <AccountTable positions={paperAccount.positions} text={text} />
          </div>
        </section>

        <section className="border-b border-editorial-rule py-7">
          <SectionHeader title={text.backtest} en={text.backtestEn} />
          <figure>
            <div className="mb-2 flex justify-between gap-3 font-data-mono text-[11px] text-ink-secondary">
              <span>{text.figureTitle}</span>
              <span>{text.chartSource}</span>
            </div>
            <EditorialChart series={paperCurve} benchmark={[]} text={text} />
            <figcaption className="mt-2 text-center font-editorial-caps text-sm text-ink-secondary">
              {text.latestRun} <strong className="text-ink">{paperAccount.account_id}</strong> ·{" "}
              {text.cumulativeReturn} <strong className="text-ink">{formatSignedPointReturn(paperWeekReturn)}</strong> ·{" "}
              {text.sharpe} <strong className="text-ink">{formatCount(paperCurve.length)}</strong> · {text.maxDrawdown}{" "}
              <strong className="text-ink">{formatMoney(paperAccount.equity)}</strong>
            </figcaption>
            <p className="mt-2 text-center font-data-mono text-[11px] text-ink-secondary">{text.chartNote}</p>
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
          {text.liveTrading}: {health.safety?.live_trading_enabled ? "on" : "off"} · {text.neverActive}
        </footer>
      </div>
    </div>
  );
}
