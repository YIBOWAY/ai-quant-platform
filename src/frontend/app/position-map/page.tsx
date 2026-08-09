import { Layers } from "lucide-react";
import { AccountRefreshControl } from "@/components/AccountRefreshControl";
import { ErrorBanner } from "@/components/ErrorBanner";
import {
  PositionMapWorkspace,
  type BacktestExposureRow,
} from "@/components/position-map/PositionMapWorkspace";
import {
  formatMoney,
  getBacktestDetail,
  getBacktests,
  getPaperAccountActivity,
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
      "One persistent simulated account: net value, cash, per-symbol exposure with strategy/manual attribution, and the full audit ledger.",
    netValue: "Net Value",
    availableCash: "Available Cash",
    unrealized: "Unrealized P&L",
    realized: "Realized P&L",
    invested: "Invested",
    cashLabel: "Cash",
    detailsToggle: "Account details · margin & balance",
    accountMargin: "Account Margin",
    orderMargin: "Order Margin",
    marginBuffer: "Margin Buffer",
    accountBalance: "Account Balance",
    reservedCash: "Reserved",
    initialBase: "initial base",
    priceSource: "Prices",
    priceKinds: {
      futu_snapshot: "Futu live snapshot",
      last_close: "last real close",
    } as Record<string, string>,
    accountUnavailable: "Account unreachable — values hidden until the backend responds.",
  },
  zh: {
    eyebrow: "模拟账户",
    title: "持仓地图",
    subtitle: "单一持续模拟账户：净值、现金、按标的的暴露（策略/手动归因），以及完整账本流水。",
    netValue: "净值",
    availableCash: "可用现金",
    unrealized: "未实现盈亏",
    realized: "已实现损益",
    invested: "已投资",
    cashLabel: "现金",
    detailsToggle: "账户详情 · 保证金与余额",
    accountMargin: "账户保证金",
    orderMargin: "订单保证金",
    marginBuffer: "保证金缓冲",
    accountBalance: "账户余额",
    reservedCash: "冻结",
    initialBase: "初始本金",
    priceSource: "报价",
    priceKinds: {
      futu_snapshot: "Futu 实时快照",
      last_close: "最近真实收盘",
    } as Record<string, string>,
    accountUnavailable: "账户接口不可达——在后端恢复前隐藏数值，避免误读。",
  },
} as const;

type PositionMapPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

type AccountTab = "positions" | "orders" | "order-history" | "balance-history" | "trade-log";

const accountTabs: AccountTab[] = ["positions", "orders", "order-history", "balance-history", "trade-log"];

function resolveAccountTab(value: string | string[] | undefined): AccountTab {
  const raw = Array.isArray(value) ? value[0] : value;
  return accountTabs.includes(raw as AccountTab) ? (raw as AccountTab) : "positions";
}

export default async function PositionMapPage({ searchParams }: PositionMapPageProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  const text = copy[locale];
  const initialTab = resolveAccountTab(params.tab);
  const [activity, backtests, health] = await Promise.all([
    getPaperAccountActivity(200),
    getBacktests(),
    getCachedHealth(),
  ]);
  const account = activity.account;
  const includeSample = shouldIncludeSampleRuns(params);
  const latestBacktest = selectDisplayRun(backtests.backtests, includeSample);
  const backtestDetail = latestBacktest ? await getBacktestDetail(latestBacktest.id) : null;
  const backtestExposure = latestExposure(backtestDetail?.positions ?? []);

  const accountDown = Boolean(activity.apiError || account.apiError);
  const positions = [...account.positions].sort(
    (a, b) => Math.abs(b.market_value) - Math.abs(a.market_value),
  );
  const grossInvested = positions.reduce((sum, p) => sum + Math.abs(p.market_value), 0);
  const priceSourceLabel = `${text.priceSource}: ${text.priceKinds[account.price_source.kind] ?? account.price_source.kind}`;
  const totalPnl = account.realized_pnl + account.unrealized_pnl;
  const investedPct = account.equity > 0 ? grossInvested / account.equity : 0;

  return (
    <div className="flex h-full flex-1 flex-col overflow-y-auto bg-bg-base text-text-primary">
      <ErrorBanner
        locale={locale}
        messages={[activity.apiError, account.apiError, backtests.apiError, health.apiError, backtestDetail?.apiError]}
      />

      {/* ---------- Hero：净值主角 + 次级指标 + 资金构成 ---------- */}
      <header className="border-b border-border-subtle px-4 pb-6 pt-5 lg:px-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-text-secondary">
              <Layers size={16} className="text-text-primary" />
              <span className="font-label-caps uppercase">
                {text.eyebrow} · {accountDown ? "default" : account.account_id} / {account.base_currency}
              </span>
            </div>
            <h1 className="mt-1 font-headline-xl text-text-primary">{text.title}</h1>
            <p className="mt-2 max-w-2xl font-body-sm text-text-secondary">{text.subtitle}</p>
          </div>
          <AccountRefreshControl locale={locale} />
        </div>

        <div className="mt-7 flex flex-wrap items-end gap-x-14 gap-y-6">
          <div>
            <div className="font-label-caps text-text-secondary">{text.netValue}</div>
            <div className="mt-1 font-data-mono text-[34px] font-semibold leading-none tabular-nums text-text-primary">
              {accountDown ? "--" : formatMoney2(account.equity)}
            </div>
            {!accountDown ? (
              <div
                className={`mt-2 inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-data-mono text-xs font-semibold ${
                  totalPnl >= 0 ? "bg-accent-success/10 text-accent-success" : "bg-danger/10 text-danger"
                }`}
              >
                {totalPnl >= 0 ? "▲" : "▼"} {signedMoney(totalPnl)} · {signedPct(account.pnl_pct)}
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-x-10 gap-y-4 pb-1">
            <HeroMetric
              label={text.availableCash}
              sub={`${text.reservedCash} ${accountDown ? "--" : formatMoney(account.reserved_cash)}`}
              value={accountDown ? "--" : formatMoney(account.available_cash)}
            />
            <HeroMetric
              label={text.unrealized}
              tone={accountDown ? "neutral" : totalTone(account.unrealized_pnl)}
              value={accountDown ? "--" : signedMoney(account.unrealized_pnl)}
            />
            <HeroMetric
              label={text.realized}
              tone={accountDown ? "neutral" : totalTone(account.realized_pnl)}
              value={accountDown ? "--" : signedMoney(account.realized_pnl)}
            />
          </div>
        </div>

        {!accountDown ? (
          <div className="mt-6 max-w-xl">
            <div className="flex h-2 overflow-hidden rounded-full">
              <div className="bg-info" style={{ width: `${Math.max(investedPct * 100, 1.5)}%` }} />
              <div className="flex-1 bg-bg-surface-muted" />
            </div>
            <div className="mt-1.5 flex justify-between font-data-mono text-[11px] text-text-secondary">
              <span>
                <span className="mr-1.5 inline-block h-[7px] w-[7px] rounded-sm bg-info" />
                {text.invested} <b className="font-medium text-text-primary">{formatMoney(grossInvested)} · {(investedPct * 100).toFixed(1)}%</b>
              </span>
              <span>
                <span className="mr-1.5 inline-block h-[7px] w-[7px] rounded-sm bg-bg-surface-muted outline outline-1 outline-border-subtle" />
                {text.cashLabel} <b className="font-medium text-text-primary">{formatMoney(account.available_cash)} · {((1 - investedPct) * 100).toFixed(1)}%</b>
              </span>
            </div>
          </div>
        ) : null}

        <details className="group mt-4">
          <summary className="flex w-fit cursor-pointer list-none items-center gap-1.5 font-body-sm text-text-secondary transition-colors hover:text-text-primary [&::-webkit-details-marker]:hidden">
            <span className="text-[9px] transition-transform group-open:rotate-90">▸</span>
            {text.detailsToggle}
          </summary>
          <div className="mt-3 flex flex-wrap gap-x-10 gap-y-3">
            <DetailMetric label={text.accountMargin} value={accountDown ? "--" : formatMoney(grossInvested)} />
            <DetailMetric label={text.orderMargin} value={accountDown ? "--" : formatMoney(account.reserved_cash)} />
            <DetailMetric
              label={text.marginBuffer}
              value={accountDown || account.equity <= 0 ? "--" : `${((account.available_cash / account.equity) * 100).toFixed(2)}%`}
            />
            <DetailMetric label={text.accountBalance} value={accountDown ? "--" : formatMoney(account.cash)} />
            <DetailMetric
              label={text.initialBase}
              value={accountDown ? "--" : formatMoney(account.initial_cash)}
            />
          </div>
        </details>

        {accountDown ? (
          <p className="mt-4 font-body-sm text-danger">{text.accountUnavailable}</p>
        ) : null}
      </header>

      {/* ---------- 工作区：tabs + 面板 + 情境右栏（客户端） ---------- */}
      <PositionMapWorkspace
        account={account}
        accountDown={accountDown}
        backtestExposure={backtestExposure}
        backtestHref={latestBacktest ? localizePath(`/backtest/${latestBacktest.id}`, locale) : null}
        balanceHistory={activity.balance_history}
        initialTab={initialTab}
        locale={locale}
        orderHistory={activity.order_history}
        pendingOrders={activity.pending_orders}
        positions={positions}
        priceSourceLabel={priceSourceLabel}
        safety={{
          paperTrading: health.safety?.paper_trading ?? true,
          liveTrading: health.safety?.live_trading_enabled ?? false,
        }}
        totals={{
          orders: activity.pending_order_total,
          orderHistory: activity.order_history_total,
          balanceHistory: activity.balance_history_total,
          tradeLog: activity.trade_log_total,
        }}
        tradeLog={activity.trade_log}
      />
    </div>
  );
}

function HeroMetric({
  label,
  sub,
  tone = "neutral",
  value,
}: {
  label: string;
  sub?: string;
  tone?: "neutral" | "success" | "danger";
  value: string;
}) {
  const toneClass =
    tone === "success" ? "text-accent-success" : tone === "danger" ? "text-danger" : "text-text-primary";
  return (
    <div className="border-l border-border-subtle pl-4 first:border-l-0 first:pl-0">
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className={`mt-1 font-data-mono text-lg font-semibold tabular-nums ${toneClass}`}>{value}</div>
      {sub ? <div className="mt-0.5 font-data-mono text-[10.5px] text-text-secondary">{sub}</div> : null}
    </div>
  );
}

function DetailMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className="mt-0.5 font-data-mono text-sm font-medium tabular-nums text-text-primary">{value}</div>
    </div>
  );
}

function totalTone(value: number): "neutral" | "success" | "danger" {
  if (!Number.isFinite(value) || value === 0) return "neutral";
  return value > 0 ? "success" : "danger";
}

function formatMoney2(value: number) {
  return `${value < 0 ? "-" : ""}$${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function signedMoney(value: number) {
  return `${value >= 0 ? "+" : ""}${formatMoney(value)}`;
}

function signedPct(value: number) {
  if (!Number.isFinite(value)) return "--";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

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
