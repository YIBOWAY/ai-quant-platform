import Link from "next/link";
import { Activity, AlertCircle, BriefcaseBusiness, ShieldAlert } from "lucide-react";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { PaperRunForm } from "@/components/forms/PaperRunForm";
import { formatMoney, getHealth, getPaperRunDetail, getPaperRuns } from "@/lib/api";
import { selectDisplayRun, shouldIncludeSampleRuns } from "@/lib/runSource";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    finalEquity: "Final Equity",
    orders: "Orders",
    riskBreaches: "Risk Breaches",
    trades: "Trades",
    paperRunStatus: "Paper Run Status",
    latestRun: "latest run",
    noPaperRun: "No paper run yet",
    openAria: (id: string) => `Open ${id}`,
    openRun: "Open run",
    killSwitch: "kill switch",
    on: "on",
    off: "off",
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
    riskCenter: "Risk Center",
    localBatchNote: "Runs are local batch simulations only.",
  },
  zh: {
    finalEquity: "最终权益",
    orders: "订单",
    riskBreaches: "风控触发",
    trades: "成交",
    paperRunStatus: "模拟运行状态",
    latestRun: "最新运行",
    noPaperRun: "暂无模拟运行",
    openAria: (id: string) => `打开 ${id}`,
    openRun: "打开运行",
    killSwitch: "终止开关",
    on: "开",
    off: "关",
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
    riskCenter: "风控中心",
    localBatchNote: "运行仅为本地批量模拟。",
  },
} as const;

type PaperTradingProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function PaperTrading({ searchParams }: PaperTradingProps) {
  const params = (await searchParams) ?? {};
  const [health, paperRuns, locale] = await Promise.all([
    getHealth(),
    getPaperRuns(),
    getServerLocale(params),
  ]);
  const text = copy[locale];
  const latestRun = selectDisplayRun(paperRuns.paper_runs, shouldIncludeSampleRuns(params));
  const detail = latestRun ? await getPaperRunDetail(latestRun.id) : null;
  const latest = latestRun?.summary;

  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden bg-base xl:flex-row">
      <div className="flex-1 space-y-6 overflow-y-auto p-4 lg:p-6">
        <ErrorBanner messages={[health.apiError, paperRuns.apiError, detail?.apiError]} />
        <section className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div className="rounded border border-border-subtle bg-surface p-4">
            <h3 className="mb-2 font-label-caps uppercase text-text-secondary">{text.finalEquity}</h3>
            <div className="font-data-mono text-headline-xl text-primary">
              {formatMoney(latest?.final_equity)}
            </div>
          </div>
          <div className="rounded border border-border-subtle bg-surface p-4">
            <h3 className="mb-2 font-label-caps uppercase text-text-secondary">{text.orders}</h3>
            <div className="font-data-mono text-headline-xl text-text-primary">
              {latest?.order_count ?? 0}
            </div>
          </div>
          <div className="rounded border border-danger/30 bg-danger/5 p-4">
            <h3 className="mb-2 flex items-center gap-2 font-label-caps uppercase text-danger">
              <AlertCircle size={14} /> {text.riskBreaches}
            </h3>
            <div className="font-data-mono text-headline-xl text-danger">
              {latest?.risk_breach_count ?? 0}
            </div>
          </div>
          <div className="rounded border border-border-subtle bg-surface p-4">
            <h3 className="mb-2 font-label-caps uppercase text-text-secondary">{text.trades}</h3>
            <div className="font-data-mono text-headline-xl text-text-primary">
              {latest?.trade_count ?? 0}
            </div>
          </div>
        </section>

        <section className="rounded border border-border-subtle bg-surface p-4">
          <h2 className="mb-3 flex items-center gap-2 font-headline-lg text-text-primary">
            <Activity className="text-primary" size={18} /> {text.paperRunStatus}
          </h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="rounded border border-border-subtle bg-surface-dim p-3">
              <div className="font-label-caps text-text-secondary">{text.latestRun}</div>
            <div className="mt-1 truncate font-data-mono text-text-primary">
              {latestRun?.id ?? text.noPaperRun}
            </div>
            {latestRun?.source ? (
              <div className="mt-2">
                <DataSourceBadge source={latestRun.source} />
              </div>
            ) : null}
            {latestRun ? (
              <Link
                aria-label={text.openAria(latestRun.id)}
                className="mt-3 inline-flex rounded border border-border-subtle px-3 py-1.5 font-body-sm text-info"
                href={`/paper-trading/${latestRun.id}`}
              >
                {text.openRun}
              </Link>
            ) : null}
          </div>
            <div className="rounded border border-border-subtle bg-surface-dim p-3">
              <div className="font-label-caps text-text-secondary">{text.killSwitch}</div>
              <div className="mt-1 font-data-mono text-warning">
                {health.safety?.kill_switch ? text.on : text.off}
              </div>
            </div>
          </div>
        </section>

        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <DataPreviewTable
            title={text.tradesTitle}
            description={text.tradesDesc}
            rows={detail?.trades ?? []}
            emptyTitle={text.tradesEmptyTitle}
            emptyDescription={text.tradesEmptyDesc}
          />
          <DataPreviewTable
            title={text.orderLifecycleTitle}
            description={text.orderLifecycleDesc}
            rows={detail?.order_events ?? []}
            emptyTitle={text.orderLifecycleEmptyTitle}
            emptyDescription={text.orderLifecycleEmptyDesc}
          />
          <div className="lg:col-span-2">
            <DataPreviewTable
              title={text.riskBreachesTitle}
              description={text.riskBreachesDesc}
              rows={detail?.risk_breaches ?? []}
              emptyTitle={text.riskBreachesEmptyTitle}
              emptyDescription={text.riskBreachesEmptyDesc}
            />
          </div>
        </section>
      </div>

      <aside className="relative flex w-full flex-shrink-0 flex-col overflow-hidden border-l border-border-subtle bg-bg-surface p-6 xl:w-[320px]">
        <div className="mb-6 flex items-center gap-2 border-b border-danger/20 pb-4 text-danger">
          <ShieldAlert size={20} />
          <h2 className="font-headline-lg uppercase tracking-wider">{text.riskCenter}</h2>
        </div>
        <div className="space-y-3 font-body-sm">
          <div className="flex justify-between">
            <span className="text-text-secondary">paper_trading</span>
            <span className="font-data-mono text-text-primary">
              {String(health.safety?.paper_trading)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-secondary">live_trading_enabled</span>
            <span className="font-data-mono text-text-primary">
              {String(health.safety?.live_trading_enabled)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-secondary">kill_switch</span>
            <span className="font-data-mono text-warning">
              {String(health.safety?.kill_switch)}
            </span>
          </div>
        </div>
        <div className="mt-6">
          <PaperRunForm locale={locale} />
          <div className="mt-4 flex items-center gap-2 font-body-sm text-text-secondary">
            <BriefcaseBusiness size={18} /> {text.localBatchNote}
          </div>
        </div>
      </aside>
    </div>
  );
}
