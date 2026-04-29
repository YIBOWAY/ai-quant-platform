import { Activity, AlertCircle, ShieldAlert, Wallet } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { PaperRunForm } from "@/components/forms/PaperRunForm";
import { formatMoney, getHealth, getPaperRuns } from "@/lib/api";

export default async function PaperTrading() {
  const [health, paperRuns] = await Promise.all([getHealth(), getPaperRuns()]);
  const latestRun = paperRuns.paper_runs[0];
  const latest = latestRun?.summary;

  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden bg-base xl:flex-row">
      <div className="flex-1 space-y-6 overflow-y-auto p-4 lg:p-6">
        <section className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div className="rounded border border-border-subtle bg-surface p-4">
            <h3 className="mb-2 font-label-caps uppercase text-text-secondary">Final Equity</h3>
            <div className="font-data-mono text-headline-xl text-primary">
              {formatMoney(latest?.final_equity)}
            </div>
          </div>
          <div className="rounded border border-border-subtle bg-surface p-4">
            <h3 className="mb-2 font-label-caps uppercase text-text-secondary">Orders</h3>
            <div className="font-data-mono text-headline-xl text-text-primary">
              {latest?.order_count ?? 0}
            </div>
          </div>
          <div className="rounded border border-danger/30 bg-danger/5 p-4">
            <h3 className="mb-2 flex items-center gap-2 font-label-caps uppercase text-danger">
              <AlertCircle size={14} /> Risk Breaches
            </h3>
            <div className="font-data-mono text-headline-xl text-danger">
              {latest?.risk_breach_count ?? 0}
            </div>
          </div>
          <div className="rounded border border-border-subtle bg-surface p-4">
            <h3 className="mb-2 font-label-caps uppercase text-text-secondary">Trades</h3>
            <div className="font-data-mono text-headline-xl text-text-primary">
              {latest?.trade_count ?? 0}
            </div>
          </div>
        </section>

        <section className="rounded border border-border-subtle bg-surface p-4">
          <h2 className="mb-3 flex items-center gap-2 font-headline-lg text-text-primary">
            <Activity className="text-primary" size={18} /> Paper Run Status
          </h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="rounded border border-border-subtle bg-surface-dim p-3">
              <div className="font-label-caps text-text-secondary">latest run</div>
              <div className="mt-1 truncate font-data-mono text-text-primary">
                {latestRun?.id ?? "No paper run yet"}
              </div>
            </div>
            <div className="rounded border border-border-subtle bg-surface-dim p-3">
              <div className="font-label-caps text-text-secondary">kill switch</div>
              <div className="mt-1 font-data-mono text-warning">
                {health.safety?.kill_switch ? "on" : "off"}
              </div>
            </div>
          </div>
        </section>

        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <EmptyState
            title="Equity curve not selected"
            description="Run or open a paper trading result to display the real equity curve."
          />
          <EmptyState
            title="Order lifecycle table pending"
            description="Order and fill details will be rendered from /api/paper/{id}."
          />
        </section>
      </div>

      <aside className="relative flex w-full flex-shrink-0 flex-col overflow-hidden border-l border-border-subtle bg-bg-surface p-6 xl:w-[320px]">
        <div className="mb-6 flex items-center gap-2 border-b border-danger/20 pb-4 text-danger">
          <ShieldAlert size={20} />
          <h2 className="font-headline-lg uppercase tracking-wider">Risk Center</h2>
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
          <PaperRunForm />
          <div className="mt-4 flex items-center gap-2 font-body-sm text-text-secondary">
            <Wallet size={18} /> Runs are local batch simulations only.
          </div>
        </div>
      </aside>
    </div>
  );
}
