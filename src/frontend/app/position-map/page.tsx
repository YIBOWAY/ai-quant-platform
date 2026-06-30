import Link from "next/link";
import type { ReactNode } from "react";
import {
  ArrowRight,
  BriefcaseBusiness,
  Layers,
  ShieldCheck,
} from "lucide-react";
import { AccountRefreshControl } from "@/components/AccountRefreshControl";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Card, SectionTitle, StatusPill } from "@/components/ui/primitives";
import {
  formatMoney,
  getBacktestDetail,
  getBacktests,
  getPaperAccount,
  getPaperAccountLedger,
  type AccountPositionView,
  type LedgerEntryView,
  type PreviewRecord,
} from "@/lib/api";
import { localizePath } from "@/lib/locale";
import { selectDisplayRun, shouldIncludeSampleRuns } from "@/lib/runSource";
import { getCachedHealth } from "@/lib/serverApi";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    eyebrow: "Paper account",
    title: "Position Map",
    subtitle:
      "One persistent simulated account: equity vs the funded base, cash, per-symbol exposure with strategy/manual attribution, and the audit ledger.",
    openPaperTrading: "Trade / Rebalance",
    accountSelector: "default paper account",
    positionsTab: "Positions",
    ordersTab: "Orders",
    orderHistoryTab: "Order History",
    balanceHistoryTab: "Balance History",
    tradeLogTab: "Trade Log",
    tabDisabledHint: "This panel is planned for a later slice.",
    accountBalance: "Account Balance",
    netValue: "Net Value",
    realizedPnl: "Realized P&L",
    accountMargin: "Account Margin",
    availableFunds: "Available Funds",
    orderMargin: "Order Margin",
    marginBuffer: "Margin Buffer",
    accountValue: "Account Value",
    pnl: "Total P&L",
    cash: "Available Cash",
    invested: "Invested",
    unrealized: "Unrealized P&L",
    accountUnavailable: "Account unreachable — values hidden until the backend responds.",
    exposureBySymbol: "Account Exposure by Symbol",
    exposureBySymbolDesc: "Share of invested market value per holding; each bar splits strategy vs manual origin.",
    long: "Long",
    short: "Short",
    manual: "Manual",
    strategy: "Strategy",
    noPositionsTitle: "No open positions",
    noPositionsDesc: "Place a manual order or run a strategy rebalance to build the account.",
    goTrade: "Open Paper Trading",
    priceSource: "Prices",
    priceKinds: {
      futu_snapshot: "Futu live snapshot",
      last_close: "last real close",
    } as Record<string, string>,
    asOf: "as of",
    safetyState: "Safety",
    paperBadge: "Paper-only · no live trading",
    accountFrozen: "frozen",
    positionsTitle: "Account Positions",
    positionsDesc: "Live holdings with average cost, current price, weight and unrealized P&L.",
    noPositionRowsDesc: "No account positions yet.",
    product: "Product",
    buySell: "Buy/Sell",
    quantity: "Qty",
    avgFill: "Avg Fill",
    latestPrice: "Last",
    unrealizedPct: "Unrealized %",
    tradeValue: "Trade Value",
    sourceLabel: "Source",
    ledgerTitle: "Account Activity",
    ledgerDesc: "Latest ledger entries — every order, rebalance and reset is recorded here.",
    ledgerEmptyTitle: "No activity yet",
    ledgerEmptyDesc: "Orders and rebalances will appear here as an audit trail.",
    ledgerMore: "Showing latest",
    kind: {
      fill: "Fill",
      rebalance_fill: "Rebalance fill",
      deposit: "Deposit",
      reset: "Reset",
      fee: "Fee",
      freeze: "Freeze",
      unfreeze: "Unfreeze",
    } as Record<string, string>,
    side: { BUY: "Buy", SELL: "Sell" } as Record<string, string>,
    cashAfter: "cash after",
    comparisonTitle: "Last Backtest Exposure (research comparison)",
    comparisonDesc: "The newest backtest's final positions — a research artifact, not your account.",
    noBacktestDesc: "No backtest positions were found.",
    openBacktest: "Open run",
    columns: {
      symbol: "Symbol",
      quantity: "Qty",
      avg_cost: "Avg Cost",
      last_price: "Last",
      weight: "Weight",
      market_value: "Mkt Value",
      unrealized_pnl: "Unrealized P&L",
      source: "Source",
      price_kind: "Price Src",
    },
    tips: {
      price_kind:
        "futu_snapshot = live Futu quote at fill time; last_close = most recent real daily close (OpenD offline fallback).",
      source: "Which path created this exposure: manual orders, strategy rebalances, or a mix.",
      weight: "Position market value as a share of total invested value.",
    },
    mixed: "Mixed",
  },
  zh: {
    eyebrow: "模拟账户",
    title: "持仓地图",
    subtitle:
      "单一持续模拟账户：净值对比初始本金、现金、按标的的暴露（策略/手动归因），以及完整账本流水。",
    openPaperTrading: "去下单 / 再平衡",
    accountSelector: "默认模拟账户",
    positionsTab: "持仓",
    ordersTab: "订单",
    orderHistoryTab: "订单历史",
    balanceHistoryTab: "余额历史",
    tradeLogTab: "交易日志",
    tabDisabledHint: "该面板将在后续切片接入。",
    accountBalance: "账户余额",
    netValue: "净值",
    realizedPnl: "已实现损益",
    accountMargin: "账户保证金",
    availableFunds: "可用资金",
    orderMargin: "订单保证金",
    marginBuffer: "保证金缓冲",
    accountValue: "账户净值",
    pnl: "总盈亏",
    cash: "可用现金",
    invested: "已投资比例",
    unrealized: "未实现盈亏",
    accountUnavailable: "账户接口不可达——在后端恢复前隐藏数值，避免误读。",
    exposureBySymbol: "按标的的暴露",
    exposureBySymbolDesc: "各持仓占已投资市值的比例；每条按「策略 / 手动」来源分段着色。",
    long: "多头",
    short: "空头",
    manual: "手动",
    strategy: "策略",
    noPositionsTitle: "暂无持仓",
    noPositionsDesc: "手动下单或运行一次策略再平衡，即可建立账户持仓。",
    goTrade: "打开模拟交易",
    priceSource: "报价",
    priceKinds: {
      futu_snapshot: "Futu 实时快照",
      last_close: "最近真实收盘",
    } as Record<string, string>,
    asOf: "截至",
    safetyState: "安全状态",
    paperBadge: "仅模拟 · 不接触实盘",
    accountFrozen: "已冻结",
    positionsTitle: "账户持仓",
    positionsDesc: "实时持仓：均价、现价、权重与未实现盈亏。",
    noPositionRowsDesc: "账户暂无持仓。",
    product: "商品",
    buySell: "买/卖方",
    quantity: "数量",
    avgFill: "平均成交价",
    latestPrice: "最新价",
    unrealizedPct: "未实现损益%",
    tradeValue: "交易值",
    sourceLabel: "来源",
    ledgerTitle: "账户流水",
    ledgerDesc: "最近的账本记录——每一笔下单、再平衡与重置都在这里留痕。",
    ledgerEmptyTitle: "暂无流水",
    ledgerEmptyDesc: "下单与再平衡后，这里会出现完整的审计流水。",
    ledgerMore: "显示最近",
    kind: {
      fill: "成交",
      rebalance_fill: "再平衡成交",
      deposit: "入金",
      reset: "重置",
      fee: "费用",
      freeze: "冻结",
      unfreeze: "解冻",
    } as Record<string, string>,
    side: { BUY: "买入", SELL: "卖出" } as Record<string, string>,
    cashAfter: "余额",
    comparisonTitle: "最近一次回测暴露（研究对比）",
    comparisonDesc: "最新回测的期末持仓——研究产物，不是你的账户。",
    noBacktestDesc: "未找到回测持仓数据行。",
    openBacktest: "打开运行",
    columns: {
      symbol: "标的",
      quantity: "数量",
      avg_cost: "均价",
      last_price: "现价",
      weight: "权重",
      market_value: "市值",
      unrealized_pnl: "未实现盈亏",
      source: "来源",
      price_kind: "价格来源",
    },
    tips: {
      price_kind:
        "futu_snapshot = 成交时的 Futu 实时快照；last_close = 最近一根真实日收盘（OpenD 离线时回退）。",
      source: "该持仓由哪条路径建立：手动下单、策略再平衡，或两者混合。",
      weight: "持仓市值占全部已投资市值的比例。",
    },
    mixed: "混合",
  },
} as const;

type PositionMapPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function PositionMapPage({ searchParams }: PositionMapPageProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  const text = copy[locale];
  const [account, ledger, backtests, health] = await Promise.all([
    getPaperAccount(),
    getPaperAccountLedger(12),
    getBacktests(),
    getCachedHealth(),
  ]);
  const includeSample = shouldIncludeSampleRuns(params);
  const latestBacktest = selectDisplayRun(backtests.backtests, includeSample);
  const backtestDetail = latestBacktest ? await getBacktestDetail(latestBacktest.id) : null;
  const backtestExposure = latestExposure(backtestDetail?.positions ?? []);

  const accountDown = Boolean(account.apiError);
  const positions = [...account.positions].sort(
    (a, b) => Math.abs(b.market_value) - Math.abs(a.market_value),
  );
  const grossInvested = positions.reduce((sum, p) => sum + Math.abs(p.market_value), 0);
  const priceSourceLabel = text.priceKinds[account.price_source.kind] ?? account.price_source.kind;
  const marginBuffer = account.equity > 0 ? account.available_cash / account.equity : 0;

  return (
    <div className="flex h-full flex-1 flex-col overflow-y-auto bg-bg-base text-text-primary">
      <ErrorBanner
        locale={locale}
        messages={[account.apiError, ledger.apiError, backtests.apiError, health.apiError, backtestDetail?.apiError]}
      />

      <header className="border-b border-border-subtle bg-bg-surface px-4 py-4 lg:px-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-text-secondary">
              <Layers size={18} className="text-text-primary" />
              <span className="font-label-caps uppercase">{text.eyebrow}</span>
            </div>
            <h1 className="mt-1 font-headline-xl text-text-primary">{text.title}</h1>
            <p className="mt-2 max-w-3xl font-body-sm text-text-secondary">{text.subtitle}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <AccountRefreshControl locale={locale} />
            <Link
              className="flex items-center gap-1.5 rounded-full border border-border-subtle bg-bg-surface-muted px-3 py-1.5 font-body-sm text-text-primary transition-colors hover:border-text-secondary/50 hover:bg-bg-surface"
              href={localizePath("/paper-trading", locale)}
            >
              <BriefcaseBusiness size={14} />
              {text.openPaperTrading}
            </Link>
          </div>
        </div>

        <div className="mt-6 flex flex-col gap-4 xl:flex-row xl:items-center">
          <div className="inline-flex min-w-[220px] items-center justify-between gap-3 rounded-lg border border-border-subtle bg-bg-base px-3 py-2 text-text-primary">
            <span className="min-w-0 truncate font-body-md">{accountDown ? text.accountSelector : account.account_id}</span>
            <span className="font-data-mono text-xs uppercase text-text-secondary">{account.base_currency}</span>
          </div>
          <div className="grid min-w-0 flex-1 grid-cols-2 gap-x-8 gap-y-3 md:grid-cols-4 2xl:grid-cols-8">
            <TerminalMetric
              label={text.accountBalance}
              value={accountDown ? "--" : formatMoney(account.cash)}
            />
            <TerminalMetric label={text.netValue} value={accountDown ? "--" : formatMoney(account.equity)} />
            <TerminalMetric
              label={text.realizedPnl}
              value={accountDown ? "--" : signedMoney(account.realized_pnl)}
              tone={accountDown ? "neutral" : pnlTone(account.realized_pnl)}
            />
            <TerminalMetric
              label={text.unrealized}
              value={accountDown ? "--" : signedMoney(account.unrealized_pnl)}
              tone={accountDown ? "neutral" : pnlTone(account.unrealized_pnl)}
            />
            <TerminalMetric
              label={text.accountMargin}
              value={accountDown ? "--" : formatMoney(grossInvested)}
            />
            <TerminalMetric
              label={text.availableFunds}
              value={accountDown ? "--" : formatMoney(account.available_cash)}
            />
            <TerminalMetric
              label={text.orderMargin}
              value={accountDown ? "--" : formatMoney(account.reserved_cash)}
            />
            <TerminalMetric
              label={text.marginBuffer}
              value={accountDown ? "--" : `${(marginBuffer * 100).toFixed(2)}%`}
            />
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
          <nav className="flex flex-wrap gap-2" aria-label={text.positionsTitle}>
            <TradingTab active label={`${text.positionsTab} ${positions.length}`} />
            <TradingTab disabledHint={text.tabDisabledHint} label={text.ordersTab} />
            <TradingTab disabledHint={text.tabDisabledHint} label={text.orderHistoryTab} />
            <TradingTab disabledHint={text.tabDisabledHint} label={text.balanceHistoryTab} />
            <TradingTab disabledHint={text.tabDisabledHint} label={text.tradeLogTab} />
          </nav>
          <div className="flex items-center gap-2 text-text-secondary">
            <span className="hidden items-center gap-1.5 font-data-mono text-[10px] uppercase sm:flex">
              {text.priceSource}: {priceSourceLabel}
              {account.price_source.as_of ? ` · ${text.asOf} ${formatTimestamp(account.price_source.as_of)}` : ""}
            </span>
          </div>
        </div>
      </header>

      {accountDown ? (
        <Card tone="danger" padded className="m-4 lg:m-6">
          <p className="font-body-sm text-danger">{text.accountUnavailable}</p>
        </Card>
      ) : null}

      <main className="flex flex-col gap-4 p-4 lg:p-6">
        <PositionsTradingPanel accountDown={accountDown} positions={positions} text={text} />

        <section className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <div className="flex min-w-0 flex-col gap-4">
          <Card padded>
            <SectionTitle
              title={text.exposureBySymbol}
              hint={text.exposureBySymbolDesc}
              right={
                <span className="shrink-0 font-data-mono text-[10px] uppercase text-text-secondary">
                  {text.priceSource}: {priceSourceLabel}
                  {account.price_source.as_of ? ` · ${text.asOf} ${formatTimestamp(account.price_source.as_of)}` : ""}
                </span>
              }
            />
            {positions.length ? (
              <div className="space-y-3">
                <div className="flex items-center gap-4 font-label-caps text-[10px] text-text-secondary">
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-sm bg-accent-success" /> {text.strategy}
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-sm bg-info" /> {text.manual}
                  </span>
                </div>
                {positions.map((row) => (
                  <ExposureBar
                    key={row.symbol}
                    row={row}
                    gross={grossInvested}
                    longLabel={text.long}
                    shortLabel={text.short}
                    manualLabel={text.manual}
                    strategyLabel={text.strategy}
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                title={text.noPositionsTitle}
                description={text.noPositionsDesc}
                action={
                  <Link
                    className="flex items-center gap-1.5 rounded-lg border border-accent-success/40 bg-accent-success/10 px-3 py-1.5 font-body-sm text-accent-success transition-colors hover:bg-accent-success/20"
                    href={localizePath("/paper-trading", locale)}
                  >
                    {text.goTrade}
                    <ArrowRight size={14} />
                  </Link>
                }
              />
            )}
          </Card>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <Card padded>
            <SectionTitle
              title={text.ledgerTitle}
              hint={text.ledgerDesc}
              right={
                ledger.total > ledger.entries.length ? (
                  <span className="font-data-mono text-[10px] uppercase text-text-secondary">
                    {text.ledgerMore} {ledger.entries.length}/{ledger.total}
                  </span>
                ) : null
              }
            />
            {ledger.entries.length ? (
              <ol className="space-y-2">
                {ledger.entries.map((entry) => (
                  <LedgerRow key={entry.entry_id} entry={entry} text={text} />
                ))}
              </ol>
            ) : (
              <EmptyState title={text.ledgerEmptyTitle} description={text.ledgerEmptyDesc} />
            )}
          </Card>

          <Card padded>
            <div className="mb-3 flex items-center gap-2 text-text-secondary">
              <ShieldCheck size={16} className="text-accent-success" />
              <h2 className="font-label-caps text-text-primary">{text.safetyState}</h2>
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusPill
                label="paper_trading"
                value={String(health.safety?.paper_trading ?? true)}
                tone="success"
              />
              <StatusPill
                label="live_trading"
                value={String(health.safety?.live_trading_enabled ?? false)}
                tone={health.safety?.live_trading_enabled ? "danger" : "neutral"}
              />
              <StatusPill
                label={text.accountFrozen}
                value={String(account.kill_switch)}
                tone={account.kill_switch ? "danger" : "neutral"}
              />
            </div>
            <p className="mt-3 font-body-sm text-text-secondary">{text.paperBadge}</p>
          </Card>
        </div>
        </section>

        <section>
        <Card padded>
          <SectionTitle
            title={text.comparisonTitle}
            hint={text.comparisonDesc}
            right={
              <span className="flex items-center gap-2">
                {latestBacktest?.source ? <DataSourceBadge source={latestBacktest.source} /> : null}
                {latestBacktest ? (
                  <Link
                    className="rounded-lg border border-border-subtle px-2 py-1 font-body-sm text-info transition-colors hover:bg-bg-surface-muted"
                    href={localizePath(`/backtest/${latestBacktest.id}`, locale)}
                  >
                    {text.openBacktest}
                  </Link>
                ) : null}
              </span>
            }
          />
          {backtestExposure.length ? (
            <div className="grid gap-x-8 gap-y-2 md:grid-cols-2">
              {backtestExposure.map((row) => (
                <div className="grid grid-cols-[110px_1fr_70px] items-center gap-2" key={row.symbol}>
                  <span className="font-data-mono text-text-primary">{row.symbol}</span>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-bg-surface-muted">
                    <div
                      className={row.side === "Long" ? "h-full bg-accent-success/70" : "h-full bg-danger/70"}
                      style={{ width: `${Math.max(row.weight * 100, 2)}%` }}
                    />
                  </div>
                  <span className="text-right font-data-mono text-text-secondary">
                    {(row.weight * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title={text.comparisonTitle} description={text.noBacktestDesc} />
          )}
        </Card>
        </section>
      </main>
    </div>
  );
}

type PositionCopy = (typeof copy)["en"] | (typeof copy)["zh"];
type Tone = "neutral" | "success" | "danger";

function TerminalMetric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: Tone;
}) {
  const toneStyle =
    tone === "success"
      ? { color: "var(--color-accent-success)" }
      : tone === "danger"
        ? { color: "var(--color-danger)" }
        : undefined;
  return (
    <div className="min-w-0">
      <div className="whitespace-nowrap font-label-caps text-text-secondary">{label}</div>
      <div
        className="mt-1 whitespace-nowrap font-data-mono text-base font-semibold tabular-nums text-text-primary"
        style={toneStyle}
      >
        {value}
      </div>
    </div>
  );
}

function TradingTab({
  label,
  active = false,
  disabledHint,
}: {
  label: string;
  active?: boolean;
  disabledHint?: string;
}) {
  return (
    <span
      aria-current={active ? "page" : undefined}
      aria-disabled={active ? undefined : true}
      className={`inline-flex h-9 items-center rounded-full px-4 font-body-md transition-colors ${
        active
          ? "bg-text-primary text-bg-base"
          : "cursor-not-allowed bg-bg-surface-muted text-text-secondary/55"
      }`}
      title={active ? undefined : disabledHint}
    >
      {label}
    </span>
  );
}

function PositionsTradingPanel({
  accountDown,
  positions,
  text,
}: {
  accountDown: boolean;
  positions: AccountPositionView[];
  text: PositionCopy;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-border-subtle bg-bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle px-4 py-3">
        <div>
          <h2 className="font-label-caps text-text-primary">{text.positionsTitle}</h2>
          <p className="mt-1 font-body-sm text-text-secondary">{text.positionsDesc}</p>
        </div>
        <span className="font-data-mono text-[10px] uppercase text-text-secondary">
          {positions.length} {text.positionsTab}
        </span>
      </div>
      {accountDown ? (
        <p className="py-10 text-center font-body-sm text-text-secondary">{text.accountUnavailable}</p>
      ) : positions.length === 0 ? (
        <EmptyState title={text.noPositionsTitle} description={text.noPositionsDesc} />
      ) : (
        <div className="overflow-x-auto" data-position-table-scroll="true">
          <table className="w-full min-w-[980px] border-collapse text-left">
            <thead>
              <tr className="border-b border-border-subtle bg-bg-surface text-text-secondary">
                {[
                  text.product,
                  text.buySell,
                  text.quantity,
                  text.avgFill,
                  text.latestPrice,
                  text.unrealized,
                  text.unrealizedPct,
                  text.tradeValue,
                  text.sourceLabel,
                ].map((heading, index) => (
                  <th
                    className={`px-4 py-3 font-label-caps ${
                      index >= 2 && index <= 7 ? "text-right" : ""
                    }`}
                    key={heading}
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="font-data-mono text-sm text-text-primary">
              {positions.map((position) => (
                <PositionTradingRow key={position.symbol} position={position} text={text} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function PositionTradingRow({ position, text }: { position: AccountPositionView; text: PositionCopy }) {
  const isLong = position.quantity >= 0;
  const pnl = pnlTone(position.unrealized_pnl);
  const pnlClass =
    pnl === "success" ? "text-accent-success" : pnl === "danger" ? "text-danger" : "text-text-primary";
  const costBasis = Math.abs(position.quantity) * position.avg_cost;
  const pnlPct = costBasis > 0 ? position.unrealized_pnl / costBasis : 0;
  const source = positionSourceLabel(position, text);
  const sourceTone =
    source === text.strategy
      ? "border-accent-success/30 bg-accent-success/10 text-accent-success"
      : source === text.manual
        ? "border-border-subtle bg-bg-surface-muted text-text-secondary"
        : "border-warning/30 bg-warning/10 text-warning";

  return (
    <tr
      className="border-b border-border-subtle/80 transition-colors hover:bg-bg-surface-muted/45"
      data-position-row="true"
    >
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-bg-surface-muted font-data-mono text-[10px] uppercase text-text-secondary">
            {position.symbol.slice(0, 2)}
          </span>
          <span className="rounded-md bg-bg-surface-muted px-2.5 py-1 font-data-mono font-semibold text-text-primary">
            {position.symbol}
          </span>
        </div>
      </td>
      <td className={isLong ? "px-4 py-3 text-info" : "px-4 py-3 text-danger"}>
        {isLong ? text.long : text.short}
      </td>
      <NumericCell>{formatQuantity(position.quantity)}</NumericCell>
      <NumericCell>{formatPrice(position.avg_cost)}</NumericCell>
      <NumericCell>{formatPrice(position.last_price)}</NumericCell>
      <NumericCell className={pnlClass}>{signedMoney(position.unrealized_pnl)}</NumericCell>
      <NumericCell className={pnlClass}>{signedPct(pnlPct)}</NumericCell>
      <NumericCell>{formatMoney(Math.abs(position.market_value))}</NumericCell>
      <td className="px-4 py-3">
        <span className={`inline-flex rounded-full border px-2 py-0.5 font-data-mono text-[10px] uppercase ${sourceTone}`}>
          {source}
        </span>
      </td>
    </tr>
  );
}

function NumericCell({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <td className={`px-4 py-3 text-right tabular-nums ${className}`}>{children}</td>;
}

function ExposureBar({
  row,
  gross,
  longLabel,
  shortLabel,
  manualLabel,
  strategyLabel,
}: {
  row: AccountPositionView;
  gross: number;
  longLabel: string;
  shortLabel: string;
  manualLabel: string;
  strategyLabel: string;
}) {
  const absValue = Math.abs(row.market_value);
  const weight = gross > 0 ? absValue / gross : 0;
  const isLong = row.quantity >= 0;
  let manualShare = 0;
  for (const [source, share] of Object.entries(row.source_breakdown)) {
    if (source === "manual") manualShare += share;
  }
  manualShare = Math.max(0, Math.min(1, manualShare));
  const strategyShare = Math.max(0, 1 - manualShare);
  const widthPct = Math.max(weight * 100, 2);

  return (
    <div className="grid gap-2 md:grid-cols-[130px_1fr_90px]">
      <div>
        <div className="font-data-mono text-text-primary">{row.symbol}</div>
        <div className={`font-label-caps ${isLong ? "text-text-secondary" : "text-danger"}`}>
          {isLong ? longLabel : shortLabel}
        </div>
      </div>
      <div className="flex flex-col justify-center gap-1">
        <div className="flex h-3 w-full overflow-hidden rounded-full bg-bg-surface-muted">
          <div className="flex h-full" style={{ width: `${widthPct}%` }}>
            {strategyShare > 0 ? (
              <div
                className={isLong ? "h-full bg-accent-success" : "h-full bg-danger"}
                style={{ width: `${strategyShare * 100}%` }}
              />
            ) : null}
            {manualShare > 0 ? (
              <div
                className={isLong ? "h-full bg-info" : "h-full bg-danger/60"}
                style={{ width: `${manualShare * 100}%` }}
              />
            ) : null}
          </div>
        </div>
        <div className="font-label-caps text-text-secondary">
          {strategyLabel} {(strategyShare * 100).toFixed(0)}% · {manualLabel} {(manualShare * 100).toFixed(0)}%
        </div>
      </div>
      <div className="text-right font-data-mono tabular-nums text-text-primary">
        {(weight * 100).toFixed(1)}%
      </div>
    </div>
  );
}

function LedgerRow({
  entry,
  text,
}: {
  entry: LedgerEntryView;
  text: PositionCopy;
}) {
  const kindLabel = text.kind[entry.kind] ?? entry.kind;
  const sideLabel = entry.side ? (text.side[entry.side.toUpperCase()] ?? entry.side) : null;
  const isStrategy = entry.source.startsWith("strategy:");
  const sourceLabel = isStrategy ? `${text.strategy} ${entry.source.slice("strategy:".length)}` : text.manual;
  const isSell = entry.side?.toUpperCase() === "SELL";

  return (
    <li className="rounded-lg border border-border-subtle bg-bg-surface-muted/40 px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-label-caps text-text-primary">{kindLabel}</span>
          {entry.source !== "system" ? (
            <span
              className={`rounded-lg border px-1.5 py-0.5 font-data-mono text-[10px] uppercase ${
                isStrategy
                  ? "border-accent-success/40 bg-accent-success/10 text-accent-success"
                  : "border-info/40 bg-info/10 text-info"
              }`}
            >
              {sourceLabel}
            </span>
          ) : null}
        </div>
        <span className="font-data-mono text-[10px] text-text-secondary">
          {formatTimestamp(entry.timestamp)}
        </span>
      </div>
      {entry.symbol ? (
        <div className="mt-1 flex flex-wrap items-center justify-between gap-2 font-data-mono text-xs">
          <span className={isSell ? "text-danger" : "text-accent-success"}>
            {sideLabel ?? ""} {entry.symbol}{" "}
            {entry.quantity != null ? Math.abs(entry.quantity).toLocaleString(undefined, { maximumFractionDigits: 2 }) : ""}
            {entry.price != null ? ` @ ${entry.price.toFixed(2)}` : ""}
          </span>
          {entry.cash_after != null ? (
            <span className="text-text-secondary">
              {text.cashAfter} {formatMoney(entry.cash_after)}
            </span>
          ) : null}
        </div>
      ) : entry.note ? (
        <div className="mt-1 font-body-sm text-text-secondary">{entry.note}</div>
      ) : null}
    </li>
  );
}

function formatTimestamp(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    return value;
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

function positionSourceLabel(row: AccountPositionView, text: PositionCopy) {
  let manualShare = 0;
  for (const [source, share] of Object.entries(row.source_breakdown)) {
    if (source === "manual") manualShare += share;
  }
  if (manualShare >= 0.999) {
    return text.manual;
  }
  if (manualShare <= 0.001) {
    return text.strategy;
  }
  return text.mixed;
}

function pnlTone(value: number): Tone {
  if (!Number.isFinite(value) || value === 0) {
    return "neutral";
  }
  return value > 0 ? "success" : "danger";
}

function signedMoney(value: number) {
  return `${value >= 0 ? "+" : ""}${formatMoney(value)}`;
}

function signedPct(value: number) {
  if (!Number.isFinite(value)) {
    return "--";
  }
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

function formatPrice(value: number) {
  return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 }) : "--";
}

function formatQuantity(value: number) {
  return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "--";
}

type BacktestExposureRow = {
  symbol: string;
  weight: number;
  side: "Long" | "Short";
};

function latestExposure(rows: PreviewRecord[]): BacktestExposureRow[] {
  const latestTimestamp = rows
    .map((row) => stringValue(row.timestamp))
    .filter(Boolean)
    .sort()
    .at(-1);
  if (!latestTimestamp) {
    return [];
  }
  const latestRows = rows.filter((row) => stringValue(row.timestamp) === latestTimestamp);
  const mapped = latestRows
    .map((row) => {
      const symbol = stringValue(row.symbol);
      const quantity = numberValue(row.quantity);
      const price = numberValue(row.close_price);
      const marketValue = numberValue(row.market_value) ?? (quantity ?? 0) * (price ?? 0);
      if (!symbol || !Number.isFinite(marketValue)) {
        return null;
      }
      return {
        symbol,
        absValue: Math.abs(marketValue),
        side: marketValue >= 0 ? "Long" : "Short",
      };
    })
    .filter((row): row is { symbol: string; absValue: number; side: "Long" | "Short" } =>
      row !== null && row.absValue > 0,
    );
  const gross = mapped.reduce((sum, row) => sum + row.absValue, 0);
  return mapped
    .map((row) => ({ symbol: row.symbol, side: row.side, weight: gross > 0 ? row.absValue / gross : 0 }))
    .sort((left, right) => right.weight - left.weight || left.symbol.localeCompare(right.symbol));
}

function numberValue(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value : "";
}
