import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import {
  Bot,
  Database,
  FlaskConical,
  LineChart,
  Play,
  Settings,
  Wallet,
} from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import {
  formatMoney,
  formatPercent,
  getAgentCandidates,
  getBacktests,
  getFactors,
  getHealth,
  getPaperRuns,
  getSymbols,
} from "@/lib/api";

function KpiCard({
  title,
  value,
  detail,
  icon: Icon,
}: {
  title: string;
  value: string | number;
  detail: string;
  icon: LucideIcon;
}) {
  return (
    <div className="flex h-28 flex-col justify-between rounded border border-border-subtle bg-bg-surface p-4">
      <div className="flex items-start justify-between">
        <h3 className="font-label-caps uppercase text-text-secondary">{title}</h3>
        <Icon size={14} className="text-primary" />
      </div>
      <div>
        <div className="font-data-mono text-headline-xl text-text-primary">{value}</div>
        <div className="font-data-mono text-[10px] text-text-secondary">{detail}</div>
      </div>
    </div>
  );
}

export default async function Dashboard() {
  const [health, symbols, factors, backtests, paperRuns, candidates] = await Promise.all([
    getHealth(),
    getSymbols(),
    getFactors(),
    getBacktests(),
    getPaperRuns(),
    getAgentCandidates(),
  ]);
  const latestBacktest = backtests.backtests[0];
  const latestPaper = paperRuns.paper_runs[0];
  const paperSummary = latestPaper?.summary;

  return (
    <div className="flex h-full flex-col overflow-hidden xl:flex-row">
      <div className="flex-1 space-y-6 overflow-y-auto p-gutter lg:p-container-padding">
        <ErrorBanner
          messages={[
            health.apiError,
            symbols.apiError,
            factors.apiError,
            backtests.apiError,
            paperRuns.apiError,
            candidates.apiError,
          ]}
        />
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            title="Registered Factors"
            value={factors.factors.length}
            detail="from /api/factors"
            icon={FlaskConical}
          />
          <KpiCard
            title="Paper Equity"
            value={formatMoney(paperSummary?.final_equity)}
            detail={`${paperRuns.paper_runs.length} paper runs`}
            icon={Wallet}
          />
          <KpiCard
            title="Agent Candidates"
            value={candidates.candidates.length}
            detail="candidate pool entries"
            icon={Bot}
          />
          <KpiCard
            title="Latest Sharpe"
            value={latestBacktest?.metrics?.sharpe?.toFixed(2) ?? "--"}
            detail={`max drawdown ${formatPercent(latestBacktest?.metrics?.max_drawdown)}`}
            icon={LineChart}
          />
        </section>

        <section className="space-y-4">
          <div className="flex items-center justify-between border-b border-border-subtle pb-2">
            <h2 className="font-headline-lg text-text-primary">Recent Operations</h2>
            <span className="font-label-caps text-text-secondary">local API snapshot</span>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded border border-border-subtle bg-bg-surface p-4">
              <div className="mb-4 flex items-center gap-2 font-label-caps text-text-secondary">
                <LineChart size={14} className="text-info" /> Backtest
              </div>
              <h3 className="truncate font-body-md font-medium text-text-primary">
                {latestBacktest?.id ?? "No backtest run yet"}
              </h3>
              <div className="mt-4 space-y-2 font-data-mono text-xs">
                <div className="flex justify-between">
                  <span className="text-text-secondary">Return</span>
                  <span className="text-text-primary">
                    {formatPercent(latestBacktest?.metrics?.total_return)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">Max DD</span>
                  <span className="text-text-primary">
                    {formatPercent(latestBacktest?.metrics?.max_drawdown)}
                  </span>
                </div>
              </div>
            </div>

            <div className="rounded border border-border-subtle bg-bg-surface p-4">
              <div className="mb-4 flex items-center gap-2 font-label-caps text-text-secondary">
                <Database size={14} className="text-warning" /> Symbols
              </div>
              <h3 className="truncate font-body-md font-medium text-text-primary">
                {symbols.symbols.join(", ")}
              </h3>
              <p className="mt-4 font-data-mono text-xs text-text-secondary">
                source={symbols.source}; status={health.status}
              </p>
            </div>

            <div className="rounded border border-border-subtle bg-bg-surface p-4">
              <div className="mb-4 flex items-center gap-2 font-label-caps text-text-secondary">
                <Wallet size={14} className="text-primary" /> Paper Run
              </div>
              <h3 className="truncate font-body-md font-medium text-text-primary">
                {latestPaper?.id ?? "No paper run yet"}
              </h3>
              <div className="mt-4 space-y-2 font-data-mono text-xs">
                <div className="flex justify-between">
                  <span className="text-text-secondary">Orders</span>
                  <span className="text-text-primary">{paperSummary?.order_count ?? 0}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">Breaches</span>
                  <span className="text-text-primary">{paperSummary?.risk_breach_count ?? 0}</span>
                </div>
              </div>
            </div>

            <div className="rounded border border-border-subtle bg-bg-surface p-4">
              <div className="mb-4 flex items-center gap-2 font-label-caps text-text-secondary">
                <Bot size={14} className="text-info" /> Agent Pool
              </div>
              <h3 className="truncate font-body-md font-medium text-text-primary">
                {candidates.candidates[0]?.candidate_id ?? "No candidate yet"}
              </h3>
              <p className="mt-4 font-data-mono text-xs text-text-secondary">
                {candidates.candidates.length} candidates require manual review.
              </p>
            </div>
          </div>
        </section>

        <EmptyState
          title="Audit log not implemented yet"
          description="audit log not implemented yet — see /docs/FIX_PLAN.md P2-5"
        />
      </div>

      <aside className="flex w-full flex-shrink-0 flex-col gap-6 overflow-y-auto border-l border-border-subtle bg-bg-surface p-6 xl:w-[320px]">
        <div>
          <h3 className="mb-4 border-b border-border-subtle pb-2 font-label-caps text-text-secondary">
            QUICK ACTIONS
          </h3>
          <div className="space-y-3">
            <Link
              href="/backtest"
              className="flex w-full items-center gap-3 rounded border border-border-subtle bg-bg-surface-muted px-4 py-2 text-left font-body-sm text-text-primary transition-colors hover:border-primary"
            >
              <Play size={14} className="text-primary" /> Start New Backtest
            </Link>
            <Link
              href="/factor-lab"
              className="flex w-full items-center gap-3 rounded border border-border-subtle bg-bg-surface-muted px-4 py-2 text-left font-body-sm text-text-primary transition-colors hover:border-warning"
            >
              <FlaskConical size={14} className="text-warning" /> Run Factor Analysis
            </Link>
            <Link
              href="/agent-studio"
              className="flex w-full items-center gap-3 rounded border border-border-subtle bg-bg-surface-muted px-4 py-2 text-left font-body-sm text-text-primary transition-colors hover:border-info"
            >
              <Bot size={14} className="text-info" /> New Agent Task
            </Link>
            <Link
              href="/settings"
              className="flex w-full items-center gap-3 rounded border border-border-subtle bg-bg-surface-muted px-4 py-2 text-left font-body-sm text-text-primary transition-colors hover:border-text-primary"
            >
              <Settings size={14} className="text-text-secondary" /> Open Settings
            </Link>
          </div>
        </div>

        <div>
          <h3 className="mb-4 border-b border-border-subtle pb-2 font-label-caps text-text-secondary">
            ENVIRONMENT STATE
          </h3>
          <div className="space-y-3 font-body-sm">
            <div className="flex justify-between">
              <span className="text-text-secondary">API</span>
              <span className="font-data-mono text-text-primary">{health.status}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-secondary">paper trading</span>
              <span className="font-data-mono text-text-primary">
                {String(health.safety?.paper_trading)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-secondary">live trading</span>
              <span className="font-data-mono text-text-primary">
                {String(health.safety?.live_trading_enabled)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-secondary">kill switch</span>
              <span className="font-data-mono text-warning">
                {health.safety?.kill_switch ? "on" : "off"}
              </span>
            </div>
          </div>
        </div>

        <EmptyState
          title="System telemetry unavailable"
          description="CPU and memory telemetry are not part of the current local API."
        />
      </aside>
    </div>
  );
}
