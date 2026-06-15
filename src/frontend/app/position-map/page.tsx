import Link from "next/link";
import { ArrowRight, BriefcaseBusiness, Layers, ShieldCheck } from "lucide-react";
import { AccountRefreshControl } from "@/components/AccountRefreshControl";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Card, MetricStat, PageHeader, SectionTitle, StatusPill } from "@/components/ui/primitives";
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
    accountValue: "Account Value",
    pnl: "Total P&L",
    cash: "Cash",
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
    accountValue: "账户净值",
    pnl: "总盈亏",
    cash: "现金",
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
  const pnlPositive = account.pnl_abs >= 0;
  const priceSourceLabel = text.priceKinds[account.price_source.kind] ?? account.price_source.kind;

  return (
    <div className="flex h-full flex-1 flex-col gap-4 overflow-y-auto bg-bg-base p-4 lg:p-6">
      <ErrorBanner
        locale={locale}
        messages={[account.apiError, ledger.apiError, backtests.apiError, health.apiError, backtestDetail?.apiError]}
      />

      <PageHeader
        eyebrow={text.eyebrow}
        icon={<Layers size={18} className="text-accent-success" />}
        title={text.title}
        subtitle={text.subtitle}
        actions={
          <>
            <AccountRefreshControl locale={locale} />
            <Link
              className="flex items-center gap-1.5 rounded-lg border border-accent-success/40 bg-accent-success/10 px-3 py-1.5 font-body-sm text-accent-success transition-colors hover:bg-accent-success/20"
              href={localizePath("/paper-trading", locale)}
            >
              <BriefcaseBusiness size={14} />
              {text.openPaperTrading}
            </Link>
          </>
        }
      />

      {accountDown ? (
        <Card tone="danger" padded>
          <p className="font-body-sm text-danger">{text.accountUnavailable}</p>
        </Card>
      ) : null}

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <MetricStat label={text.accountValue} value={accountDown ? "--" : formatMoney(account.equity)} />
        <MetricStat
          label={text.pnl}
          value={accountDown ? "--" : `${pnlPositive ? "+" : ""}${formatMoney(account.pnl_abs)}`}
          delta={accountDown ? undefined : `${(account.pnl_pct * 100).toFixed(2)}%`}
          tone={accountDown ? "neutral" : pnlPositive ? "success" : "danger"}
        />
        <MetricStat label={text.cash} value={accountDown ? "--" : formatMoney(account.cash)} />
        <MetricStat
          label={text.invested}
          value={accountDown ? "--" : `${(account.invested_pct * 100).toFixed(1)}%`}
        />
        <MetricStat
          label={text.unrealized}
          value={accountDown ? "--" : `${account.unrealized_pnl >= 0 ? "+" : ""}${formatMoney(account.unrealized_pnl)}`}
          tone={accountDown ? "neutral" : account.unrealized_pnl >= 0 ? "success" : "danger"}
        />
      </section>

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

          <DataPreviewTable
            columns={[
              "symbol",
              "quantity",
              "avg_cost",
              "last_price",
              "weight",
              "market_value",
              "unrealized_pnl",
              "source",
              "price_kind",
            ]}
            columnLabels={text.columns}
            columnTips={{
              price_kind: text.tips.price_kind,
              source: text.tips.source,
              weight: text.tips.weight,
            }}
            description={text.positionsDesc}
            emptyDescription={text.noPositionRowsDesc}
            emptyTitle={text.positionsTitle}
            locale={locale}
            maxRows={30}
            rows={positionTableRows(positions, text)}
            title={text.positionsTitle}
          />
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
    </div>
  );
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
  text: (typeof copy)["en"] | (typeof copy)["zh"];
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

function positionTableRows(
  rows: AccountPositionView[],
  text: (typeof copy)["en"] | (typeof copy)["zh"],
) {
  return rows.map((row) => {
    let manualShare = 0;
    for (const [source, share] of Object.entries(row.source_breakdown)) {
      if (source === "manual") manualShare += share;
    }
    const source =
      manualShare >= 0.999 ? text.manual : manualShare <= 0.001 ? text.strategy : text.mixed;
    return {
      symbol: row.symbol,
      quantity: Number(row.quantity.toFixed(4)),
      avg_cost: Number(row.avg_cost.toFixed(2)),
      last_price: Number(row.last_price.toFixed(2)),
      weight: `${(Math.max(0, Math.min(1, row.weight)) * 100).toFixed(1)}%`,
      market_value: Number(row.market_value.toFixed(2)),
      unrealized_pnl: Number(row.unrealized_pnl.toFixed(2)),
      source,
      price_kind: text.priceKinds[row.price_kind] ?? row.price_kind,
    };
  });
}

function formatTimestamp(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    return value;
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
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
