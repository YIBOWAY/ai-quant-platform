'use client';

import { useMemo, useState } from "react";
import {
  Activity,
  BarChart3,
  Calculator,
  Gauge,
  LineChart,
  ListChecks,
  Play,
  SlidersHorizontal,
} from "lucide-react";
import { ApiClientError, apiPost, apiRequest } from "@/lib/apiClient";

type TabId = "greeks" | "strategy" | "score" | "simulate" | "surface" | "smile";

type GreeksResult = {
  price: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  rho: number;
  charm: number;
  vanna: number;
  volga: number;
};

type StrategyRank = {
  template_id: string;
  strategy: string;
  score: number;
  net_debit?: number | null;
  max_profit?: number | null;
  max_loss?: number | null;
  rating: string;
};

type StrategyRankResult = {
  market_view: string;
  rankings: StrategyRank[];
  assumptions?: string[];
};

type ContractRank = {
  symbol: string;
  option_type: string;
  strike?: number | null;
  mid?: number | null;
  spread_pct?: number | null;
  implied_volatility?: number | null;
  delta?: number | null;
  score: number;
  rating: string;
  warnings?: string[];
};

type ScoreContractsResult = {
  objective: string;
  ranked_contracts: ContractRank[];
  assumptions?: string[];
};

type SimulationResult = {
  ticker: string;
  price: number;
  max_profit?: number | null;
  max_loss?: number | null;
  breakevens: number[];
  pnl_at_expiry: {
    price_axis: number[];
    pnl_axis: number[];
  };
  assumptions?: string[];
};

type SurfaceResult = {
  ticker: string;
  price: number;
  shape: string;
  surface: {
    moneyness_axis: number[];
    expiry_axis: string[];
    iv_grid: Array<Array<number | null>>;
  };
};

type SmileResult = {
  ticker: string;
  price: number;
  expiry: string;
  shape: string;
  skew_metrics: {
    skew_25d?: number | null;
    atm_iv?: number | null;
  };
  smile: {
    strikes: Array<number | null>;
    ivs: Array<number | null>;
    option_types: string[];
  };
};

const tabs: Array<{ id: TabId; label: string; icon: typeof Calculator; live: boolean }> = [
  { id: "greeks", label: "Greeks", icon: Calculator, live: false },
  { id: "strategy", label: "Strategy Rank", icon: ListChecks, live: false },
  { id: "score", label: "Score Contracts", icon: Gauge, live: false },
  { id: "simulate", label: "Simulator", icon: LineChart, live: false },
  { id: "surface", label: "Vol Surface", icon: BarChart3, live: true },
  { id: "smile", label: "Vol Smile", icon: Activity, live: true },
];

const sampleContracts = [
  {
    symbol: "AAPL_PUT_95",
    option_type: "PUT",
    strike: 95,
    bid: 1.1,
    ask: 1.2,
    volume: 600,
    open_interest: 1200,
    implied_volatility: 0.5,
    delta: -0.24,
  },
  {
    symbol: "AAPL_CALL_105",
    option_type: "CALL",
    strike: 105,
    bid: 1.4,
    ask: 1.55,
    volume: 380,
    open_interest: 850,
    implied_volatility: 0.36,
    delta: 0.35,
  },
  {
    symbol: "AAPL_PUT_90",
    option_type: "PUT",
    strike: 90,
    bid: 0.72,
    ask: 0.8,
    volume: 280,
    open_interest: 700,
    implied_volatility: 0.46,
    delta: -0.16,
  },
];

export function OptionsToolsWorkbench() {
  const [activeTab, setActiveTab] = useState<TabId>("greeks");
  const [sharedTicker, setSharedTicker] = useState("AAPL");

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <header className="border-b border-border-subtle bg-bg-surface px-6 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="font-label-caps uppercase text-text-secondary">Local AlphaGBM</p>
            <h1 className="mt-1 font-headline-xl text-text-primary">Options Tools</h1>
            <p className="mt-1 max-w-3xl font-body-sm text-text-secondary">
              Read-only option research tools. Live-data tabs require Futu OpenD. Local-calculation tabs work offline.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 font-body-sm text-text-secondary">
              Ticker
              <input
                className="h-9 w-28 rounded border border-border-subtle bg-surface-container px-3 font-data-mono uppercase text-text-primary"
                onChange={(event) => setSharedTicker(event.target.value.toUpperCase())}
                value={sharedTicker}
              />
            </label>
            <div className="rounded border border-border-subtle bg-surface-container px-3 py-2 font-label-caps uppercase text-accent-success">
              Research only
            </div>
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="w-[260px] shrink-0 overflow-y-auto border-r border-border-subtle bg-bg-surface p-4">
          <div className="space-y-1" role="tablist" aria-label="Options tools">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const selected = activeTab === tab.id;
              return (
                <button
                  aria-selected={selected}
                  className={`flex w-full items-center gap-2 rounded px-3 py-2 text-left font-body-sm transition-colors ${
                    selected
                      ? "bg-surface-container text-accent-success"
                      : "text-text-secondary hover:bg-surface-container/70 hover:text-text-primary"
                  }`}
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  role="tab"
                  type="button"
                >
                  <Icon size={16} />
                  <span className="flex-1">{tab.label}</span>
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-label-caps ${tab.live ? "bg-info/10 text-info" : "bg-surface-muted text-text-secondary"}`}>
                    {tab.live ? "Live" : "Calc"}
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        <section className="min-w-0 flex-1 overflow-y-auto p-6" role="tabpanel">
          {activeTab === "greeks" ? <GreeksPanel /> : null}
          {activeTab === "strategy" ? <StrategyRankPanel /> : null}
          {activeTab === "score" ? <ScoreContractsPanel /> : null}
          {activeTab === "simulate" ? <SimulationPanel ticker={sharedTicker} /> : null}
          {activeTab === "surface" ? <SurfacePanel ticker={sharedTicker} /> : null}
          {activeTab === "smile" ? <SmilePanel ticker={sharedTicker} /> : null}
        </section>
      </div>
    </div>
  );
}

function GreeksPanel() {
  const [result, setResult] = useState<GreeksResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  async function run() {
    setIsRunning(true);
    setError(null);
    try {
      const payload = await apiPost<GreeksResult>("/api/options/tools/greeks", {
        spot: 100,
        strike: 100,
        expiry_days: 30,
        iv: 0.25,
        option_type: "call",
      });
      setResult(payload);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <ToolPanel
      actionLabel="Calculate Greeks"
      description="Price and sensitivity snapshot for a sample at-the-money call."
      icon={Calculator}
      isRunning={isRunning}
      onRun={run}
      title="Greeks"
    >
      {error ? <ErrorLine message={error} /> : null}
      {result ? (
        <MetricGrid
          items={[
            ["Price", result.price],
            ["Delta", result.delta],
            ["Gamma", result.gamma],
            ["Theta", result.theta],
            ["Vega", result.vega],
            ["Rho", result.rho],
            ["Charm", result.charm],
            ["Vanna", result.vanna],
            ["Volga", result.volga],
          ]}
        />
      ) : (
        <EmptyPrompt label="Run the sample calculation to inspect the Greeks table." />
      )}
    </ToolPanel>
  );
}

function StrategyRankPanel() {
  const [result, setResult] = useState<StrategyRankResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  async function run() {
    setIsRunning(true);
    setError(null);
    try {
      const payload = await apiPost<StrategyRankResult>("/api/options/tools/strategy/rank", {
        market_view: "bullish",
        spot: 100,
        expiry_days: 45,
        strikes: [85, 90, 95, 100, 105, 110, 115],
        iv: 0.25,
        symbol: "AAPL",
      });
      setResult(payload);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <ToolPanel
      actionLabel="Rank Strategies"
      description="Compares bullish strategy templates with the same spot, IV, DTE, and strike set."
      icon={ListChecks}
      isRunning={isRunning}
      onRun={run}
      title="Strategy Rank"
    >
      {error ? <ErrorLine message={error} /> : null}
      {result ? (
        <DataTable
          columns={["Strategy", "Score", "Rating", "Net Debit", "Max Profit", "Max Loss"]}
          rows={result.rankings.map((item) => [
            item.strategy,
            num(item.score, 1),
            item.rating,
            money(item.net_debit),
            money(item.max_profit),
            money(item.max_loss),
          ])}
        />
      ) : (
        <EmptyPrompt label="Run the local ranker to compare strategy templates." />
      )}
    </ToolPanel>
  );
}

function ScoreContractsPanel() {
  const [result, setResult] = useState<ScoreContractsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  async function run() {
    setIsRunning(true);
    setError(null);
    try {
      const payload = await apiPost<ScoreContractsResult>("/api/options/tools/score-contracts", {
        spot: 100,
        objective: "sell_premium",
        top_n: 5,
        contracts: sampleContracts,
      });
      setResult(payload);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <ToolPanel
      actionLabel="Score Contracts"
      description="Ranks sample contracts by liquidity, volatility value, delta fit, and premium quality."
      icon={Gauge}
      isRunning={isRunning}
      onRun={run}
      title="Score Contracts"
    >
      {error ? <ErrorLine message={error} /> : null}
      {result ? (
        <DataTable
          columns={["Symbol", "Type", "Strike", "Mid", "IV", "Delta", "Score", "Rating"]}
          rows={result.ranked_contracts.map((item) => [
            item.symbol,
            item.option_type,
            num(item.strike, 2),
            money(item.mid),
            pct(item.implied_volatility),
            num(item.delta, 2),
            num(item.score, 1),
            item.rating,
          ])}
        />
      ) : (
        <EmptyPrompt label="Run the scorer to rank the bundled sample contracts." />
      )}
    </ToolPanel>
  );
}

function SimulationPanel({ ticker }: { ticker: string }) {
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  async function run() {
    setIsRunning(true);
    setError(null);
    try {
      const payload = await apiPost<SimulationResult>("/api/options/tools/simulate", {
        symbol: ticker,
        spot: 100,
        legs: [
          {
            action: "buy",
            option_type: "call",
            strike: 100,
            expiry_days: 30,
            iv: 0.25,
            entry_price: 5,
          },
          {
            action: "sell",
            option_type: "call",
            strike: 110,
            expiry_days: 30,
            iv: 0.25,
            entry_price: 2,
          },
        ],
      });
      setResult(payload);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsRunning(false);
    }
  }

  const chartRows = useMemo(() => {
    if (!result) {
      return [];
    }
    return result.pnl_at_expiry.price_axis.map((price, index) => ({
      price,
      pnl: result.pnl_at_expiry.pnl_axis[index] ?? 0,
    }));
  }, [result]);

  return (
    <ToolPanel
      actionLabel="Run Simulation"
      description="Shows expiry profit and loss for a sample vertical call spread."
      icon={LineChart}
      isRunning={isRunning}
      onRun={run}
      title="Simulator"
    >
      {error ? <ErrorLine message={error} /> : null}
      {result ? (
        <div className="space-y-4">
          <MetricGrid
            items={[
              ["Max Profit", money(result.max_profit)],
              ["Max Loss", money(result.max_loss)],
              ["Breakevens", result.breakevens.map((item) => num(item, 2)).join(", ") || "--"],
            ]}
          />
          <MiniPnlChart rows={chartRows} />
        </div>
      ) : (
        <EmptyPrompt label="Run the simulator to see payoff bounds and the expiry curve." />
      )}
    </ToolPanel>
  );
}

function SurfacePanel({ ticker: initialTicker }: { ticker: string }) {
  const [ticker, setTicker] = useState(initialTicker);
  const [result, setResult] = useState<SurfaceResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  async function run() {
    setIsRunning(true);
    setError(null);
    try {
      const payload = await apiRequest<SurfaceResult>(
        `/api/options/tools/vol-surface/${encodeURIComponent(ticker.trim().toUpperCase())}?max_expirations=3`,
      );
      setResult(payload);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <ToolPanel
      actionLabel="Load Surface"
      description="Fetches current option IV buckets from the configured read-only quote provider."
      icon={BarChart3}
      isRunning={isRunning}
      onRun={run}
      title="Vol Surface"
      controls={<TickerInput onChange={setTicker} value={ticker} />}
    >
      {error ? <ErrorLine message={error} /> : null}
      {result ? <SurfaceGrid result={result} /> : <EmptyPrompt label={`Click "Load Surface" to fetch live IV data for ${ticker} via Futu.`} />}
    </ToolPanel>
  );
}

function SmilePanel({ ticker: initialTicker }: { ticker: string }) {
  const [ticker, setTicker] = useState(initialTicker);
  const [result, setResult] = useState<SmileResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  async function run() {
    setIsRunning(true);
    setError(null);
    try {
      const payload = await apiRequest<SmileResult>(
        `/api/options/tools/vol-smile/${encodeURIComponent(ticker.trim().toUpperCase())}`,
      );
      setResult(payload);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <ToolPanel
      actionLabel="Load Smile"
      description="Fetches the nearest-expiry volatility smile from the configured read-only quote provider."
      icon={Activity}
      isRunning={isRunning}
      onRun={run}
      title="Vol Smile"
      controls={<TickerInput onChange={setTicker} value={ticker} />}
    >
      {error ? <ErrorLine message={error} /> : null}
      {result ? (
        <div className="space-y-4">
          <MetricGrid
            items={[
              ["Ticker", result.ticker],
              ["Expiry", result.expiry],
              ["Shape", result.shape],
              ["ATM IV", pct(result.skew_metrics.atm_iv)],
              ["25D Skew", num(result.skew_metrics.skew_25d, 2)],
            ]}
          />
          <DataTable
            columns={["Strike", "IV", "Type"]}
            rows={result.smile.strikes.slice(0, 12).map((strike, index) => [
              num(strike, 2),
              pct(result.smile.ivs[index]),
              result.smile.option_types[index] ?? "--",
            ])}
          />
        </div>
      ) : (
        <EmptyPrompt label={`Click "Load Smile" to fetch live IV smile for ${ticker} via Futu.`} />
      )}
    </ToolPanel>
  );
}

function ToolPanel({
  actionLabel,
  children,
  controls,
  description,
  icon: Icon,
  isRunning,
  onRun,
  title,
}: {
  actionLabel: string;
  children: React.ReactNode;
  controls?: React.ReactNode;
  description: string;
  icon: typeof Calculator;
  isRunning: boolean;
  onRun: () => void;
  title: string;
}) {
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-border-subtle pb-4">
        <div className="flex items-start gap-3">
          <div className="mt-1 rounded bg-surface-container p-2 text-accent-success">
            <Icon size={18} />
          </div>
          <div>
            <h2 className="font-headline-lg text-text-primary">{title}</h2>
            <p className="mt-1 max-w-2xl font-body-sm text-text-secondary">{description}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          {controls}
          <button
            className="inline-flex min-h-9 items-center gap-2 rounded border border-accent-success bg-accent-success px-3 py-2 font-label-caps uppercase text-bg-base transition-opacity disabled:opacity-60"
            disabled={isRunning}
            onClick={onRun}
            type="button"
          >
            <Play size={14} />
            <span>{isRunning ? "Running..." : actionLabel}</span>
          </button>
        </div>
      </div>
      {children}
    </div>
  );
}

function TickerInput({ onChange, value }: { onChange: (value: string) => void; value: string }) {
  return (
    <label className="flex flex-col gap-1 font-body-sm text-text-primary">
      Ticker
      <input
        className="h-9 w-28 rounded border border-border-subtle bg-surface-container px-3 font-data-mono uppercase text-text-primary"
        onChange={(event) => onChange(event.target.value)}
        value={value}
      />
    </label>
  );
}

function MetricGrid({ items }: { items: Array<[string, React.ReactNode]> }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {items.map(([label, value]) => (
        <div className="rounded border border-border-subtle bg-bg-surface p-4" key={label}>
          <div className="font-label-caps uppercase text-text-secondary">{label}</div>
          <div className="mt-2 break-words font-data-mono text-lg text-text-primary">{formatDisplay(value)}</div>
        </div>
      ))}
    </div>
  );
}

function DataTable({ columns, rows }: { columns: string[]; rows: React.ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded border border-border-subtle bg-bg-surface">
      <table className="min-w-full border-collapse font-body-sm">
        <thead className="bg-surface-container text-left font-label-caps uppercase text-text-secondary">
          <tr>
            {columns.map((column) => (
              <th className="whitespace-nowrap px-3 py-2" key={column}>
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr className="border-t border-border-subtle/70" key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td className="whitespace-nowrap px-3 py-2 text-text-primary" key={`${rowIndex}-${cellIndex}`}>
                  {formatDisplay(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MiniPnlChart({ rows }: { rows: Array<{ price: number; pnl: number }> }) {
  if (rows.length === 0) {
    return null;
  }
  const minPnl = Math.min(...rows.map((row) => row.pnl));
  const maxPnl = Math.max(...rows.map((row) => row.pnl));
  const range = Math.max(maxPnl - minPnl, 1);

  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-4">
      <div className="mb-3 flex items-center gap-2 font-label-caps uppercase text-text-secondary">
        <SlidersHorizontal size={14} />
        Expiry P&L
      </div>
      <div className="flex h-40 items-end gap-1">
        {rows.map((row) => {
          const positive = row.pnl >= 0;
          const height = Math.max(((row.pnl - minPnl) / range) * 100, 4);
          return (
            <div className="flex flex-1 items-end" key={row.price}>
              <div
                className={positive ? "w-full bg-accent-success" : "w-full bg-danger"}
                style={{ height: `${height}%` }}
                title={`${num(row.price, 2)} / ${money(row.pnl)}`}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SurfaceGrid({ result }: { result: SurfaceResult }) {
  return (
    <div className="space-y-4">
      <MetricGrid
        items={[
          ["Ticker", result.ticker],
          ["Price", money(result.price)],
          ["Shape", result.shape],
        ]}
      />
      <div className="overflow-x-auto rounded border border-border-subtle bg-bg-surface">
        <table className="min-w-full border-collapse font-body-sm">
          <thead className="bg-surface-container text-left font-label-caps uppercase text-text-secondary">
            <tr>
              <th className="px-3 py-2">Expiry</th>
              {result.surface.moneyness_axis.map((point) => (
                <th className="px-3 py-2" key={point}>
                  {num(point, 2)}x
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.surface.expiry_axis.map((expiry, rowIndex) => (
              <tr className="border-t border-border-subtle/70" key={expiry}>
                <td className="whitespace-nowrap px-3 py-2 text-text-primary">{expiry}</td>
                {result.surface.iv_grid[rowIndex]?.map((iv, cellIndex) => (
                  <td className="whitespace-nowrap px-3 py-2 font-data-mono text-text-primary" key={`${expiry}-${cellIndex}`}>
                    {pct(iv)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EmptyPrompt({ label }: { label: string }) {
  return (
    <div className="flex min-h-48 items-center justify-center rounded border border-dashed border-border-subtle bg-bg-surface/60 p-6 text-center font-body-sm text-text-secondary">
      {label}
    </div>
  );
}

function ErrorLine({ message }: { message: string }) {
  return (
    <div className="rounded border border-danger/40 bg-danger/10 px-3 py-2 font-body-sm text-error">
      {message}
    </div>
  );
}

function errorMessage(error: unknown) {
  if (error instanceof ApiClientError) {
    return error.message;
  }
  return error instanceof Error ? error.message : "Request failed";
}

function num(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function money(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "--";
  }
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    maximumFractionDigits: 2,
    style: "currency",
  }).format(value);
}

function pct(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "--";
  }
  return `${(value * 100).toFixed(2)}%`;
}

function formatDisplay(value: React.ReactNode) {
  if (value === null || value === undefined || value === "") {
    return "--";
  }
  return value;
}
