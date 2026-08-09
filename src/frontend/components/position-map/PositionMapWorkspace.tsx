'use client';

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import type {
  AccountPositionView,
  LedgerEntryView,
  PaperAccountBalanceHistoryRowResponse,
  PaperAccountOrderHistoryRowResponse,
  PaperAccountResponse,
  PendingAccountOrderView,
} from "@/lib/api";
import { QuickTradeDrawer, type QuickTradeRequest } from "./QuickTradeDrawer";

type Locale = "en" | "zh";
type AccountTab = "positions" | "orders" | "order-history" | "balance-history" | "trade-log";

const copy = {
  en: {
    positionsTab: "Positions",
    ordersTab: "Orders",
    orderHistoryTab: "Order History",
    balanceHistoryTab: "Balance History",
    tradeLogTab: "Trade Log",
    positionsTitle: "Account Positions",
    positionsHint: "Live holdings: average cost, last price, weight and unrealized P&L. Trade inline.",
    noPositions: "No open positions yet — manual orders or strategy rebalances will appear here.",
    exposureTitle: "Account Exposure by Symbol",
    exposureHint: "Bar length = share of invested market value · segments = strategy / manual origin",
    strategy: "Strategy",
    manual: "Manual",
    mixed: "Mixed",
    long: "Long",
    short: "Short",
    buy: "Buy",
    sell: "Sell",
    restRow: (n: number) => `${n} more`,
    ordersTitle: "Open Orders",
    ordersHint: "Pending paper limit orders reserve cash or quantity until they fill.",
    noOrders: "No open orders — pending limit orders will appear here.",
    placeFirst: "Place a limit order",
    orderHistoryTitle: "Order History",
    orderHistoryHint: (n: number) => `${n} entries · from the account ledger`,
    balanceHistoryTitle: "Balance History",
    balanceHistoryHint: (n: number, total: number) => `${n} / ${total} entries · cash movements`,
    tradeLogTitle: "Trade Log",
    tradeLogHint: (n: number, total: number) => `${n} / ${total} entries · full ledger`,
    comparisonTitle: "Last Backtest Exposure · research comparison, not your account",
    openBacktest: "Open run",
    quickTradeTitle: "Quick Trade",
    quickTradeDesc:
      "Use the row-level Buy/Sell buttons to prefill symbol and side, or start a new order here. Submits straight to the paper account.",
    newOrder: "New paper order",
    safetyTitle: "Safety",
    paperOnly: "Paper-only · no live trading",
    frozen: "kill_switch",
    netInflow: "Net inflow",
    sinceOpen: "since account opened",
    fillCount: "Fills",
    systemEvents: "System events",
    lastActivity: "Last activity",
    filterTitle: "Filter by event",
    filterApplies: "Applies to Balance History and Trade Log.",
    filterAll: "All",
    kind: {
      fill: "Fill",
      rebalance_fill: "Rebalance fill",
      deposit: "Deposit",
      reset: "Reset",
      fee: "Fee",
      freeze: "Freeze",
      unfreeze: "Unfreeze",
      order_cancelled: "Cancelled",
      sleeve_cash_allocated: "Sleeve cash",
      sleeve_execution_fill: "Sleeve fill",
    } as Record<string, string>,
    statusLabels: {
      pending: "Pending",
      filled: "Filled",
      cancelled: "Cancelled",
      event: "Event",
    } as Record<string, string>,
    col: {
      time: "Time",
      status: "Status",
      orderId: "Order ID",
      symbol: "Symbol",
      side: "Side",
      quantity: "Qty",
      avgFill: "Avg Fill",
      limitPrice: "Limit",
      reserved: "Reserved",
      lastCheck: "Last Check",
      event: "Event",
      cashDelta: "Cash Δ",
      cashAfter: "Balance",
      note: "Note",
      avgCost: "Avg Cost",
      lastPrice: "Last",
      unrealized: "Unrealized P&L",
      marketValue: "Mkt Value",
      weight: "Weight",
      source: "Source",
      tradeValue: "Trade Value",
      price: "Price",
    },
    accountUnavailable: "Account unreachable — values hidden until the backend responds.",
  },
  zh: {
    positionsTab: "持仓",
    ordersTab: "订单",
    orderHistoryTab: "订单历史",
    balanceHistoryTab: "余额历史",
    tradeLogTab: "交易日志",
    positionsTitle: "账户持仓",
    positionsHint: "实时持仓：均价、现价、权重与未实现盈亏。行内可直接买卖。",
    noPositions: "暂无持仓 —— 手动下单或策略再平衡后会显示在这里。",
    exposureTitle: "按标的的暴露与归因",
    exposureHint: "条长 = 占已投资市值比例 · 条内分段 = 策略 / 手动来源",
    strategy: "策略",
    manual: "手动",
    mixed: "混合",
    long: "多头",
    short: "空头",
    buy: "买入",
    sell: "卖出",
    restRow: (n: number) => `其余 ${n} 只`,
    ordersTitle: "当前订单",
    ordersHint: "尚未成交的模拟限价单，会冻结现金或数量。",
    noOrders: "暂无当前订单 —— 等待成交的限价单会显示在这里。",
    placeFirst: "下第一笔限价单",
    orderHistoryTitle: "订单历史",
    orderHistoryHint: (n: number) => `${n} 条 · 来自账户账本`,
    balanceHistoryTitle: "余额历史",
    balanceHistoryHint: (n: number, total: number) => `${n} / ${total} 条 · 现金变化重建`,
    tradeLogTitle: "交易日志",
    tradeLogHint: (n: number, total: number) => `${n} / ${total} 条 · 完整账本`,
    comparisonTitle: "最近一次回测暴露 · 研究对比，非账户事实",
    openBacktest: "打开运行",
    quickTradeTitle: "快速交易",
    quickTradeDesc: "从持仓行点「买 / 卖」自动预填标的与方向，或在这里发起一笔新订单。提交直接进模拟账户。",
    newOrder: "新建模拟订单",
    safetyTitle: "安全状态",
    paperOnly: "仅模拟 · 不接触实盘",
    frozen: "kill_switch",
    netInflow: "净流入",
    sinceOpen: "开户以来",
    fillCount: "成交笔数",
    systemEvents: "系统事件",
    lastActivity: "最近活动",
    filterTitle: "按事件筛选",
    filterApplies: "同时作用于余额历史与交易日志。",
    filterAll: "全部",
    kind: {
      fill: "成交",
      rebalance_fill: "再平衡成交",
      deposit: "入金",
      reset: "重置",
      fee: "费用",
      freeze: "冻结",
      unfreeze: "解冻",
      order_cancelled: "已取消",
      sleeve_cash_allocated: "袖珍仓现金",
      sleeve_execution_fill: "袖珍仓成交",
    } as Record<string, string>,
    statusLabels: {
      pending: "等待",
      filled: "已成交",
      cancelled: "已取消",
      event: "事件",
    } as Record<string, string>,
    col: {
      time: "时间",
      status: "状态",
      orderId: "订单号",
      symbol: "标的",
      side: "买/卖",
      quantity: "数量",
      avgFill: "平均成交价",
      limitPrice: "限价",
      reserved: "冻结",
      lastCheck: "最近检查",
      event: "事件",
      cashDelta: "现金变化",
      cashAfter: "余额",
      note: "备注",
      avgCost: "均价",
      lastPrice: "最新价",
      unrealized: "未实现盈亏",
      marketValue: "市值",
      weight: "权重",
      source: "来源",
      tradeValue: "交易值",
      price: "价格",
    },
    accountUnavailable: "账户接口不可达——在后端恢复前隐藏数值，避免误读。",
  },
} as const;

type Text = (typeof copy)["en"] | (typeof copy)["zh"];

export type BacktestExposureRow = { symbol: string; weight: number; side: "Long" | "Short" };

export function PositionMapWorkspace({
  locale,
  initialTab,
  account,
  positions,
  pendingOrders,
  orderHistory,
  balanceHistory,
  tradeLog,
  totals,
  accountDown,
  priceSourceLabel,
  safety,
  backtestExposure,
  backtestHref,
}: {
  locale: Locale;
  initialTab: AccountTab;
  account: PaperAccountResponse;
  positions: AccountPositionView[];
  pendingOrders: PendingAccountOrderView[];
  orderHistory: PaperAccountOrderHistoryRowResponse[];
  balanceHistory: PaperAccountBalanceHistoryRowResponse[];
  tradeLog: LedgerEntryView[];
  totals: { orders: number; orderHistory: number; balanceHistory: number; tradeLog: number };
  accountDown: boolean;
  priceSourceLabel: string;
  safety: { paperTrading: boolean; liveTrading: boolean };
  backtestExposure: BacktestExposureRow[];
  backtestHref: string | null;
}) {
  const text = copy[locale];
  const [tab, setTab] = useState<AccountTab>(initialTab);
  const [kindFilter, setKindFilter] = useState<string>("all");
  const [tradeRequest, setTradeRequest] = useState<QuickTradeRequest | null>(null);

  const grossInvested = useMemo(
    () => positions.reduce((sum, row) => sum + Math.abs(row.market_value), 0),
    [positions],
  );
  const netInflow = useMemo(
    () => balanceHistory.reduce((sum, row) => sum + row.cash_delta, 0),
    [balanceHistory],
  );
  const filteredBalance = useMemo(
    () => balanceHistory.filter((row) => kindFilter === "all" || row.kind === kindFilter),
    [balanceHistory, kindFilter],
  );
  const filteredLog = useMemo(
    () => tradeLog.filter((row) => kindFilter === "all" || row.kind === kindFilter),
    [tradeLog, kindFilter],
  );
  const historyTab = tab === "order-history" || tab === "balance-history" || tab === "trade-log";

  function switchTab(next: AccountTab) {
    setTab(next);
    const url = next === "positions" ? window.location.pathname : `?tab=${next}`;
    window.history.replaceState(null, "", url);
  }

  const tabs: { id: AccountTab; label: string; count: number }[] = [
    { id: "positions", label: text.positionsTab, count: positions.length },
    { id: "orders", label: text.ordersTab, count: totals.orders },
    { id: "order-history", label: text.orderHistoryTab, count: totals.orderHistory },
    { id: "balance-history", label: text.balanceHistoryTab, count: totals.balanceHistory },
    { id: "trade-log", label: text.tradeLogTab, count: totals.tradeLog },
  ];

  return (
    <div className="px-4 pb-10 lg:px-8">
      {/* ---------- 下划线 tabs：客户端瞬时切换 ---------- */}
      <nav aria-label={text.positionsTitle} className="flex flex-wrap gap-x-7 border-b border-border-subtle" role="tablist">
        {tabs.map((item) => {
          const active = item.id === tab;
          return (
            <button
              aria-selected={active}
              className={`relative flex items-baseline gap-2 px-0.5 pb-3 pt-3 font-body-sm transition-colors ${
                active ? "text-text-primary" : "text-text-secondary hover:text-text-primary"
              }`}
              key={item.id}
              onClick={() => switchTab(item.id)}
              role="tab"
              type="button"
            >
              <span className="font-medium">{item.label}</span>
              <span className={`font-data-mono text-[11px] ${active ? "text-text-primary" : "text-text-secondary/70"}`}>
                {item.count}
              </span>
              {active ? (
                <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-text-primary" />
              ) : null}
            </button>
          );
        })}
      </nav>

      <div className="mt-6 grid items-start gap-7 xl:grid-cols-[minmax(0,1fr)_350px]">
        {/* ---------- 主区 ---------- */}
        <div className="flex min-w-0 flex-col gap-7" role="tabpanel">
          {tab === "positions" ? (
            <>
              <PositionsBlock
                accountDown={accountDown}
                grossInvested={grossInvested}
                onTrade={(symbol, side) => setTradeRequest({ symbol, side })}
                positions={positions}
                priceSourceLabel={priceSourceLabel}
                text={text}
              />
              <ExposureBlock grossInvested={grossInvested} positions={positions} text={text} />
              {backtestExposure.length ? (
                <details className="group border-t border-border-subtle pt-4">
                  <summary className="flex cursor-pointer list-none items-center gap-1.5 font-label-caps text-text-secondary transition-colors hover:text-text-primary [&::-webkit-details-marker]:hidden">
                    <span className="text-[9px] transition-transform group-open:rotate-90">▸</span>
                    {text.comparisonTitle}
                  </summary>
                  <div className="mt-4 grid gap-x-8 gap-y-2 md:grid-cols-2">
                    {backtestExposure.map((row) => (
                      <div className="grid grid-cols-[90px_1fr_64px] items-center gap-2" key={row.symbol}>
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
                  {backtestHref ? (
                    <a className="mt-3 inline-block font-body-sm text-info underline-offset-2 hover:underline" href={backtestHref}>
                      {text.openBacktest} →
                    </a>
                  ) : null}
                </details>
              ) : null}
            </>
          ) : null}

          {tab === "orders" ? (
            <OrdersBlock
              accountDown={accountDown}
              onPlace={() => setTradeRequest({})}
              orders={pendingOrders}
              text={text}
            />
          ) : null}

          {tab === "order-history" ? (
            <OrderHistoryBlock accountDown={accountDown} rows={orderHistory} text={text} />
          ) : null}

          {tab === "balance-history" ? (
            <BalanceHistoryBlock
              accountDown={accountDown}
              rows={filteredBalance}
              text={text}
              total={totals.balanceHistory}
            />
          ) : null}

          {tab === "trade-log" ? (
            <TradeLogBlock accountDown={accountDown} rows={filteredLog} text={text} total={totals.tradeLog} />
          ) : null}
        </div>

        {/* ---------- 情境化右栏 ---------- */}
        <aside className="flex flex-col gap-5 xl:sticky xl:top-4">
          {historyTab ? (
            <>
              <div className="rounded-xl border border-border-subtle bg-bg-surface p-5">
                <h3 className="font-label-caps text-text-primary">{text.netInflow}</h3>
                <div
                  className={`mt-1 font-data-mono text-2xl font-semibold tabular-nums ${
                    netInflow > 0 ? "text-accent-success" : netInflow < 0 ? "text-danger" : "text-text-primary"
                  }`}
                >
                  {signedMoney(netInflow)}
                </div>
                <p className="mb-3 mt-0.5 font-data-mono text-[11px] text-text-secondary">{text.sinceOpen}</p>
                <div className="flex flex-col gap-2 border-t border-border-subtle/60 pt-3 font-data-mono text-[12px] text-text-secondary">
                  <div className="flex justify-between">
                    <span>{text.fillCount}</span>
                    <span className="text-text-primary">{orderHistory.length}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>{text.systemEvents}</span>
                    <span className="text-text-primary">
                      {balanceHistory.filter((row) => row.source === "system").length}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>{text.lastActivity}</span>
                    <span className="text-text-primary">
                      {tradeLog[0] ? formatTimestamp(tradeLog[0].timestamp) : "--"}
                    </span>
                  </div>
                </div>
              </div>
              <div className="rounded-xl border border-border-subtle bg-bg-surface p-5">
                <h3 className="mb-3 font-label-caps text-text-primary">{text.filterTitle}</h3>
                <div className="flex flex-wrap gap-1.5">
                  {["all", "fill", "deposit", "freeze", "unfreeze", "reset"].map((kind) => (
                    <button
                      className={`rounded-md px-2.5 py-1 font-body-sm transition-colors ${
                        kindFilter === kind
                          ? "border border-info/40 bg-info/15 text-info"
                          : "border border-transparent bg-bg-surface-muted text-text-secondary hover:text-text-primary"
                      }`}
                      key={kind}
                      onClick={() => setKindFilter(kind)}
                      type="button"
                    >
                      {kind === "all" ? text.filterAll : (text.kind[kind] ?? kind)}
                    </button>
                  ))}
                </div>
                <p className="mt-3 font-body-sm text-text-secondary">{text.filterApplies}</p>
              </div>
            </>
          ) : (
            <>
              <div className="rounded-xl border border-border-subtle bg-bg-surface p-5">
                <h3 className="font-label-caps text-text-primary">⚡ {text.quickTradeTitle}</h3>
                <p className="mb-4 mt-1.5 font-body-sm leading-relaxed text-text-secondary">{text.quickTradeDesc}</p>
                <button
                  className="group flex w-full items-center justify-between rounded-lg border border-accent-success/35 bg-accent-success/10 px-3.5 py-2.5 font-body-sm font-semibold text-[#0FB78F] transition-colors hover:border-accent-success/55 hover:bg-accent-success/15"
                  onClick={() => setTradeRequest({})}
                  type="button"
                >
                  <span>{text.newOrder}</span>
                  <span className="transition-transform group-hover:translate-x-1">→</span>
                </button>
              </div>
              <div className="rounded-xl border border-border-subtle bg-bg-surface p-5">
                <h3 className="mb-2 font-label-caps text-text-primary">{text.safetyTitle}</h3>
                <SafetyRow label="paper_trading" tone="up" value={String(safety.paperTrading)} />
                <SafetyRow label="live_trading" tone={safety.liveTrading ? "danger" : "neutral"} value={String(safety.liveTrading)} />
                <SafetyRow label={text.frozen} tone={account.kill_switch ? "danger" : "neutral"} value={account.kill_switch ? "true" : "false"} />
                <p className="mt-3 font-body-sm text-text-secondary">{text.paperOnly}</p>
              </div>
            </>
          )}
        </aside>
      </div>

      <QuickTradeDrawer
        locale={locale}
        onClose={() => setTradeRequest(null)}
        positions={positions}
        request={tradeRequest}
      />
    </div>
  );
}

/* ================= 区块 ================= */

function BlockTitle({ hint, title }: { hint?: string; title: string }) {
  return (
    <div className="mb-3.5 flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="flex items-center gap-2 font-label-caps text-text-primary">
        <span className="inline-block h-3 w-[3px] rounded-sm bg-accent-success" />
        {title}
      </h2>
      {hint ? <span className="font-body-sm text-text-secondary">{hint}</span> : null}
    </div>
  );
}

function PositionsBlock({
  accountDown,
  grossInvested,
  onTrade,
  positions,
  priceSourceLabel,
  text,
}: {
  accountDown: boolean;
  grossInvested: number;
  onTrade: (symbol: string, side: "buy" | "sell") => void;
  positions: AccountPositionView[];
  priceSourceLabel: string;
  text: Text;
}) {
  return (
    <section>
      <BlockTitle hint={priceSourceLabel} title={text.positionsTitle} />
      {accountDown ? (
        <p className="py-8 text-center font-body-sm text-text-secondary">{text.accountUnavailable}</p>
      ) : positions.length === 0 ? (
        <EmptyBox>{text.noPositions}</EmptyBox>
      ) : (
        <div className="overflow-x-auto" data-position-table-scroll="true">
          <table className="w-full min-w-[960px] border-collapse text-left">
            <thead>
              <tr className="border-b border-border-subtle">
                {[text.col.symbol, text.col.quantity, text.col.avgCost, text.col.lastPrice, text.col.unrealized, text.col.marketValue, text.col.weight, text.col.source, ""].map(
                  (heading, index) => (
                    <Th className={index >= 1 && index <= 6 ? "text-right" : ""} key={heading || "actions"}>
                      {heading}
                    </Th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="font-data-mono text-sm text-text-primary">
              {positions.map((position) => (
                <PositionRow
                  key={position.symbol}
                  onTrade={onTrade}
                  position={position}
                  text={text}
                  weight={grossInvested > 0 ? Math.abs(position.market_value) / grossInvested : 0}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function PositionRow({
  onTrade,
  position,
  text,
  weight,
}: {
  onTrade: (symbol: string, side: "buy" | "sell") => void;
  position: AccountPositionView;
  text: Text;
  weight: number;
}) {
  const isLong = position.quantity >= 0;
  const costBasis = Math.abs(position.quantity) * position.avg_cost;
  const pnlPct = costBasis > 0 ? position.unrealized_pnl / costBasis : 0;
  return (
    <tr className="group border-b border-border-subtle/50 transition-colors last:border-b-0 hover:bg-bg-surface-muted/45" data-position-row="true">
      <Td>
        <div className="flex items-center gap-2.5">
          <span className="h-[22px] w-1 flex-none rounded-sm bg-text-primary/25" />
          <div>
            <div className="font-semibold">{position.symbol}</div>
            <div className="font-body-sm text-[11px] text-text-secondary">
              {isLong ? text.long : text.short} · {sourceLabel(position, text)}
            </div>
          </div>
        </div>
      </Td>
      <Td className="text-right">{formatQuantity(position.quantity)}</Td>
      <Td className="text-right">{formatPrice(position.avg_cost)}</Td>
      <Td className="text-right">{formatPrice(position.last_price)}</Td>
      <Td className={`text-right ${toneClass(position.unrealized_pnl)}`}>
        <span className="block">{signedMoney(position.unrealized_pnl)}</span>
        <span className="block text-[11px] opacity-65">{signedPct(pnlPct)}</span>
      </Td>
      <Td className="text-right">{formatMoney(Math.abs(position.market_value))}</Td>
      <Td className="text-right">
        <div className="flex items-center justify-end gap-2">
          <div className="h-1.5 w-[74px] flex-none overflow-hidden rounded-full bg-bg-surface-muted">
            <div className="h-full rounded-full bg-info" style={{ width: `${Math.max(weight * 100, 2)}%` }} />
          </div>
          <span className="min-w-[40px] text-right text-[11px]">{(weight * 100).toFixed(1)}%</span>
        </div>
      </Td>
      <Td>
        <span className="inline-flex items-center gap-1.5 font-body-sm text-[11px] text-text-secondary">
          <span className="h-1.5 w-1.5 rounded-full bg-info" />
          {sourceLabel(position, text)}
        </span>
      </Td>
      <Td className="text-right">
        <span className="opacity-0 transition-opacity group-hover:opacity-100">
          <button
            className="mr-1.5 rounded-md border border-info/45 bg-info/10 px-2.5 py-1 font-body-sm text-[11px] text-info transition-colors hover:bg-info/20"
            onClick={() => onTrade(position.symbol, "buy")}
            type="button"
          >
            {text.buy}
          </button>
          <button
            className="rounded-md border border-danger/45 bg-danger/10 px-2.5 py-1 font-body-sm text-[11px] text-danger transition-colors hover:bg-danger/20"
            onClick={() => onTrade(position.symbol, "sell")}
            type="button"
          >
            {text.sell}
          </button>
        </span>
      </Td>
    </tr>
  );
}

function ExposureBlock({
  grossInvested,
  positions,
  text,
}: {
  grossInvested: number;
  positions: AccountPositionView[];
  text: Text;
}) {
  const TOP = 8;
  const rows = useMemo(() => {
    const sorted = [...positions].sort((a, b) => Math.abs(b.market_value) - Math.abs(a.market_value));
    const rest = sorted.slice(TOP);
    if (!rest.length) return sorted.map((row) => ({ ...row, isRest: false }));
    const restMv = rest.reduce((sum, row) => sum + Math.abs(row.market_value), 0);
    const restManual =
      rest.reduce((sum, row) => sum + manualShare(row) * Math.abs(row.market_value), 0) / (restMv || 1);
    return [
      ...sorted.slice(0, TOP).map((row) => ({ ...row, isRest: false })),
      {
        ...rest[0],
        symbol: text.restRow(rest.length),
        market_value: restMv,
        isRest: true,
        source_breakdown: { manual: restManual },
      },
    ];
  }, [positions, text]);

  if (!rows.length || grossInvested <= 0) return null;
  return (
    <section>
      <BlockTitle hint={text.exposureHint} title={text.exposureTitle} />
      <div className="mb-4 flex gap-4 font-label-caps text-[10px] text-text-secondary">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm bg-accent-success" /> {text.strategy}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm bg-info" /> {text.manual}
        </span>
      </div>
      <div className="flex flex-col gap-3.5">
        {rows.map((row) => {
          const weight = Math.abs(row.market_value) / grossInvested;
          const manualW = weight * manualShare(row);
          const stratW = weight - manualW;
          return (
            <div className="grid grid-cols-[96px_1fr_90px_56px] items-center gap-3.5" key={row.symbol}>
              <span
                className={
                  row.isRest
                    ? "font-body-sm text-[11.5px] text-text-secondary"
                    : "font-data-mono text-[12.5px] font-semibold text-text-primary"
                }
              >
                {row.symbol}
              </span>
              <div className="flex h-2.5 overflow-hidden rounded-full bg-bg-surface-muted">
                {stratW > 0.0005 ? (
                  <div className="h-full bg-accent-success" style={{ width: `${stratW * 100}%` }} />
                ) : null}
                {manualW > 0.0005 ? (
                  <div className="h-full bg-info" style={{ width: `${manualW * 100}%` }} />
                ) : null}
              </div>
              <span className="text-right font-data-mono text-[11.5px] text-text-secondary">
                {formatMoney(Math.abs(row.market_value))}
              </span>
              <span className="text-right font-data-mono text-xs text-text-primary">
                {(weight * 100).toFixed(1)}%
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function OrdersBlock({
  accountDown,
  onPlace,
  orders,
  text,
}: {
  accountDown: boolean;
  onPlace: () => void;
  orders: PendingAccountOrderView[];
  text: Text;
}) {
  return (
    <section>
      <BlockTitle hint={text.ordersHint} title={text.ordersTitle} />
      {accountDown ? (
        <p className="py-8 text-center font-body-sm text-text-secondary">{text.accountUnavailable}</p>
      ) : orders.length === 0 ? (
        <EmptyBox>
          <span>{text.noOrders}</span>
          <button
            className="rounded-md border border-border-subtle bg-bg-surface-muted px-3 py-1.5 font-body-sm text-text-primary transition-colors hover:border-info/50"
            onClick={onPlace}
            type="button"
          >
            {text.placeFirst}
          </button>
        </EmptyBox>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] border-collapse text-left">
            <thead>
              <tr className="border-b border-border-subtle">
                {[text.col.time, text.col.orderId, text.col.symbol, text.col.side, text.col.quantity, text.col.limitPrice, text.col.reserved, text.col.lastCheck].map(
                  (heading, index) => (
                    <Th className={index >= 4 && index <= 6 ? "text-right" : ""} key={heading}>
                      {heading}
                    </Th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="font-data-mono text-sm text-text-primary">
              {orders.map((order) => (
                <tr className="border-b border-border-subtle/50 transition-colors last:border-b-0 hover:bg-bg-surface-muted/45" key={order.order_id}>
                  <Td className="text-text-secondary">{formatTimestamp(order.created_at)}</Td>
                  <Td className="text-text-secondary">{shortId(order.order_id)}</Td>
                  <Td className="font-semibold">{order.symbol}</Td>
                  <Td className={order.side.toLowerCase() === "buy" ? "text-info" : "text-danger"}>
                    {order.side.toLowerCase() === "buy" ? text.buy : text.sell}
                  </Td>
                  <Td className="text-right">{formatQuantity(order.quantity)}</Td>
                  <Td className="text-right">{formatPrice(order.limit_price)}</Td>
                  <Td className="text-right">{formatReserved(order)}</Td>
                  <Td className="text-text-secondary">
                    {order.last_checked_at ? formatTimestamp(order.last_checked_at) : "--"}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function OrderHistoryBlock({
  accountDown,
  rows,
  text,
}: {
  accountDown: boolean;
  rows: PaperAccountOrderHistoryRowResponse[];
  text: Text;
}) {
  return (
    <section>
      <BlockTitle hint={text.orderHistoryHint(rows.length)} title={text.orderHistoryTitle} />
      {accountDown ? (
        <p className="py-8 text-center font-body-sm text-text-secondary">{text.accountUnavailable}</p>
      ) : rows.length === 0 ? (
        <EmptyBox>{text.orderHistoryHint(0)}</EmptyBox>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] border-collapse text-left">
            <thead>
              <tr className="border-b border-border-subtle">
                {[text.col.time, text.col.status, text.col.symbol, text.col.side, text.col.quantity, text.col.avgFill, text.col.tradeValue, text.col.source].map(
                  (heading, index) => (
                    <Th className={index >= 4 && index <= 6 ? "text-right" : ""} key={heading}>
                      {heading}
                    </Th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="font-data-mono text-sm text-text-primary">
              {rows.map((row) => (
                <tr className="border-b border-border-subtle/50 transition-colors last:border-b-0 hover:bg-bg-surface-muted/45" key={row.event_id}>
                  <Td className="text-text-secondary">{formatTimestamp(row.timestamp)}</Td>
                  <Td>
                    <StatusDot status={row.status} text={text.statusLabels[row.status] ?? row.status} />
                  </Td>
                  <Td className="font-semibold">{row.symbol ?? "--"}</Td>
                  <Td className={row.side?.toLowerCase() === "buy" ? "text-info" : "text-danger"}>
                    {row.side ? (row.side.toLowerCase() === "buy" ? text.buy : text.sell) : "--"}
                  </Td>
                  <Td className="text-right">{formatMaybeQuantity(row.quantity)}</Td>
                  <Td className="text-right">{formatMaybePrice(row.price)}</Td>
                  <Td className="text-right">{formatMaybeMoney(row.gross_value)}</Td>
                  <Td>
                    <span className="inline-flex items-center gap-1.5 font-body-sm text-[11px] text-text-secondary">
                      <span className="h-1.5 w-1.5 rounded-full bg-info" />
                      {row.source === "manual" ? text.manual : text.strategy}
                    </span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function BalanceHistoryBlock({
  accountDown,
  rows,
  text,
  total,
}: {
  accountDown: boolean;
  rows: PaperAccountBalanceHistoryRowResponse[];
  text: Text;
  total: number;
}) {
  return (
    <section>
      <BlockTitle hint={text.balanceHistoryHint(rows.length, total)} title={text.balanceHistoryTitle} />
      {accountDown ? (
        <p className="py-8 text-center font-body-sm text-text-secondary">{text.accountUnavailable}</p>
      ) : rows.length === 0 ? (
        <EmptyBox>{text.balanceHistoryHint(0, total)}</EmptyBox>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] border-collapse text-left">
            <thead>
              <tr className="border-b border-border-subtle">
                {[text.col.time, text.col.event, text.col.cashDelta, text.col.cashAfter, text.col.note].map(
                  (heading, index) => (
                    <Th className={index === 2 || index === 3 ? "text-right" : ""} key={heading}>
                      {heading}
                    </Th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="font-data-mono text-sm text-text-primary">
              {rows.map((row) => (
                <tr className="border-b border-border-subtle/50 transition-colors last:border-b-0 hover:bg-bg-surface-muted/45" key={row.event_id}>
                  <Td className="text-text-secondary">{formatTimestamp(row.timestamp)}</Td>
                  <Td>{text.kind[row.kind] ?? row.kind}</Td>
                  <Td className={`text-right ${row.cash_delta ? toneClass(row.cash_delta) : "text-text-secondary"}`}>
                    {row.cash_delta ? signedMoney(row.cash_delta) : "—"}
                  </Td>
                  <Td className="text-right">{formatMoney(row.cash_after)}</Td>
                  <Td className="max-w-[280px] truncate text-text-secondary">{row.note || "--"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function TradeLogBlock({
  accountDown,
  rows,
  text,
  total,
}: {
  accountDown: boolean;
  rows: LedgerEntryView[];
  text: Text;
  total: number;
}) {
  return (
    <section>
      <BlockTitle hint={text.tradeLogHint(rows.length, total)} title={text.tradeLogTitle} />
      {accountDown ? (
        <p className="py-8 text-center font-body-sm text-text-secondary">{text.accountUnavailable}</p>
      ) : rows.length === 0 ? (
        <EmptyBox>{text.tradeLogHint(0, total)}</EmptyBox>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] border-collapse text-left">
            <thead>
              <tr className="border-b border-border-subtle">
                {[text.col.time, text.col.event, text.col.symbol, text.col.side, text.col.quantity, text.col.price, text.col.cashAfter].map(
                  (heading, index) => (
                    <Th className={index >= 4 && index <= 6 ? "text-right" : ""} key={heading}>
                      {heading}
                    </Th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="font-data-mono text-sm text-text-primary">
              {rows.map((row) => (
                <tr className="border-b border-border-subtle/50 transition-colors last:border-b-0 hover:bg-bg-surface-muted/45" key={row.entry_id}>
                  <Td className="text-text-secondary">{formatTimestamp(row.timestamp)}</Td>
                  <Td>{text.kind[row.kind] ?? row.kind}</Td>
                  <Td className="font-semibold">{row.symbol ?? "—"}</Td>
                  <Td
                    className={
                      row.side?.toLowerCase() === "buy"
                        ? "text-info"
                        : row.side?.toLowerCase() === "sell"
                          ? "text-danger"
                          : "text-text-secondary"
                    }
                  >
                    {row.side ? (row.side.toLowerCase() === "buy" ? text.buy : text.sell) : "—"}
                  </Td>
                  <Td className="text-right">{formatMaybeQuantity(row.quantity)}</Td>
                  <Td className="text-right">{formatMaybePrice(row.price)}</Td>
                  <Td className="text-right">{formatMaybeMoney(row.cash_after)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/* ================= 小部件 ================= */

function Th({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <th className={`px-3 pb-2.5 pt-0 font-label-caps text-text-secondary ${className}`}>{children}</th>
  );
}

function Td({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <td className={`px-3 py-3.5 tabular-nums ${className}`}>{children}</td>;
}

function EmptyBox({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border-subtle px-5 py-10 text-center font-body-sm text-text-secondary">
      {children}
    </div>
  );
}

function StatusDot({ status, text }: { status: string; text: string }) {
  const dot =
    status === "filled" ? "bg-accent-success" : status === "cancelled" ? "bg-danger" : "bg-text-secondary";
  return (
    <span className="inline-flex items-center gap-1.5 font-body-sm text-[11px] text-text-primary">
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {text}
    </span>
  );
}

function SafetyRow({ label, tone, value }: { label: string; tone: "up" | "neutral" | "danger"; value: string }) {
  const dot = tone === "up" ? "bg-accent-success" : tone === "danger" ? "bg-danger" : "bg-text-secondary";
  return (
    <div className="flex items-center justify-between border-b border-border-subtle/50 py-1.5 font-data-mono text-xs last:border-b-0">
      <span className="font-body-sm text-[11.5px] text-text-secondary">{label}</span>
      <span className="inline-flex items-center gap-1.5 text-text-primary">
        <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
        {value}
      </span>
    </div>
  );
}

/* ================= 工具 ================= */

function manualShare(row: AccountPositionView) {
  let share = 0;
  for (const [source, value] of Object.entries(row.source_breakdown)) {
    if (source === "manual") share += value;
  }
  return Math.max(0, Math.min(1, share));
}

function sourceLabel(row: AccountPositionView, text: Text) {
  const share = manualShare(row);
  if (share >= 0.999) return text.manual;
  if (share <= 0.001) return text.strategy;
  return text.mixed;
}

function formatTimestamp(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

function toneClass(value: number) {
  if (!Number.isFinite(value) || value === 0) return "text-text-primary";
  return value > 0 ? "text-accent-success" : "text-danger";
}

function formatMoney(value: number) {
  return `${value < 0 ? "-" : ""}$${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function signedMoney(value: number) {
  return `${value >= 0 ? "+" : ""}${formatMoney(value)}`;
}

function signedPct(value: number) {
  if (!Number.isFinite(value)) return "--";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

function formatPrice(value: number) {
  return Number.isFinite(value)
    ? value.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })
    : "--";
}

function formatQuantity(value: number) {
  return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "--";
}

function formatMaybeQuantity(value: number | null | undefined) {
  return typeof value === "number" ? formatQuantity(value) : "--";
}

function formatMaybePrice(value: number | null | undefined) {
  return typeof value === "number" ? formatPrice(value) : "--";
}

function formatMaybeMoney(value: number | null | undefined) {
  return typeof value === "number" ? formatMoney(value) : "--";
}

function formatReserved(order: PendingAccountOrderView) {
  if (order.reserved_cash > 0) return formatMoney(order.reserved_cash);
  if (order.reserved_quantity > 0) return formatQuantity(order.reserved_quantity);
  return "--";
}

function shortId(id: string) {
  return id.length > 12 ? `${id.slice(0, 8)}...` : id;
}
