import Link from "next/link";
import { Activity, ArrowRight, BriefcaseBusiness, ShieldAlert } from "lucide-react";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { SyntheticMetricsWarning } from "@/components/DataSourceBadge";
import { ErrorBanner } from "@/components/ErrorBanner";
import { AccountTradePanel } from "@/components/forms/AccountTradePanel";
import { PaperRunForm } from "@/components/forms/PaperRunForm";
import { PaperStrategyOpsPanel } from "@/components/forms/PaperStrategyOpsPanel";
import { PaperStrategySleevesPanel } from "@/components/forms/PaperStrategySleevesPanel";
import { PendingOrderCancelButton } from "@/components/forms/PendingOrderCancelButton";
import { PositionMapPageContent } from "@/components/position-map/PositionMapPageContent";
import { Tabs } from "@/components/ui/Tabs";
import {
  Card,
  MetricStat,
  PageHeader,
  SectionTitle,
  StatusPill,
  TableScrollHint,
  TerminalTable,
  tableScrollHintText,
} from "@/components/ui/primitives";
import {
  type AccountPositionView,
  type LedgerEntryView,
  type PendingAccountOrderView,
  formatMoney,
  getPaperAccount,
  getPaperAccountLedger,
  getPaperRunDetail,
  getPaperRuns,
  getPaperStrategyConfigs,
  getPaperStrategySleeveDetail,
  getPaperStrategySleeves,
  getStrategies,
} from "@/lib/api";
import { localizePath } from "@/lib/locale";
import { resolvePaperAccountAvailableCash } from "@/lib/paperAccountState";
import { isSampleSource } from "@/components/DataSourceBadge";
import { selectDisplayRun, shouldIncludeSampleRuns } from "@/lib/runSource";
import { getCachedHealth } from "@/lib/serverApi";
import { getServerLocale } from "@/lib/serverLocale";
import { accountValuation, hasMarketPrice, valuationWarning } from "@/lib/accountValuation";

const copy = {
  en: {
    pageEyebrow: "Paper trading",
    pageTitle: "Paper Trading",
    pageSubtitle:
      "One persistent simulated account: manual orders, strategy sleeves, and full-account controls. Historical replay stays separate and never touches it.",
    finalEquity: "Final Equity",
    orders: "Orders",
    riskBreaches: "Risk Breaches",
    trades: "Trades",
    latestRun: "latest run",
    noPaperRun: "No paper run yet",
    openAria: (id: string) => `Open ${id}`,
    openRun: "Open run",
    tradesTitle: "Trades",
    tradesDesc: "Latest simulated paper trades.",
    tradesEmptyTitle: "No trades recorded",
    tradesEmptyDesc: "This run may have produced orders without fills, or no run exists yet.",
    orderLifecycleTitle: "Order Lifecycle",
    orderLifecycleDesc: "Order status events from the newest paper run.",
    orderLifecycleEmptyTitle: "Order lifecycle table pending",
    orderLifecycleEmptyDesc: "Order and fill details will be rendered after a paper run completes.",
    riskBreachesTitle: "Risk Breaches",
    riskBreachesDesc: "Latest rule hits captured by the paper trading engine.",
    riskBreachesEmptyTitle: "No risk breaches logged",
    riskBreachesEmptyDesc: "This run did not emit any risk breach rows.",
    riskCenter: "Account Controls & Safety",
    accountFreezeState: "account frozen",
    replayKillSwitch: "replay safety lock",
    localBatchNote: "Runs are local batch simulations only.",
    killSwitchExplainer:
      "The latest historical replay recorded orders but zero fills, with risk breaches logged — most often its safety lock. This does not mean the persistent account is frozen.",
    historyResultsTitle: "Historical Replay Results",
    historyResultsDesc: "Saved results from the latest research replay. They do not change the persistent account.",
    accountUnavailable: "Account unreachable — values hidden until the backend responds.",
    accountValue: "Account Value",
    accountCash: "Available Cash",
    accountPnl: "Total P&L",
    openMap: "Open position map",
    replayTitle: "Historical Replay (research)",
    replayDesc:
      "Batch-replay a strategy over a past date window. This does NOT touch the account above — it is a research backtest in trading-desk clothing.",
    tabLive: "Live Account",
    tabReplay: "Historical Replay",
    researchOnly: "Research only",
    holdings: "Holdings",
    holdingsEmpty: "No open positions. Place a manual order or rebalance to a strategy.",
    holdingsUnavailable: "Holdings unavailable while the account API is unreachable.",
    pendingOrders: "Pending Limit Orders",
    pendingOrdersEmpty: "No pending limit orders.",
    pendingOrdersUnavailable: "Pending limit orders unavailable while the account API is unreachable.",
    symbol: "Symbol",
    order: "Order",
    quantity: "Qty (sh)",
    limit: "Limit",
    lastCheck: "Last check",
    sharesUnit: "sh",
    invested: "Invested",
    priceSource: "Prices",
    marketValue: "Market Value",
    avgCost: "Avg Cost",
    lastPrice: "Last",
    sourceMix: "Source Mix",
    weight: "Weight",
    pnl: "P&L",
    tradeActions: "Manual & Advanced Actions",
    ledgerTitle: "Ledger Activity",
    ledgerDesc: "Latest ledger entries from orders, rebalances and system events.",
    ledgerEmptyTitle: "No activity yet",
    ledgerEmptyDesc: "Manual orders and rebalances will appear here.",
    ledgerUnavailable: "Ledger unavailable while the account API is unreachable.",
    manual: "Manual",
    strategy: "Strategy",
    kind: {
      fill: "Fill",
      rebalance_fill: "Rebalance fill",
      deposit: "Deposit",
      reset: "Reset",
      fee: "Fee",
      freeze: "Freeze",
      unfreeze: "Unfreeze",
      order_pending: "Pending order",
    } as Record<string, string>,
    side: { BUY: "Buy", SELL: "Sell" } as Record<string, string>,
    runHistoryTitle: "Replay Run History",
    runHistoryDesc: "Saved research replays, newest first.",
    runHistoryEmptyTitle: "No saved replay runs",
    runHistoryEmptyDesc: "Run a historical replay to populate this list.",
    hiddenSampleRuns: (n: number) => `${n} sample run(s) hidden —`,
    showSample: "show them",
    hideSample: "hide sample runs",
    runColumns: {
      id: "Run ID",
      source: "Source",
      status: "Status",
      final_equity: "Final Equity",
      trade_count: "Trades",
      risk_breach_count: "Breaches",
      open: "",
    },
    on: "on",
    off: "off",
    unknown: "unknown",
  },
  zh: {
    pageEyebrow: "模拟交易",
    pageTitle: "模拟交易",
    pageSubtitle:
      "单一持续模拟账户：手动下单、策略仓与全账户控制都在这里。历史回放保持隔离，不触碰账户。",
    finalEquity: "最终权益",
    orders: "订单",
    riskBreaches: "风控触发",
    trades: "成交",
    latestRun: "最新运行",
    noPaperRun: "暂无模拟运行",
    openAria: (id: string) => `打开 ${id}`,
    openRun: "打开运行",
    tradesTitle: "成交",
    tradesDesc: "最新的模拟成交。",
    tradesEmptyTitle: "暂无成交记录",
    tradesEmptyDesc: "本次运行可能产生了订单但没有成交，或者尚未存在任何运行。",
    orderLifecycleTitle: "订单生命周期",
    orderLifecycleDesc: "来自最新模拟运行的订单状态事件。",
    orderLifecycleEmptyTitle: "订单生命周期表待生成",
    orderLifecycleEmptyDesc: "模拟运行完成后将显示订单与成交明细。",
    riskBreachesTitle: "风控触发",
    riskBreachesDesc: "模拟交易引擎捕获的最新规则触发。",
    riskBreachesEmptyTitle: "暂无风控触发记录",
    riskBreachesEmptyDesc: "本次运行未产生任何风控触发记录。",
    riskCenter: "账户操作与安全状态",
    accountFreezeState: "账户冻结",
    replayKillSwitch: "回放安全锁",
    localBatchNote: "运行仅为本地批量模拟。",
    killSwitchExplainer:
      "最近一次历史回放产生了订单但 0 成交，且记录了风控触发——最常见原因是它自己的安全锁。这不代表上面的持续账户被冻结。",
    historyResultsTitle: "历史回放结果",
    historyResultsDesc: "最近一次研究回放保存的结果，不会改变持续模拟账户。",
    accountUnavailable: "账户接口不可达——在后端恢复前隐藏数值，避免误读。",
    accountValue: "账户净值",
    accountCash: "可用现金",
    accountPnl: "总盈亏",
    openMap: "打开持仓地图",
    replayTitle: "历史回放（研究）",
    replayDesc:
      "对一段历史日期区间批量回放某个策略。它不会触及上面的账户——本质是穿着交易台外衣的研究回测。",
    tabLive: "当前账户",
    tabReplay: "历史回放",
    researchOnly: "仅研究",
    holdings: "持仓",
    holdingsEmpty: "暂无持仓。手动下单或按策略再平衡即可建立持仓。",
    holdingsUnavailable: "账户接口不可达，暂不展示持仓，避免把离线误判为空仓。",
    pendingOrders: "待处理限价单",
    pendingOrdersEmpty: "暂无待处理限价单。",
    pendingOrdersUnavailable: "账户接口不可达，暂不展示待处理限价单。",
    symbol: "标的",
    order: "订单",
    quantity: "数量（股）",
    limit: "限价",
    lastCheck: "上次检查",
    sharesUnit: "股",
    invested: "已投资",
    priceSource: "报价",
    marketValue: "市值",
    avgCost: "均价",
    lastPrice: "现价",
    sourceMix: "来源拆分",
    weight: "权重",
    pnl: "盈亏",
    tradeActions: "手动与高级账户动作",
    ledgerTitle: "账本动态",
    ledgerDesc: "下单、再平衡与系统事件产生的最新账本记录。",
    ledgerEmptyTitle: "暂无流水",
    ledgerEmptyDesc: "手动下单或再平衡后，这里会出现流水。",
    ledgerUnavailable: "账户流水接口不可达，暂不展示流水，避免把离线误判为暂无活动。",
    manual: "手动",
    strategy: "策略",
    kind: {
      fill: "成交",
      rebalance_fill: "再平衡成交",
      deposit: "入金",
      reset: "重置",
      fee: "费用",
      freeze: "冻结",
      unfreeze: "解冻",
      order_pending: "挂单",
    } as Record<string, string>,
    side: { BUY: "买入", SELL: "卖出" } as Record<string, string>,
    runHistoryTitle: "回放运行历史",
    runHistoryDesc: "已保存的研究回放，按时间倒序。",
    runHistoryEmptyTitle: "暂无已保存的回放运行",
    runHistoryEmptyDesc: "运行一次历史回放后，这里会出现列表。",
    hiddenSampleRuns: (n: number) => `已隐藏 ${n} 条 sample 演示运行 ——`,
    showSample: "显示",
    hideSample: "隐藏 sample 运行",
    runColumns: {
      id: "运行 ID",
      source: "数据源",
      final_equity: "最终权益",
      trade_count: "成交数",
      risk_breach_count: "风控触发",
      open: "",
    },
    on: "开",
    off: "关",
    unknown: "未知",
  },
} as const;

type PaperTradingProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function PaperTrading({ searchParams }: PaperTradingProps) {
  const params = (await searchParams) ?? {};
  const rawView = Array.isArray(params.view) ? params.view[0] : params.view;
  const view = rawView === "map" ? "map" : "account";
  if (view === "map") {
    return <PositionMapPageContent searchParams={Promise.resolve(params)} />;
  }
  const [account, ledger, health, paperRuns, strategies, strategyConfigs, strategySleeves, locale] =
    await Promise.all([
    getPaperAccount(),
    getPaperAccountLedger(8),
    getCachedHealth(),
    getPaperRuns(),
    getStrategies(),
    getPaperStrategyConfigs(),
    getPaperStrategySleeves(),
    getServerLocale(params),
  ]);
  const text = copy[locale];
  const includeSample = shouldIncludeSampleRuns(params);
  const latestRun = selectDisplayRun(paperRuns.paper_runs, includeSample);
  const [detail, sleeveDetails] = await Promise.all([
    latestRun ? getPaperRunDetail(latestRun.id) : Promise.resolve(null),
    Promise.all(
      strategySleeves.sleeves.map((sleeve) => getPaperStrategySleeveDetail(sleeve.sleeve_id)),
    ),
  ]);
  const latest = latestRun?.summary;
  const accountDown = Boolean(account.apiError);
  const ledgerDown = Boolean(ledger.apiError);
  const accountPnlPositive = account.pnl_abs >= 0;
  const killSwitchExplainerVisible =
    (latest?.trade_count ?? 0) === 0 && (latest?.risk_breach_count ?? 0) > 0;
  const hiddenSampleCount = includeSample
    ? 0
    : paperRuns.paper_runs.filter((run) => isSampleSource(run.source)).length;
  const visibleRuns = includeSample
    ? paperRuns.paper_runs
    : paperRuns.paper_runs.filter((run) => !isSampleSource(run.source));

  const liveTab = (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-6">
        <AccountHero
          account={account}
          accountDown={accountDown}
          health={health}
          positive={accountPnlPositive}
          text={text}
          locale={locale}
        />
        <HoldingsSection
          account={account}
          accountDown={accountDown}
          locale={locale}
          text={text}
        />
        <PaperStrategySleevesPanel
          accountAvailableCash={resolvePaperAccountAvailableCash(account)}
          accountDown={accountDown}
          configs={strategyConfigs.configs}
          unavailableConfigs={strategyConfigs.unavailable_configs}
          locale={locale}
          sleeveDetails={sleeveDetails}
          sleeves={strategySleeves.sleeves}
          strategies={strategies.strategies}
        />
        <PendingOrdersSection
          account={account}
          accountDown={accountDown}
          locale={locale}
          text={text}
        />
        <LedgerPanel
          entries={ledger.entries}
          ledgerDown={ledgerDown}
          text={text}
        />
        <PaperStrategyOpsPanel accountDown={accountDown} locale={locale} />
      </div>
      <aside className="h-fit xl:sticky xl:top-0 xl:border-l xl:border-border-subtle xl:pl-6">
        <h2 className="mb-3 flex items-center gap-2 font-label-caps text-text-primary">
          <Activity className="text-accent-success" size={15} /> {text.tradeActions}
        </h2>
        <AccountTradePanel
          locale={locale}
          killSwitch={account.kill_switch}
          pendingOrderCount={(account.pending_orders ?? []).length}
          strategies={strategies.strategies}
        />
      </aside>
    </div>
  );

  const replayTab = (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
      <Card padded className="h-fit">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-label-caps text-text-primary">{text.replayTitle}</h3>
          <StatusPill label="" value={text.researchOnly} tone="info" />
        </div>
        <p className="mb-3 mt-1 font-body-sm text-text-secondary">{text.replayDesc}</p>
        <PaperRunForm
          locale={locale}
          futuReachable={health.futu_opend?.reachable !== false}
          replayKillSwitch={health.safety?.kill_switch !== false}
        />
        <div className="mt-4 flex items-center gap-2 font-body-sm text-text-secondary">
          <BriefcaseBusiness size={16} /> {text.localBatchNote}
        </div>
      </Card>

      <div className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="font-label-caps text-text-primary">{text.historyResultsTitle}</h2>
            <p className="mt-1 font-body-sm text-text-secondary">{text.historyResultsDesc}</p>
          </div>
          {hiddenSampleCount > 0 ? (
            <p className="font-body-sm text-text-secondary">
              {text.hiddenSampleRuns(hiddenSampleCount)}{" "}
              <Link className="text-info underline underline-offset-2" href="?include_sample=1">
                {text.showSample}
              </Link>
            </p>
          ) : null}
        </div>
        <SyntheticMetricsWarning source={latestRun?.source} locale={locale} />
        {killSwitchExplainerVisible ? (
          <Card tone="info" padded>
            <p className="font-body-sm text-info">{text.killSwitchExplainer}</p>
          </Card>
        ) : null}

        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <MetricStat label={text.finalEquity} value={formatMoney(latest?.final_equity)} />
          <MetricStat label={text.orders} value={latest?.order_count ?? 0} />
          <MetricStat
            label={text.riskBreaches}
            value={latest?.risk_breach_count ?? 0}
            tone={(latest?.risk_breach_count ?? 0) > 0 ? "danger" : "neutral"}
          />
          <MetricStat label={text.trades} value={latest?.trade_count ?? 0} />
        </section>

        <div className="flex flex-wrap items-center justify-between gap-2 border-y border-border-subtle py-2.5">
          <div className="flex min-w-0 items-center gap-3">
            <span className="shrink-0 font-label-caps text-text-secondary">{text.latestRun}</span>
            <span className="truncate font-data-mono text-xs text-text-primary">
              {latestRun?.id ?? text.noPaperRun}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {latestRun?.source ? <DataSourceBadge source={latestRun.source} /> : null}
            {latestRun ? (
              <Link
                aria-label={text.openAria(latestRun.id)}
                className="font-body-sm text-info underline-offset-2 hover:underline"
                href={localizePath(`/paper-trading/${latestRun.id}`, locale)}
              >
                {text.openRun}
              </Link>
            ) : null}
          </div>
        </div>

        <RunHistory locale={locale} runs={visibleRuns} text={text} />

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <DataPreviewTable
            title={text.tradesTitle}
            description={text.tradesDesc}
            locale={locale}
            rows={detail?.trades ?? []}
            emptyTitle={text.tradesEmptyTitle}
            emptyDescription={text.tradesEmptyDesc}
          />
          <DataPreviewTable
            title={text.orderLifecycleTitle}
            description={text.orderLifecycleDesc}
            locale={locale}
            rows={detail?.order_events ?? []}
            emptyTitle={text.orderLifecycleEmptyTitle}
            emptyDescription={text.orderLifecycleEmptyDesc}
          />
          <div className="lg:col-span-2">
            <DataPreviewTable
              title={text.riskBreachesTitle}
              description={text.riskBreachesDesc}
              locale={locale}
              rows={detail?.risk_breaches ?? []}
              emptyTitle={text.riskBreachesEmptyTitle}
              emptyDescription={text.riskBreachesEmptyDesc}
            />
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto bg-bg-base p-4 lg:p-6">
      <ErrorBanner
        locale={locale}
        messages={[
          account.apiError,
          ledger.apiError,
          health.apiError,
          paperRuns.apiError,
          strategyConfigs.apiError,
          strategySleeves.apiError,
          detail?.apiError,
          ...sleeveDetails.map((sleeveDetail) => sleeveDetail.apiError),
        ]}
      />
      <PageHeader
        eyebrow={text.pageEyebrow}
        icon={<BriefcaseBusiness size={18} className="text-accent-success" />}
        title={text.pageTitle}
        subtitle={text.pageSubtitle}
        actions={
          <div className="flex flex-wrap gap-2">
          <Link
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle px-3 py-1.5 font-body-sm text-text-primary transition-colors hover:bg-bg-surface-muted"
            href={localizePath("/research-evaluation?tab=paper", locale)}
          >
            {locale === "zh" ? "模拟运行复盘" : "Paper review"}
            <ArrowRight size={13} />
          </Link>
          <a
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle px-3 py-1.5 font-body-sm text-text-primary transition-colors hover:bg-bg-surface-muted"
            href={localizePath("/paper-trading?view=map", locale)}
          >
            {text.openMap}
            <ArrowRight size={13} />
          </a>
          </div>
        }
      />
      <Tabs
        items={[
          { id: "live", label: <span className="flex items-center gap-2"><Activity size={15} />{text.tabLive}</span>, content: liveTab },
          { id: "replay", label: <span className="flex items-center gap-2"><Activity size={15} />{text.tabReplay}</span>, content: replayTab },
        ]}
      />
    </div>
  );
}

function AccountHero({
  account,
  accountDown,
  health,
  positive,
  text,
  locale,
}: {
  account: Awaited<ReturnType<typeof getPaperAccount>>;
  accountDown: boolean;
  health: Awaited<ReturnType<typeof getCachedHealth>>;
  positive: boolean;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  locale: "en" | "zh";
}) {
  const valuationComplete = accountValuation(account).complete;
  const valuationMessage = accountDown ? null : valuationWarning(account, locale);
  return (
    <section className="border-b border-border-subtle pb-5" data-paper-account-hero="true">
      <div className="flex flex-wrap items-end gap-x-10 gap-y-4">
        <div>
          <div className="font-label-caps text-text-secondary">{text.accountValue}</div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="font-data-mono text-3xl font-semibold tabular-nums leading-none text-text-primary">
              {accountDown || !valuationComplete ? "—" : formatMoney(account.market_equity ?? account.equity)}
            </span>
            {!accountDown && valuationComplete ? (
              <span
                className={`inline-flex items-center rounded-md px-2 py-0.5 font-data-mono text-xs font-semibold ${
                  positive
                    ? "bg-accent-success/10 text-accent-success"
                    : "bg-danger/10 text-danger"
                }`}
                title={text.accountPnl}
              >
                {positive ? "+" : ""}
                {formatMoney(account.pnl_abs)} · {positive ? "+" : ""}
                {(account.pnl_pct * 100).toFixed(2)}%
              </span>
            ) : null}
          </div>
        </div>
        <InlineMetric
          label={text.accountCash}
          value={accountDown ? "--" : formatMoney(account.available_cash)}
        />
        <InlineMetric
          label={text.invested}
          value={accountDown || !valuationComplete ? "—" : `${(account.invested_pct * 100).toFixed(1)}%`}
        />
        <InlineMetric
          label={text.priceSource}
          value={accountDown ? text.unknown : account.price_source.kind}
        />
        <div className="pb-0.5 xl:ml-auto">
          <SafetyFlags account={account} health={health} text={text} />
        </div>
      </div>
      {accountDown ? (
        <p className="mt-3 font-body-sm text-danger">{text.accountUnavailable}</p>
      ) : null}
      {valuationMessage ? <p role="status" className="mt-3 font-body-sm text-warning">{valuationMessage}</p> : null}
    </section>
  );
}

function InlineMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="border-l border-border-subtle pl-4 first:border-l-0 first:pl-0">
      <div className="font-label-caps text-[10px] uppercase text-text-secondary">{label}</div>
      <div className="mt-0.5 font-data-mono text-sm font-semibold tabular-nums text-text-primary">
        {value}
      </div>
    </div>
  );
}

function SafetyFlags({
  account,
  health,
  text,
}: {
  account: Awaited<ReturnType<typeof getPaperAccount>>;
  health: Awaited<ReturnType<typeof getCachedHealth>>;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  const fmt = (value: boolean | undefined) =>
    value === undefined ? text.unknown : value ? text.on : text.off;
  return (
    <div className="flex flex-wrap items-center gap-1.5" title={text.riskCenter}>
      <ShieldAlert size={13} className="text-text-secondary" />
      <StatusPill label="paper" value={fmt(health.safety?.paper_trading)} tone="success" />
      <StatusPill
        label="live"
        value={fmt(health.safety?.live_trading_enabled)}
        tone={health.safety?.live_trading_enabled ? "danger" : "neutral"}
      />
      <StatusPill
        label={text.accountFreezeState}
        value={account.kill_switch ? text.on : text.off}
        tone={account.kill_switch ? "danger" : "neutral"}
      />
      <StatusPill
        label={text.replayKillSwitch}
        value={fmt(health.safety?.kill_switch)}
        tone={health.safety?.kill_switch ? "neutral" : "warning"}
      />
    </div>
  );
}

function HoldingsSection({
  account,
  accountDown,
  locale,
  text,
}: {
  account: Awaited<ReturnType<typeof getPaperAccount>>;
  accountDown: boolean;
  locale: "en" | "zh";
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  const valuationComplete = accountValuation(account).complete;
  const positions = [...account.positions].sort((a, b) => b.market_value - a.market_value);
  return (
    <section data-paper-holdings="true">
      <SectionTitle title={text.holdings} />
      {accountDown ? (
        <p className="py-3 font-body-sm text-text-secondary">{text.holdingsUnavailable}</p>
      ) : positions.length === 0 ? (
        <p className="py-3 font-body-sm text-text-secondary">{text.holdingsEmpty}</p>
      ) : (
        <TerminalTable
          columns={[
            { label: text.symbol },
            { label: text.quantity, align: "right" },
            { label: text.avgCost, align: "right" },
            { label: text.lastPrice, align: "right" },
            { label: text.weight, align: "right" },
            { label: text.marketValue, align: "right" },
            { label: text.pnl, align: "right" },
            { label: text.sourceMix },
          ]}
          minWidth="760px"
          scrollHint={<TableScrollHint label={tableScrollHintText[locale]} />}
        >
          {positions.map((position) => (
            <HoldingTableRow key={position.symbol} position={position} text={text} valuationComplete={valuationComplete} />
          ))}
        </TerminalTable>
      )}
    </section>
  );
}

function HoldingTableRow({
  position,
  text,
  valuationComplete,
}: {
  position: AccountPositionView;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  valuationComplete: boolean;
}) {
  const priceAvailable = hasMarketPrice(position);
  const pnlPositive = position.unrealized_pnl >= 0;
  const isLong = position.quantity >= 0;
  const weightPct = Math.max(0, Math.min(1, Math.abs(position.weight))) * 100;
  let manualShare = 0;
  for (const [source, share] of Object.entries(position.source_breakdown)) {
    if (source === "manual") manualShare += share;
  }
  manualShare = Math.max(0, Math.min(1, manualShare));
  const strategyShare = Math.max(0, 1 - manualShare);
  const sourceLabel =
    manualShare >= 0.999
      ? text.manual
      : manualShare <= 0.001
        ? text.strategy
        : `${text.strategy} ${(strategyShare * 100).toFixed(0)}% · ${text.manual} ${(manualShare * 100).toFixed(0)}%`;
  const sourceShort =
    manualShare >= 0.999
      ? text.manual
      : manualShare <= 0.001
        ? text.strategy
        : `${text.strategy} ${(strategyShare * 100).toFixed(0)}%`;

  return (
    <tr className="border-b border-border-subtle/50 last:border-b-0 hover:bg-bg-surface-muted/45">
      <td className="px-3 py-2 font-bold">{position.symbol}</td>
      <td className="px-3 py-2 text-right tabular-nums">
        {position.quantity.toLocaleString(undefined, { maximumFractionDigits: 2 })}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{position.avg_cost.toFixed(2)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{priceAvailable ? position.last_price.toFixed(2) : "—"}</td>
      <td className="px-3 py-2 text-right tabular-nums">{valuationComplete ? `${weightPct.toFixed(1)}%` : "—"}</td>
      <td className="px-3 py-2 text-right tabular-nums">{priceAvailable ? formatMoney(position.market_value) : "—"}</td>
      <td
        className={`px-3 py-2 text-right tabular-nums ${
          !priceAvailable ? "text-text-secondary" : pnlPositive ? "text-accent-success" : "text-danger"
        }`}
      >
        {priceAvailable ? `${pnlPositive ? "+" : ""}${formatMoney(position.unrealized_pnl)}` : "—"}
      </td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2" title={sourceLabel}>
          <span className="flex h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-bg-surface-muted">
            {strategyShare > 0 ? (
              <span
                className={isLong ? "bg-accent-success" : "bg-danger"}
                style={{ width: `${strategyShare * 100}%` }}
              />
            ) : null}
            {manualShare > 0 ? (
              <span
                className={isLong ? "bg-info" : "bg-danger/60"}
                style={{ width: `${manualShare * 100}%` }}
              />
            ) : null}
          </span>
          <span className="whitespace-nowrap text-[10px] uppercase text-text-secondary">
            {sourceShort}
          </span>
        </div>
      </td>
    </tr>
  );
}

function PendingOrdersSection({
  account,
  accountDown,
  locale,
  text,
}: {
  account: Awaited<ReturnType<typeof getPaperAccount>>;
  accountDown: boolean;
  locale: "en" | "zh";
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  const pending = [...(account.pending_orders ?? [])].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  );
  return (
    <section data-paper-pending-orders="true">
      <SectionTitle title={text.pendingOrders} />
      {accountDown ? (
        <p className="py-3 font-body-sm text-text-secondary">{text.pendingOrdersUnavailable}</p>
      ) : pending.length === 0 ? (
        <p className="py-3 font-body-sm text-text-secondary">{text.pendingOrdersEmpty}</p>
      ) : (
        <TerminalTable
          columns={[
            { label: text.order },
            { label: text.quantity, align: "right" },
            { label: text.limit, align: "right" },
            { label: text.lastCheck, align: "right" },
            { label: "", align: "right" },
          ]}
          minWidth="640px"
          scrollHint={<TableScrollHint label={tableScrollHintText[locale]} />}
        >
          {pending.map((order) => (
            <PendingOrderTableRow
              key={order.order_id}
              locale={locale}
              order={order}
              text={text}
            />
          ))}
        </TerminalTable>
      )}
    </section>
  );
}

function PendingOrderTableRow({
  locale,
  order,
  text,
}: {
  locale: "en" | "zh";
  order: PendingAccountOrderView;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  const sideLabel = text.side[order.side.toUpperCase()] ?? order.side;
  const isBuy = order.side.toUpperCase() === "BUY";
  const lastChecked =
    order.last_checked_at && order.last_checked_price != null
      ? `${formatShortTime(order.last_checked_at)} @ ${order.last_checked_price.toFixed(2)}`
      : "--";

  return (
    <tr className="border-b border-border-subtle/50 last:border-b-0 hover:bg-bg-surface-muted/45">
      <td className="px-3 py-2">
        <span className={`font-bold ${isBuy ? "text-accent-success" : "text-danger"}`}>
          {sideLabel} {order.symbol}
        </span>
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {order.quantity.toLocaleString(undefined, { maximumFractionDigits: 2 })}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{order.limit_price.toFixed(2)}</td>
      <td className="px-3 py-2 text-right text-xs tabular-nums text-text-secondary">
        {lastChecked}
      </td>
      <td className="px-3 py-2 text-right">
        <PendingOrderCancelButton locale={locale} orderId={order.order_id} />
      </td>
    </tr>
  );
}

function LedgerPanel({
  entries,
  ledgerDown,
  text,
}: {
  entries: LedgerEntryView[];
  ledgerDown: boolean;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  return (
    <section data-paper-ledger="true">
      <SectionTitle title={text.ledgerTitle} hint={text.ledgerDesc} />
      {ledgerDown ? (
        <p className="py-3 font-body-sm text-text-secondary">{text.ledgerUnavailable}</p>
      ) : entries.length ? (
        <ol className="divide-y divide-border-subtle/60 border-y border-border-subtle">
          {entries.map((entry) => {
            const isStrategy = entry.source.startsWith("strategy:");
            const kindLabel = text.kind[entry.kind] ?? entry.kind;
            const sideLabel = entry.side ? (text.side[entry.side.toUpperCase()] ?? entry.side) : "";
            const isSell = entry.side?.toUpperCase() === "SELL";
            return (
              <li
                className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2"
                key={entry.entry_id}
              >
                <span className="flex items-center gap-2 font-data-mono text-xs">
                  <span className="font-label-caps text-text-secondary">{kindLabel}</span>
                  {entry.source !== "system" ? (
                    <span
                      className={`rounded-md border px-1.5 py-0.5 text-[10px] uppercase ${
                        isStrategy
                          ? "border-accent-success/40 bg-accent-success/10 text-accent-success"
                          : "border-info/40 bg-info/10 text-info"
                      }`}
                    >
                      {isStrategy ? text.strategy : text.manual}
                    </span>
                  ) : null}
                  {entry.symbol ? (
                    <span className={isSell ? "text-danger" : "text-accent-success"}>
                      {sideLabel} {entry.symbol}
                      {entry.quantity != null
                        ? ` ${Math.abs(entry.quantity).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
                        : ""}
                      {entry.price != null ? ` @ ${entry.price.toFixed(2)}` : ""}
                    </span>
                  ) : null}
                </span>
                <span className="font-data-mono text-[10px] text-text-secondary">
                  {formatShortTime(entry.timestamp)}
                </span>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="py-3 font-body-sm text-text-secondary">{text.ledgerEmptyDesc}</p>
      )}
    </section>
  );
}

function formatShortTime(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    return value;
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

function RunHistory({
  runs,
  locale,
  text,
}: {
  runs: Array<{
    id: string;
    source?: string;
    summary?: {
      final_equity?: number;
      trade_count?: number;
      risk_breach_count?: number;
      execution_status?: string;
      execution_note?: string;
    };
  }>;
  locale: "en" | "zh";
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  const statusColumn = "status" in text.runColumns ? text.runColumns.status : "Status";

  return (
    <Card padded>
      <SectionTitle title={text.runHistoryTitle} hint={text.runHistoryDesc} />
      {runs.length ? (
        <>
        <div
          aria-label={text.runHistoryTitle}
          className="overflow-auto"
          role="region"
          tabIndex={0}
        >
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-border-subtle">
                <th className="pb-2 pr-3 font-label-caps text-text-secondary">{text.runColumns.id}</th>
                <th className="pb-2 pr-3 font-label-caps text-text-secondary">{text.runColumns.source}</th>
                <th className="pb-2 pr-3 font-label-caps text-text-secondary">{statusColumn}</th>
                <th className="pb-2 pr-3 text-right font-label-caps text-text-secondary">{text.runColumns.final_equity}</th>
                <th className="pb-2 pr-3 text-right font-label-caps text-text-secondary">{text.runColumns.trade_count}</th>
                <th className="pb-2 pr-3 text-right font-label-caps text-text-secondary">{text.runColumns.risk_breach_count}</th>
                <th className="pb-2 font-label-caps text-text-secondary"></th>
              </tr>
            </thead>
            <tbody className="font-data-mono text-xs text-text-primary">
              {runs.slice(0, 8).map((run) => (
                <tr className="border-b border-border-subtle/40" key={run.id}>
                  <td className="max-w-64 truncate py-2 pr-3" title={run.id}>
                    {run.id}
                  </td>
                  <td className="py-2 pr-3">{run.source ? <DataSourceBadge source={run.source} /> : "--"}</td>
                  <td className="py-2 pr-3">
                    <ReplayStatusPill
                      status={run.summary?.execution_status}
                      note={run.summary?.execution_note}
                    />
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">{formatMoney(run.summary?.final_equity)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{run.summary?.trade_count ?? "--"}</td>
                  <td className={`py-2 pr-3 text-right tabular-nums ${(run.summary?.risk_breach_count ?? 0) > 0 ? "text-danger" : ""}`}>
                    {run.summary?.risk_breach_count ?? "--"}
                  </td>
                  <td className="py-2 text-right">
                    <Link
                      className="text-info underline-offset-2 hover:underline"
                      href={localizePath(`/paper-trading/${run.id}`, locale)}
                    >
                      {text.openRun}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <TableScrollHint label={tableScrollHintText[locale]} />
        </>
      ) : (
        <p className="py-4 text-center font-body-sm text-text-secondary">{text.runHistoryEmptyDesc}</p>
      )}
    </Card>
  );
}

function ReplayStatusPill({
  status,
  note,
}: {
  status?: string;
  note?: string;
}) {
  const normalized = status ?? "unknown";
  const tone =
    normalized === "filled"
      ? "success"
      : normalized === "blocked"
        ? "danger"
        : normalized === "no_orders" || normalized === "unfilled"
          ? "warning"
          : "neutral";

  return (
    <span title={note}>
      <StatusPill label="" value={normalized} tone={tone} />
    </span>
  );
}
