import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { ErrorBanner } from "@/components/ErrorBanner";
import {
  formatMoney,
  formatPercent,
  getAgentCandidates,
  getAiHotItems,
  getBacktestDetail,
  getBacktests,
  getFactors,
  getPaperAccount,
  getPaperRuns,
  getRecentRuns,
  getSymbols,
  type AccountPositionResponse,
  type PreviewRecord,
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
    stripTitle: "Direction B · Research Daily",
    stripPreview: "trial",
    stripSource: "local backend facts",
    volume: "VOL. CXXIII",
    edition: "U.S. research edition",
    title: "Hermes Morning Brief",
    subtitle: "HERMES MORNING BRIEF · A QUANTITATIVE LETTER",
    author: "Editor Hermes · arranged by the local agent overnight",
    subscriber: "subscriber one · private use",
    safetyLine: "paper-only journal · dry-run rehearsal · live trading never implied active",
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
    backtest: "Backtest Study",
    backtestEn: "A BACKTEST STUDY",
    figureTitle: "Figure 1 · strategy equity curve, normalized from the latest run",
    latestRun: "latest run",
    cumulativeReturn: "cumulative return",
    sharpe: "Sharpe",
    maxDrawdown: "max drawdown",
    noChart: "No equity curve has been written yet.",
    market: "Market",
    marketEn: "THE MARKET",
    symbols: "Symbols",
    factors: "Factors",
    candidates: "Candidates",
    hermesReady: "Hermes",
    ready: "editor ready",
    quote:
      "This brief is a layout-first read of the research desk: treat every number as paper evidence, then open the artifact before trusting the conclusion.",
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
    stripTitle: "Direction B · 研究日报",
    stripPreview: "试跑稿",
    stripSource: "数据来自本地后端",
    volume: "VOL. CXXIII",
    edition: "美股研究版",
    title: "宿契晨报",
    subtitle: "HERMES MORNING BRIEF · A QUANTITATIVE LETTER",
    author: "主笔 Hermes · 由本地代理彻夜整理",
    subscriber: "订户一人 · 自用",
    safetyLine: "本刊为模拟盘刊物 · DRY-RUN 演练 · live trading never implied active",
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
    backtest: "回测研究",
    backtestEn: "A BACKTEST STUDY",
    figureTitle: "图一 · 最新运行策略权益曲线归一化",
    latestRun: "最新运行",
    cumulativeReturn: "累计回报",
    sharpe: "夏普",
    maxDrawdown: "最大回撤",
    noChart: "尚未写入权益曲线。",
    market: "市场",
    marketEn: "THE MARKET",
    symbols: "标的",
    factors: "因子",
    candidates: "候选",
    hermesReady: "Hermes",
    ready: "主笔就绪",
    quote:
      "今晨这份 brief 先看研究证据，不下结论。所有数字都只是 paper evidence；真正要信任它之前，先打开 artifact 看来源、窗口和约束。",
    quoteSig: "Hermes 手记 · 主笔按",
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

function recordNumber(record: PreviewRecord, key: string) {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function recordString(record: PreviewRecord, key: string) {
  const value = record[key];
  return typeof value === "string" ? value : undefined;
}

function normalizeCurve(rows: PreviewRecord[]): ChartPoint[] {
  const parsed = rows
    .map((row) => ({
      x: recordString(row, "timestamp") ?? recordString(row, "date") ?? "",
      equity: recordNumber(row, "equity"),
    }))
    .filter((row): row is { x: string; equity: number } => Boolean(row.x) && row.equity !== undefined);
  const first = parsed[0]?.equity;
  if (!first) {
    return [];
  }
  return parsed.map((row) => ({ x: row.x, y: (row.equity / first - 1) * 100 }));
}

function normalizeBenchmark(rows: Array<{ timestamp: string; equity: number }> | undefined) {
  if (!rows?.length) {
    return [];
  }
  const first = rows[0]?.equity;
  if (!first) {
    return [];
  }
  return rows.map((row) => ({ x: row.timestamp, y: (row.equity / first - 1) * 100 }));
}

function buildLede({
  text,
  equity,
  totalReturn,
  sharpe,
  digestCount,
}: {
  text: BriefCopy;
  equity: string;
  totalReturn: string;
  sharpe: string;
  digestCount: number;
}) {
  if (text === copy.zh) {
    return (
      <>
        今晨，本模拟盘权益报 <strong>{equity}</strong>；最新策略回测录得{" "}
        <strong>{totalReturn}</strong> 累计回报，夏普 <strong>{sharpe}</strong>；Hermes 已为你整理{" "}
        <strong>{formatCount(digestCount)}</strong> 条 AI 业内情报。
      </>
    );
  }
  return (
    <>
      This morning, paper equity prints at <strong>{equity}</strong>; the latest strategy run shows{" "}
      <strong>{totalReturn}</strong> cumulative return with Sharpe <strong>{sharpe}</strong>; Hermes has set{" "}
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
  strategy,
  benchmark,
  text,
}: {
  strategy: ChartPoint[];
  benchmark: ChartPoint[];
  text: BriefCopy;
}) {
  const all = [...strategy, ...benchmark];
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
  const maxLen = Math.max(strategy.length, benchmark.length, 2);
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
        {strategy.length ? (
          <polyline
            className="fill-none stroke-editorial-accent"
            points={pointsFor(strategy)}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="2.5"
          />
        ) : null}
        <text className="fill-editorial-accent font-data-mono text-[11px] font-bold" x={width - 92} y={28}>
          strategy
        </text>
        <text className="fill-editorial-down font-data-mono text-[11px] font-bold" x={width - 92} y={44}>
          benchmark
        </text>
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
  tone?: "neutral" | "up" | "accent";
}) {
  const toneClass = tone === "up" ? "text-editorial-up" : tone === "accent" ? "text-editorial-accent" : "text-ink";
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

function RunLog({
  runs,
  locale,
  text,
}: {
  runs: RecentRun[];
  locale: "en" | "zh";
  text: BriefCopy;
}) {
  if (!runs.length) {
    return <p className="font-data-mono text-sm text-ink-secondary">{text.noRuns}</p>;
  }
  return (
    <div className="font-data-mono text-xs text-ink-secondary">
      {runs.slice(0, 5).map((run) => (
        <div className="flex gap-4 border-b border-dotted border-editorial-rule py-1.5" key={`${run.kind}-${run.run_id}`}>
          <span className="w-[72px] shrink-0 text-ink-secondary">{formatTimestamp(run.created_at)}</span>
          <Link
            className="min-w-0 flex-1 text-ink transition-colors hover:text-editorial-accent"
            href={localizePath(dashboardRunHref(run), locale)}
          >
            {dashboardRunKindLabel(run, locale)} · {run.run_id}
            <ArrowUpRight className="ml-1 inline h-3 w-3" aria-hidden="true" />
          </Link>
          <span className="hidden max-w-[360px] truncate lg:inline">{dashboardRunSummary(run)}</span>
        </div>
      ))}
    </div>
  );
}

export default async function BriefPage() {
  const [
    health,
    symbols,
    factors,
    backtests,
    paperRuns,
    paperAccount,
    recentRuns,
    candidates,
    digest,
    locale,
  ] = await Promise.all([
    getCachedHealth(),
    getSymbols(),
    getFactors(),
    getBacktests(),
    getPaperRuns(),
    getPaperAccount(),
    getRecentRuns(8),
    getAgentCandidates(),
    getAiHotItems({ take: 6 }),
    getServerLocale(),
  ]);
  const text = copy[locale];
  const latestBacktest = selectDisplayRun(backtests.backtests);
  const latestPaper = selectDisplayRun(paperRuns.paper_runs);
  const backtestDetail = latestBacktest ? await getBacktestDetail(latestBacktest.id) : null;
  const strategyCurve = normalizeCurve(backtestDetail?.equity_curve ?? []);
  const benchmarkCurve = normalizeBenchmark(backtestDetail?.benchmark?.equity_curve);
  const today = new Date();
  const totalReturn = formatPercent(latestBacktest?.metrics?.total_return);
  const sharpe = latestBacktest?.metrics?.sharpe?.toFixed(2) ?? "--";
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
            recentRuns.apiError,
            candidates.apiError,
            digest.apiError,
            backtestDetail?.apiError,
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
        </header>

        <div className="border-b border-editorial-rule py-2 text-center font-data-mono text-[11px] uppercase tracking-[0.14em] text-ink-secondary">
          {text.safetyLine} · API {health.status}
        </div>

        <section className="border-b border-editorial-rule px-0 py-7 text-center md:px-14">
          <p className="font-editorial-body text-xl leading-9 text-ink">
            {buildLede({
              text,
              equity: formatMoney(paperAccount.equity),
              totalReturn,
              sharpe,
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
              <span>{latestBacktest?.id ?? "--"}</span>
            </div>
            <EditorialChart strategy={strategyCurve} benchmark={benchmarkCurve} text={text} />
            <figcaption className="mt-2 text-center font-editorial-caps text-sm text-ink-secondary">
              {text.latestRun} <strong className="text-ink">{latestBacktest?.id ?? "--"}</strong> ·{" "}
              {text.cumulativeReturn} <strong className="text-ink">{totalReturn}</strong> · {text.sharpe}{" "}
              <strong className="text-ink">{sharpe}</strong> · {text.maxDrawdown}{" "}
              <strong className="text-ink">{formatPercent(latestBacktest?.metrics?.max_drawdown)}</strong>
            </figcaption>
          </figure>
        </section>

        <section className="border-b border-editorial-rule py-7">
          <SectionHeader title={text.market} en={text.marketEn} />
          <div className="grid gap-5 md:grid-cols-4">
            <MarketCell title={text.symbols} value={symbols.symbols.join(", ") || "--"} detail={`source=${symbols.source}`} />
            <MarketCell title={text.factors} value={formatCount(factors.factors.length)} detail="/api/factors" tone="accent" />
            <MarketCell title={text.candidates} value={formatCount(candidates.candidates.length)} detail="/api/agent/candidates" />
            <MarketCell
              title={text.hermesReady}
              value={text.ready}
              detail={`${formatCount(recentRuns.runs.length)} artifacts · ${latestPaper?.id ?? "--"}`}
              tone="up"
            />
          </div>
        </section>

        <aside className="mx-auto my-7 max-w-3xl border-l-4 border-editorial-accent bg-paper-surface px-6 py-4">
          <p className="font-editorial-body text-base italic leading-7 text-ink">“{text.quote}”</p>
          <div className="mt-2 font-data-mono text-xs text-ink-secondary">-- {text.quoteSig}</div>
        </aside>

        <section className="border-b border-editorial-rule py-7">
          <SectionHeader title={text.digest} en={text.digestEn} />
          {digestItems.length ? (
            <div className="gap-8 text-sm leading-7 text-ink-secondary md:columns-2 md:[column-rule:1px_solid_var(--color-editorial-rule)]">
              {digestItems.map((item, index) => (
                <article className="mb-5 break-inside-avoid" key={item.id}>
                  <div className="font-data-mono text-[10px] font-bold uppercase tracking-[0.12em] text-editorial-down">
                    {item.source} · {item.category ?? "feed"}
                  </div>
                  <h3 className="mt-1 text-lg font-bold leading-6 text-ink [font-family:var(--font-editorial-serif)]">
                    {item.title}
                  </h3>
                  <div className="mt-1 font-data-mono text-[11px] text-ink-secondary">
                    {formatTimestamp(item.published_at)} · {text.score} {item.score ?? "--"}
                  </div>
                  <p className={index === 0 ? "mt-1 first-letter:float-left first-letter:pr-2 first-letter:font-editorial-display first-letter:text-4xl first-letter:font-bold first-letter:text-editorial-accent" : "mt-1"}>
                    {item.summary ?? item.url}
                  </p>
                </article>
              ))}
            </div>
          ) : (
            <p className="font-data-mono text-sm text-ink-secondary">{text.noDigest}</p>
          )}
        </section>

        <section className="border-b border-editorial-rule py-7">
          <SectionHeader title={text.log} en={text.logEn} />
          <RunLog runs={recentRuns.runs} locale={locale} text={text} />
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
