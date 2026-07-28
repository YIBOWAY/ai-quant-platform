import Link from "next/link";
import { Activity, ArrowRight, BriefcaseBusiness, ShieldAlert, Wallet } from "lucide-react";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { SyntheticMetricsWarning } from "@/components/DataSourceBadge";
import { ErrorBanner } from "@/components/ErrorBanner";
import { AccountTradePanel } from "@/components/forms/AccountTradePanel";
import { PaperRunForm } from "@/components/forms/PaperRunForm";
import { PaperStrategyOpsPanel } from "@/components/forms/PaperStrategyOpsPanel";
import { PaperStrategySleevesPanel } from "@/components/forms/PaperStrategySleevesPanel";
import { PendingOrderCancelButton } from "@/components/forms/PendingOrderCancelButton";
import { Tabs } from "@/components/ui/Tabs";
import { Card, MetricStat, PageHeader, SectionTitle, StatusPill } from "@/components/ui/primitives";
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

const copy = {
  en: {
    pageEyebrow: "Paper trading",
    pageTitle: "Paper Trading",
    pageSubtitle:
      "Live account: manual orders, Strategy Sleeves, and advanced full-account controls. Historical replay stays separate and never touches the account.",
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
    accountTitle: "Paper Account",
    accountDesc:
      "One persistent account with manual cash, Strategy Sleeves allocations, and advanced full-account controls reconciled here.",
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
    pendingOrdersDesc: "Manual limit orders waiting for a later price check.",
    pendingOrdersEmpty: "No pending limit orders.",
    pendingOrdersUnavailable: "Pending limit orders unavailable while the account API is unreachable.",
    limit: "limit",
    lastCheck: "last check",
    sharesUnit: "sh",
    invested: "Invested",
    priceSource: "Prices",
    marketValue: "Market Value",
    avgCost: "Avg Cost",
    lastPrice: "Last",
    sourceMix: "Source Mix",
    weight: "weight",
    pnl: "P&L",
    tradeActions: "Manual & Advanced Actions",
    ledgerTitle: "Ledger Activity",
    ledgerDesc: "Latest ledger entries from orders, rebalances and system events.",
    ledgerEmptyTitle: "No activity yet",
    ledgerEmptyDesc: "Manual orders and rebalances will appear here.",
    ledgerUnavailable: "Ledger unavailable while the account API is unreachable.",
    viewOnMap: "View on position map",
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
      "实时账户：手动下单、策略袖珍仓和高级全账户控制。历史回放保持隔离，不触碰账户。",
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
    accountTitle: "模拟账户",
    accountDesc: "单一持续账户，手动现金、策略袖珍仓划拨和高级全账户控制都会在这里对账。",
    accountUnavailable: "账户接口不可达——在后端恢复前隐藏数值，避免误读。",
    accountValue: "账户净值",
    accountCash: "可用现金",
    accountPnl: "总盈亏",
    openMap: "打开持仓地图",
    replayTitle: "历史回放（研究）",
    replayDesc:
      "对一段历史日期区间批量回放某个策略。它不会触及上面的账户——本质是穿着交易台外衣的研究回测。",
    tabLive: "实时账户",
    tabReplay: "历史回放",
    researchOnly: "仅研究",
    holdings: "持仓",
    holdingsEmpty: "暂无持仓。手动下单或按策略再平衡即可建立持仓。",
    holdingsUnavailable: "账户接口不可达，暂不展示持仓，避免把离线误判为空仓。",
    pendingOrders: "待处理限价单",
    pendingOrdersDesc: "等待后续价格检查的手动限价单。",
    pendingOrdersEmpty: "暂无待处理限价单。",
    pendingOrdersUnavailable: "账户接口不可达，暂不展示待处理限价单。",
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
    viewOnMap: "在持仓地图查看",
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
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
      <div className="space-y-6">
        <AccountSummary
          account={account}
          accountDown={accountDown}
          locale={locale}
          positive={accountPnlPositive}
          text={text}
        />
        <PaperStrategyOpsPanel accountDown={accountDown} locale={locale} />
        <PaperStrategySleevesPanel
          accountAvailableCash={resolvePaperAccountAvailableCash(account)}
          accountDown={accountDown}
          configs={strategyConfigs.configs}
          locale={locale}
          sleeveDetails={sleeveDetails}
          sleeves={strategySleeves.sleeves}
          strategies={strategies.strategies}
        />
        <div className="grid grid-cols-1 gap-6 2xl:grid-cols-2">
          <HoldingsPanel
            account={account}
            accountDown={accountDown}
            locale={locale}
            text={text}
          />
          <PendingOrdersPanel
            account={account}
            accountDown={accountDown}
            locale={locale}
            text={text}
          />
        </div>
        <LedgerPanel
          entries={ledger.entries}
          ledgerDown={ledgerDown}
          locale={locale}
          text={text}
        />
      </div>
      <Card padded className="h-fit xl:sticky xl:top-0">
        <h2 className="mb-3 flex items-center gap-2 font-label-caps text-text-primary">
          <Activity className="text-accent-success" size={16} /> {text.tradeActions}
        </h2>
        <AccountTradePanel
          locale={locale}
          killSwitch={account.kill_switch}
          pendingOrderCount={(account.pending_orders ?? []).length}
          strategies={strategies.strategies}
        />
        <SafetyFlags account={account} health={health} text={text} />
      </Card>
    </div>
  );

  const replayTab = (
    <div className="space-y-6">
      <Card tone="info" padded>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-headline-lg text-text-primary">{text.historyResultsTitle}</h2>
            <p className="mt-1 font-body-sm text-text-secondary">{text.historyResultsDesc}</p>
          </div>
          <StatusPill label="" value={text.researchOnly} tone="info" />
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[360px_1fr]">
        <Card padded className="h-fit">
          <h3 className="font-label-caps text-text-secondary">{text.replayTitle}</h3>
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
          <SyntheticMetricsWarning source={latestRun?.source} locale={locale} />
          {hiddenSampleCount > 0 ? (
            <p className="font-body-sm text-text-secondary">
              {text.hiddenSampleRuns(hiddenSampleCount)}{" "}
              <Link className="text-info underline underline-offset-2" href="?include_sample=1">
                {text.showSample}
              </Link>
            </p>
          ) : null}
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

          <Card padded>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-label-caps text-text-secondary">{text.latestRun}</span>
              <div className="flex items-center gap-2">
                {latestRun?.source ? <DataSourceBadge source={latestRun.source} /> : null}
                {latestRun ? (
                  <Link
                    aria-label={text.openAria(latestRun.id)}
                    className="rounded-lg border border-border-subtle px-3 py-1.5 font-body-sm text-info"
                    href={localizePath(`/paper-trading/${latestRun.id}`, locale)}
                  >
                    {text.openRun}
                  </Link>
                ) : null}
              </div>
            </div>
            <div className="mt-1 truncate font-data-mono text-sm text-text-primary">
              {latestRun?.id ?? text.noPaperRun}
            </div>
          </Card>

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
      />
      <Tabs
        items={[
          { id: "live", label: <span className="flex items-center gap-2"><Wallet size={15} />{text.tabLive}</span>, content: liveTab },
          { id: "replay", label: <span className="flex items-center gap-2"><Activity size={15} />{text.tabReplay}</span>, content: replayTab },
        ]}
      />
    </div>
  );
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
        <div className="overflow-auto">
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

function LedgerPanel({
  entries,
  ledgerDown,
  locale,
  text,
}: {
  entries: LedgerEntryView[];
  ledgerDown: boolean;
  locale: "en" | "zh";
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  return (
    <Card padded>
      <SectionTitle
        title={text.ledgerTitle}
        hint={text.ledgerDesc}
        right={
          <Link
            className="flex shrink-0 items-center gap-1 font-body-sm text-info underline-offset-2 hover:underline"
            href={localizePath("/position-map", locale)}
          >
            {text.viewOnMap}
            <ArrowRight size={13} />
          </Link>
        }
      />
      {ledgerDown ? (
        <p className="py-4 text-center font-body-sm text-text-secondary">{text.ledgerUnavailable}</p>
      ) : entries.length ? (
        <ol className="space-y-1.5">
          {entries.map((entry) => {
            const isStrategy = entry.source.startsWith("strategy:");
            const kindLabel = text.kind[entry.kind] ?? entry.kind;
            const sideLabel = entry.side ? (text.side[entry.side.toUpperCase()] ?? entry.side) : "";
            const isSell = entry.side?.toUpperCase() === "SELL";
            return (
              <li
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border-subtle bg-bg-surface-muted/40 px-3 py-1.5"
                key={entry.entry_id}
              >
                <span className="flex items-center gap-2 font-data-mono text-xs">
                  <span className="font-label-caps text-text-secondary">{kindLabel}</span>
                  {entry.source !== "system" ? (
                    <span
                      className={`rounded-lg border px-1.5 py-0.5 text-[10px] uppercase ${
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
        <p className="py-4 text-center font-body-sm text-text-secondary">{text.ledgerEmptyDesc}</p>
      )}
    </Card>
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

function HoldingsPanel({
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
  const positions = [...account.positions].sort((a, b) => b.market_value - a.market_value);
  return (
    <Card padded>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-label-caps text-text-primary">{text.holdings}</h2>
        <span className="font-data-mono text-[10px] uppercase text-text-secondary">
          {text.priceSource}: {accountDown ? text.unknown : account.price_source.kind}
        </span>
      </div>
      {accountDown ? (
        <p className="py-6 text-center font-body-sm text-text-secondary">{text.holdingsUnavailable}</p>
      ) : positions.length === 0 ? (
        <p className="py-6 text-center font-body-sm text-text-secondary">{text.holdingsEmpty}</p>
      ) : (
        <div className="space-y-2">
          {positions.map((p) => (
            <HoldingRow key={p.symbol} position={p} locale={locale} text={text} />
          ))}
        </div>
      )}
    </Card>
  );
}

function PendingOrdersPanel({
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
    <Card padded>
      <SectionTitle title={text.pendingOrders} hint={text.pendingOrdersDesc} />
      {accountDown ? (
        <p className="py-4 text-center font-body-sm text-text-secondary">
          {text.pendingOrdersUnavailable}
        </p>
      ) : pending.length === 0 ? (
        <p className="py-4 text-center font-body-sm text-text-secondary">
          {text.pendingOrdersEmpty}
        </p>
      ) : (
        <div className="space-y-2">
          {pending.map((order) => (
            <PendingOrderRow
              key={order.order_id}
              locale={locale}
              order={order}
              text={text}
            />
          ))}
        </div>
      )}
    </Card>
  );
}

function PendingOrderRow({
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
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border-subtle bg-bg-surface-muted/40 p-3">
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex items-center gap-2">
          <span
            className={`font-data-mono text-sm font-bold ${
              isBuy ? "text-accent-success" : "text-danger"
            }`}
          >
            {sideLabel} {order.symbol}
          </span>
          <span className="rounded-lg border border-info/40 bg-info/10 px-1.5 py-0.5 font-data-mono text-[10px] uppercase text-info">
            {text.kind.order_pending}
          </span>
        </div>
        <span className="font-data-mono text-xs text-text-secondary">
          {order.quantity.toLocaleString(undefined, { maximumFractionDigits: 2 })}{" "}
          {text.sharesUnit} ·{" "}
          {text.limit} {order.limit_price.toFixed(2)}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <div className="text-right font-data-mono text-[10px] text-text-secondary">
          <div>{text.lastCheck}</div>
          <div>{lastChecked}</div>
        </div>
        <PendingOrderCancelButton locale={locale} orderId={order.order_id} />
      </div>
    </div>
  );
}

function HoldingRow({
  position,
  text,
}: {
  position: AccountPositionView;
  locale: "en" | "zh";
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  const pnlPositive = position.unrealized_pnl >= 0;
  const isLong = position.quantity >= 0;
  const weightPct = Math.max(0, Math.min(1, Math.abs(position.weight))) * 100;
  const barWidthPct = Math.max(weightPct, 2);
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

  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface p-3">
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-data-mono text-base font-bold text-text-primary">{position.symbol}</span>
            <span className={`font-label-caps ${isLong ? "text-text-secondary" : "text-danger"}`}>
              {position.quantity.toLocaleString(undefined, { maximumFractionDigits: 2 })} {text.sharesUnit}
            </span>
            <span
              className={`shrink-0 rounded-full border px-2 py-0.5 font-data-mono text-[10px] uppercase ${
                manualShare >= 0.999
                  ? "border-info/40 bg-info/10 text-info"
                  : "border-accent-success/40 bg-accent-success/10 text-accent-success"
              }`}
              title={sourceLabel}
            >
              {sourceLabel}
            </span>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 font-data-mono text-xs sm:grid-cols-3">
            <span className="text-text-secondary">
              {text.avgCost} <span className="text-text-primary">{position.avg_cost.toFixed(2)}</span>
            </span>
            <span className="text-text-secondary">
              {text.lastPrice} <span className="text-text-primary">{position.last_price.toFixed(2)}</span>
            </span>
            <span className="text-text-secondary">
              {text.weight} <span className="text-text-primary">{weightPct.toFixed(1)}%</span>
            </span>
          </div>
        </div>
        <div className="shrink-0 text-left md:text-right">
          <div className="font-label-caps text-text-secondary">{text.marketValue}</div>
          <div className="font-data-mono text-sm font-bold text-text-primary">
            {formatMoney(position.market_value)}
          </div>
          <div className={`font-data-mono text-xs ${pnlPositive ? "text-accent-success" : "text-danger"}`}>
            {text.pnl} {pnlPositive ? "+" : ""}{formatMoney(position.unrealized_pnl)}
          </div>
        </div>
      </div>

      <div className="mt-3 space-y-1">
        <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-bg-surface-muted" title={sourceLabel}>
          <div className="flex h-full" style={{ width: `${barWidthPct}%` }}>
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
        <div className="flex flex-wrap items-center justify-between gap-2 font-label-caps text-[10px] text-text-secondary">
          <span>{text.sourceMix}</span>
          <span>{text.strategy} {(strategyShare * 100).toFixed(0)}% · {text.manual} {(manualShare * 100).toFixed(0)}%</span>
        </div>
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
    <div className="mt-4 border-t border-border-subtle pt-4">
      <div className="mb-2 flex items-center gap-2 text-text-secondary">
        <ShieldAlert size={14} />
        <span className="font-label-caps">{text.riskCenter}</span>
      </div>
      <div className="flex flex-wrap gap-2">
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
    </div>
  );
}

function AccountSummary({
  account,
  accountDown,
  locale,
  positive,
  text,
}: {
  account: Awaited<ReturnType<typeof getPaperAccount>>;
  accountDown: boolean;
  locale: "en" | "zh";
  positive: boolean;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  return (
    <Card tone="success" padded>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 font-headline-lg text-text-primary">
            <Wallet className="text-accent-success" size={18} /> {text.accountTitle}
          </h2>
          <p className="mt-1 font-body-sm text-text-secondary">
            {accountDown ? text.accountUnavailable : text.accountDesc}
          </p>
        </div>
        <Link
          className="rounded-lg border border-border-subtle px-3 py-1.5 font-body-sm text-text-primary transition-colors hover:bg-bg-surface-muted"
          href={localizePath("/position-map", locale)}
        >
          {text.openMap}
        </Link>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricStat label={text.accountValue} value={accountDown ? "--" : formatMoney(account.equity)} />
        <MetricStat
          label={text.accountPnl}
          value={accountDown ? "--" : `${positive ? "+" : ""}${formatMoney(account.pnl_abs)}`}
          delta={accountDown ? undefined : `${(account.pnl_pct * 100).toFixed(2)}%`}
          tone={accountDown ? "neutral" : positive ? "success" : "danger"}
        />
        <MetricStat label={text.accountCash} value={accountDown ? "--" : formatMoney(account.available_cash)} />
        <MetricStat
          label={text.invested}
          value={accountDown ? "--" : `${(account.invested_pct * 100).toFixed(1)}%`}
        />
      </div>
    </Card>
  );
}
