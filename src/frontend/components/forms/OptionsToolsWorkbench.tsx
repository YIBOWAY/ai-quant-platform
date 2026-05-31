'use client';

import type { ReactNode } from "react";
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
import { InfoTip } from "@/components/InfoTip";
import type { Locale } from "@/lib/locale";

type TabId =
  | "greeks"
  | "strategy"
  | "score"
  | "simulate"
  | "surface"
  | "smile"
  | "signals"
  | "researchOps";

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

const tabs: Array<{ id: TabId; icon: typeof Calculator; live: boolean }> = [
  { id: "greeks", icon: Calculator, live: false },
  { id: "strategy", icon: ListChecks, live: false },
  { id: "score", icon: Gauge, live: false },
  { id: "simulate", icon: LineChart, live: false },
  { id: "surface", icon: BarChart3, live: true },
  { id: "smile", icon: Activity, live: true },
  { id: "signals", icon: Gauge, live: false },
  { id: "researchOps", icon: ListChecks, live: false },
];

const copy = {
  en: {
    brand: "Local AlphaGBM",
    title: "Options Tools",
    intro:
      "Read-only option research tools. Tabs marked Live use backend/Futu option data. Tabs marked Example use fixed inputs and say so before showing results.",
    ticker: "Ticker",
    researchOnly: "Research only",
    live: "Live",
    example: "Example",
    running: "Running...",
    response: "response",
    requestFailed: "Request failed",
    expiryPnl: "Expiry P&L",
    tabs: {
      greeks: "Greeks",
      strategy: "Strategy Rank",
      score: "Score Contracts",
      simulate: "Simulator",
      surface: "Vol Surface",
      smile: "Vol Smile",
      signals: "Signals",
      researchOps: "Research Ops",
    },
    labels: {
      price: "Price",
      strategy: "Strategy",
      score: "Score",
      rating: "Rating",
      netDebit: "Net Debit",
      maxProfit: "Max Profit",
      maxLoss: "Max Loss",
      symbol: "Symbol",
      type: "Type",
      strike: "Strike",
      mid: "Mid",
      breakevens: "Breakevens",
      ticker: "Ticker",
      expiry: "Expiry",
      shape: "Shape",
      atmIv: "ATM IV",
      skew25d: "25D Skew",
      iv: "IV",
      delta: "Delta",
    },
    greeks: {
      action: "Calculate Greeks",
      desc: "Price and sensitivity snapshot for a fixed at-the-money call input.",
      empty: "Run the example calculation to inspect the Greeks table.",
    },
    strategy: {
      action: "Rank Strategies",
      desc: "Compares bullish strategy templates with the same fixed spot, IV, DTE, and strike set.",
      empty: "Run the local ranker to compare strategy templates.",
    },
    score: {
      action: "Score Contracts",
      desc: "Ranks fixed example contracts by liquidity, volatility value, delta fit, and premium quality.",
      empty: "Run the scorer to rank the fixed example contracts.",
    },
    simulate: {
      action: "Run Simulation",
      desc: "Shows expiry profit and loss for a fixed vertical call spread input.",
      empty: "Run the simulator to see payoff bounds and the expiry curve.",
    },
    surface: {
      action: "Load Surface",
      desc: "Fetches current option IV buckets from the configured read-only quote provider.",
      empty: (ticker: string) => `Click "Load Surface" to fetch live IV data for ${ticker} via Futu.`,
    },
    smile: {
      action: "Load Smile",
      desc: "Fetches the nearest-expiry volatility smile from the configured read-only quote provider.",
      empty: (ticker: string) => `Click "Load Smile" to fetch live IV smile for ${ticker} via Futu.`,
    },
    signals: {
      action: "Run Fear Score",
      desc: "Runs local signal endpoints with explicit example research inputs. These calls do not fetch live data or create orders.",
      empty: "Choose a signal button to run a local options research endpoint.",
      impliedVolatility: "Implied Volatility",
      bullPutSignal: "Bull Put Signal",
      fearScore: "Fear Score",
      ivRank: "IV Rank",
      marketSentiment: "Market Sentiment",
      earningsCrush: "Earnings Crush",
      hedgeAdvisor: "Hedge Advisor",
      unusualActivity: "Unusual Activity",
    },
    researchOps: {
      action: "Load Templates",
      desc: "Runs local strategy library, watchlist, alert, and research health endpoints with explicit example context where needed.",
      empty: "Choose a research operation to call the connected backend endpoint.",
      strategyTemplates: "Strategy Templates",
      buildStrategy: "Build Strategy",
      addWatchlist: "Add Watchlist",
      loadWatchlist: "Load Watchlist",
      evaluateAlerts: "Evaluate Alerts",
      healthCheck: "Health Check",
    },
    sourceNotes: {
      exampleLabel: "Example input",
      example: "Fixed inputs are sent to backend calculators. This is not live market data.",
      liveLabel: "Live Futu",
      live: "Fetched through backend read-only Futu option-chain endpoints.",
      researchLabel: "Backend local",
      research: "Calls backend research endpoints with explicit example context and never creates orders.",
    },
  },
  zh: {
    brand: "Local AlphaGBM",
    title: "期权工具",
    intro:
      "只读期权研究工具。标为“实时”的标签页使用后端/Futu 期权数据；标为“示例”的标签页使用固定输入，页面会明确说明。",
    ticker: "标的代码",
    researchOnly: "仅供研究",
    live: "实时",
    example: "示例",
    running: "运行中...",
    response: "响应",
    requestFailed: "请求失败",
    expiryPnl: "到期盈亏",
    tabs: {
      greeks: "希腊字母",
      strategy: "策略排名",
      score: "合约评分",
      simulate: "模拟器",
      surface: "波动率曲面",
      smile: "波动率微笑",
      signals: "信号",
      researchOps: "研究操作",
    },
    labels: {
      price: "价格",
      strategy: "策略",
      score: "评分",
      rating: "评级",
      netDebit: "净支出",
      maxProfit: "最大盈利",
      maxLoss: "最大亏损",
      symbol: "代码",
      type: "类型",
      strike: "行权价",
      mid: "中间价",
      breakevens: "盈亏平衡价",
      ticker: "标的",
      expiry: "到期",
      shape: "形态",
      atmIv: "平值 IV",
      skew25d: "25Δ 偏斜",
      iv: "IV",
      delta: "Delta",
    },
    greeks: {
      action: "计算希腊字母",
      desc: "针对固定平值看涨期权输入计算价格与敏感度快照。",
      empty: "运行示例计算以查看希腊字母表。",
    },
    strategy: {
      action: "策略排名",
      desc: "使用固定的现价、IV、到期天数与行权价集合，比较看涨策略模板。",
      empty: "运行本地排名器以比较策略模板。",
    },
    score: {
      action: "合约评分",
      desc: "按流动性、波动率价值、Delta 匹配度与权利金质量对固定示例合约排名。",
      empty: "运行评分器以对固定示例合约排名。",
    },
    simulate: {
      action: "运行模拟",
      desc: "展示固定垂直看涨价差输入在到期时的盈亏。",
      empty: "运行模拟器以查看盈亏边界与到期曲线。",
    },
    surface: {
      action: "加载曲面",
      desc: "从已配置的只读行情源获取当前期权 IV 分桶。",
      empty: (ticker: string) => `点击“加载曲面”以通过富途获取 ${ticker} 的实时 IV 数据。`,
    },
    smile: {
      action: "加载微笑曲线",
      desc: "从已配置的只读行情源获取最近到期的波动率微笑。",
      empty: (ticker: string) => `点击“加载微笑曲线”以通过富途获取 ${ticker} 的实时 IV 微笑数据。`,
    },
    signals: {
      action: "运行恐慌评分",
      desc: "运行本地信号接口，使用明确的示例研究输入。这些调用不会获取实时数据，也不会创建订单。",
      empty: "选择一个信号按钮，运行本地期权研究接口。",
      impliedVolatility: "隐含波动率",
      bullPutSignal: "牛市看跌价差信号",
      fearScore: "恐慌评分",
      ivRank: "IV 排名",
      marketSentiment: "市场情绪",
      earningsCrush: "财报 IV 崩塌",
      hedgeAdvisor: "对冲顾问",
      unusualActivity: "异常活跃度",
    },
    researchOps: {
      action: "加载模板",
      desc: "运行本地策略库、自选清单、提醒与研究健康检查接口；需要上下文时使用明确示例输入。",
      empty: "选择一个研究操作，调用已连接的后端接口。",
      strategyTemplates: "策略模板",
      buildStrategy: "构建策略",
      addWatchlist: "添加自选",
      loadWatchlist: "加载自选",
      evaluateAlerts: "评估提醒",
      healthCheck: "健康检查",
    },
    sourceNotes: {
      exampleLabel: "示例输入",
      example: "固定输入会提交给后端计算器；这不是实时行情数据。",
      liveLabel: "实时 Futu",
      live: "通过后端只读 Futu 期权链接口获取。",
      researchLabel: "本地后端",
      research: "调用后端研究接口，必要时使用明确示例上下文，不会创建订单。",
    },
  },
} as const;

type Copy = (typeof copy)[Locale];

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

export function OptionsToolsWorkbench({ locale = "en" }: { locale?: Locale }) {
  const [activeTab, setActiveTab] = useState<TabId>("greeks");
  const [sharedTicker, setSharedTicker] = useState("AAPL");
  const text = copy[locale];

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <header className="border-b border-border-subtle bg-bg-surface px-6 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="font-label-caps uppercase text-text-secondary">{text.brand}</p>
            <h1 className="mt-1 font-headline-xl text-text-primary">{text.title}</h1>
            <p className="mt-1 max-w-3xl font-body-sm text-text-secondary">
              {text.intro}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 font-body-sm text-text-secondary">
              {text.ticker}
              <input
                className="h-9 w-28 rounded border border-border-subtle bg-surface-container px-3 font-data-mono uppercase text-text-primary"
                onChange={(event) => setSharedTicker(event.target.value.toUpperCase())}
                value={sharedTicker}
              />
            </label>
            <div className="rounded border border-border-subtle bg-surface-container px-3 py-2 font-label-caps uppercase text-accent-success">
              {text.researchOnly}
            </div>
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="w-[260px] shrink-0 overflow-y-auto border-r border-border-subtle bg-bg-surface p-4">
          <div className="space-y-1" role="tablist" aria-label={text.title}>
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
                  <span className="flex-1">{text.tabs[tab.id]}</span>
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-label-caps ${tab.live ? "bg-info/10 text-info" : "bg-surface-muted text-text-secondary"}`}>
                    {tab.live ? text.live : text.example}
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        <section className="min-w-0 flex-1 overflow-y-auto p-6" role="tabpanel">
          {activeTab === "greeks" ? <GreeksPanel t={text} locale={locale} /> : null}
          {activeTab === "strategy" ? <StrategyRankPanel t={text} locale={locale} /> : null}
          {activeTab === "score" ? <ScoreContractsPanel t={text} locale={locale} /> : null}
          {activeTab === "simulate" ? <SimulationPanel ticker={sharedTicker} t={text} locale={locale} /> : null}
          {activeTab === "surface" ? <SurfacePanel ticker={sharedTicker} t={text} /> : null}
          {activeTab === "smile" ? <SmilePanel ticker={sharedTicker} t={text} /> : null}
          {activeTab === "signals" ? <SignalsPanel ticker={sharedTicker} t={text} /> : null}
          {activeTab === "researchOps" ? <ResearchOpsPanel ticker={sharedTicker} t={text} /> : null}
        </section>
      </div>
    </div>
  );
}

function GreeksPanel({ t, locale }: { t: Copy; locale: Locale }) {
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
      setError(errorMessage(err, t.requestFailed));
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <ToolPanel
      actionLabel={t.greeks.action}
      description={t.greeks.desc}
      icon={Calculator}
      isRunning={isRunning}
      onRun={run}
      runningLabel={t.running}
      sourceDescription={t.sourceNotes.example}
      sourceLabel={t.sourceNotes.exampleLabel}
      title={t.tabs.greeks}
    >
      {error ? <ErrorLine message={error} /> : null}
      {result ? (
        <MetricGrid
          items={[
            [t.labels.price, result.price],
            [
              <span className="inline-flex items-center gap-1" key="delta">
                Delta
                <InfoTip term="delta" locale={locale} />
              </span>,
              result.delta,
            ],
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
        <EmptyPrompt label={t.greeks.empty} />
      )}
    </ToolPanel>
  );
}

function StrategyRankPanel({ t, locale }: { t: Copy; locale: Locale }) {
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
      setError(errorMessage(err, t.requestFailed));
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <ToolPanel
      actionLabel={t.strategy.action}
      description={t.strategy.desc}
      icon={ListChecks}
      isRunning={isRunning}
      onRun={run}
      runningLabel={t.running}
      sourceDescription={t.sourceNotes.example}
      sourceLabel={t.sourceNotes.exampleLabel}
      title={t.tabs.strategy}
    >
      {error ? <ErrorLine message={error} /> : null}
      {result ? (
        <DataTable
          columns={[
            t.labels.strategy,
            t.labels.score,
            t.labels.rating,
            <span className="inline-flex items-center gap-1" key="netDebit">
              {t.labels.netDebit}
              <InfoTip term="netDebit" locale={locale} />
            </span>,
            t.labels.maxProfit,
            t.labels.maxLoss,
          ]}
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
        <EmptyPrompt label={t.strategy.empty} />
      )}
    </ToolPanel>
  );
}

function ScoreContractsPanel({ t, locale }: { t: Copy; locale: Locale }) {
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
      setError(errorMessage(err, t.requestFailed));
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <ToolPanel
      actionLabel={t.score.action}
      description={t.score.desc}
      icon={Gauge}
      isRunning={isRunning}
      onRun={run}
      runningLabel={t.running}
      sourceDescription={t.sourceNotes.example}
      sourceLabel={t.sourceNotes.exampleLabel}
      title={t.tabs.score}
    >
      {error ? <ErrorLine message={error} /> : null}
      {result ? (
        <DataTable
          columns={[
            t.labels.symbol,
            t.labels.type,
            t.labels.strike,
            t.labels.mid,
            t.labels.iv,
            <span className="inline-flex items-center gap-1" key="delta">
              Delta
              <InfoTip term="delta" locale={locale} />
            </span>,
            t.labels.score,
            t.labels.rating,
          ]}
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
        <EmptyPrompt label={t.score.empty} />
      )}
    </ToolPanel>
  );
}

function SimulationPanel({ ticker, t, locale }: { ticker: string; t: Copy; locale: Locale }) {
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
      setError(errorMessage(err, t.requestFailed));
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
      actionLabel={t.simulate.action}
      description={t.simulate.desc}
      icon={LineChart}
      isRunning={isRunning}
      onRun={run}
      runningLabel={t.running}
      sourceDescription={t.sourceNotes.example}
      sourceLabel={t.sourceNotes.exampleLabel}
      title={t.tabs.simulate}
    >
      {error ? <ErrorLine message={error} /> : null}
      {result ? (
        <div className="space-y-4">
          <MetricGrid
            items={[
              [t.labels.maxProfit, money(result.max_profit)],
              [t.labels.maxLoss, money(result.max_loss)],
              [
                <span className="inline-flex items-center gap-1" key="breakevens">
                  {t.labels.breakevens}
                  <InfoTip term="breakEven" locale={locale} />
                </span>,
                result.breakevens.map((item) => num(item, 2)).join(", ") || "--",
              ],
            ]}
          />
          <MiniPnlChart rows={chartRows} label={t.expiryPnl} />
        </div>
      ) : (
        <EmptyPrompt label={t.simulate.empty} />
      )}
    </ToolPanel>
  );
}

function SurfacePanel({ ticker: initialTicker, t }: { ticker: string; t: Copy }) {
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
      setError(errorMessage(err, t.requestFailed));
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <ToolPanel
      actionLabel={t.surface.action}
      description={t.surface.desc}
      icon={BarChart3}
      isRunning={isRunning}
      onRun={run}
      runningLabel={t.running}
      sourceDescription={t.sourceNotes.live}
      sourceLabel={t.sourceNotes.liveLabel}
      title={t.tabs.surface}
      controls={<TickerInput onChange={setTicker} value={ticker} label={t.ticker} />}
    >
      {error ? <ErrorLine message={error} /> : null}
      {result ? <SurfaceGrid result={result} t={t} /> : <EmptyPrompt label={t.surface.empty(ticker)} />}
    </ToolPanel>
  );
}

function SmilePanel({ ticker: initialTicker, t }: { ticker: string; t: Copy }) {
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
      setError(errorMessage(err, t.requestFailed));
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <ToolPanel
      actionLabel={t.smile.action}
      description={t.smile.desc}
      icon={Activity}
      isRunning={isRunning}
      onRun={run}
      runningLabel={t.running}
      sourceDescription={t.sourceNotes.live}
      sourceLabel={t.sourceNotes.liveLabel}
      title={t.tabs.smile}
      controls={<TickerInput onChange={setTicker} value={ticker} label={t.ticker} />}
    >
      {error ? <ErrorLine message={error} /> : null}
      {result ? (
        <div className="space-y-4">
          <MetricGrid
            items={[
              [t.labels.ticker, result.ticker],
              [t.labels.expiry, result.expiry],
              [t.labels.shape, result.shape],
              [t.labels.atmIv, pct(result.skew_metrics.atm_iv)],
              [t.labels.skew25d, num(result.skew_metrics.skew_25d, 2)],
            ]}
          />
          <DataTable
            columns={[t.labels.strike, t.labels.iv, t.labels.type]}
            rows={result.smile.strikes.slice(0, 12).map((strike, index) => [
              num(strike, 2),
              pct(result.smile.ivs[index]),
              result.smile.option_types[index] ?? "--",
            ])}
          />
        </div>
      ) : (
        <EmptyPrompt label={t.smile.empty(ticker)} />
      )}
    </ToolPanel>
  );
}

function SignalsPanel({ ticker, t }: { ticker: string; t: Copy }) {
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState<string | null>(null);

  async function run(title: string, request: () => Promise<unknown>) {
    setIsRunning(title);
    setError(null);
    try {
      const payload = await request();
      setResult({ title, payload });
    } catch (err) {
      setError(errorMessage(err, t.requestFailed));
    } finally {
      setIsRunning(null);
    }
  }

  return (
    <ToolPanel
      actionLabel={t.signals.action}
      description={t.signals.desc}
      icon={Gauge}
      isRunning={isRunning !== null}
      onRun={() =>
        run(t.signals.fearScore, () =>
          apiPost("/api/options/tools/fear-score", {
            vix: 24,
            iv_rank: 72,
            rsi_14: 34,
            options_volume_anomaly: 2.4,
            put_call_ratio: 1.1,
            consecutive_down_days: 3,
          }),
        )
      }
      runningLabel={t.running}
      sourceDescription={t.sourceNotes.research}
      sourceLabel={t.sourceNotes.researchLabel}
      title={t.tabs.signals}
    >
      {error ? <ErrorLine message={error} /> : null}
      <ActionGrid
        runningLabel={t.running}
        actions={[
          {
            label: t.signals.impliedVolatility,
            onClick: () =>
              run(t.signals.impliedVolatility, () =>
                apiPost("/api/options/tools/implied-volatility", {
                  market_price: 4.2,
                  spot: 100,
                  strike: 100,
                  expiry_days: 30,
                  option_type: "call",
                }),
              ),
          },
          {
            label: t.signals.bullPutSignal,
            onClick: () =>
              run(t.signals.bullPutSignal, () =>
                apiPost("/api/options/tools/bull-put-signal", {
                  contracts: sampleContracts,
                  spot: 100,
                  fear_score: 68,
                }),
              ),
          },
          {
            label: t.signals.fearScore,
            onClick: () =>
              run(t.signals.fearScore, () =>
                apiPost("/api/options/tools/fear-score", {
                  vix: 24,
                  iv_rank: 72,
                  rsi_14: 34,
                  options_volume_anomaly: 2.4,
                  put_call_ratio: 1.1,
                  consecutive_down_days: 3,
                }),
              ),
          },
          {
            label: t.signals.ivRank,
            onClick: () =>
              run(t.signals.ivRank, () =>
                apiPost("/api/options/tools/iv-rank", {
                  ticker,
                  current_iv: 0.42,
                  history: [0.18, 0.22, 0.29, 0.35, 0.48, 0.39, 0.31],
                }),
              ),
          },
          {
            label: t.signals.marketSentiment,
            onClick: () =>
              run(t.signals.marketSentiment, () =>
                apiPost("/api/options/tools/market-sentiment", {
                  vix: 24,
                  put_call_ratio: 1.05,
                  advance_decline_ratio: 0.85,
                  percent_above_200dma: 45,
                }),
              ),
          },
          {
            label: t.signals.earningsCrush,
            onClick: () =>
              run(t.signals.earningsCrush, () =>
                apiPost("/api/options/tools/earnings-crush", {
                  ticker,
                  current_iv: 0.58,
                  implied_move_pct: 0.07,
                  historical_pre_post_iv: [
                    { pre_iv: 0.62, post_iv: 0.41 },
                    { pre_iv: 0.55, post_iv: 0.39 },
                    { pre_iv: 0.49, post_iv: 0.36 },
                  ],
                }),
              ),
          },
          {
            label: t.signals.hedgeAdvisor,
            onClick: () =>
              run(t.signals.hedgeAdvisor, () =>
                apiPost("/api/options/tools/hedge-advisor", {
                  ticker,
                  shares: 100,
                  cost_basis: 88,
                  spot: 100,
                  purpose: "protect",
                  contracts: sampleContracts,
                }),
              ),
          },
          {
            label: t.signals.unusualActivity,
            onClick: () =>
              run(t.signals.unusualActivity, () =>
                apiPost("/api/options/tools/unusual-activity", {
                  contracts: [
                    ...sampleContracts,
                    {
                      symbol: `${ticker}_PUT_SPIKE`,
                      option_type: "PUT",
                      strike: 92,
                      bid: 1.8,
                      ask: 1.95,
                      volume: 2500,
                      open_interest: 400,
                      implied_volatility: 0.54,
                      delta: -0.28,
                    },
                  ],
                  min_volume_oi_ratio: 2,
                  min_volume: 100,
                }),
              ),
          },
        ]}
        isRunning={isRunning}
      />
      {result ? <JsonResult title={result.title} payload={result.payload} responseLabel={t.response} /> : <EmptyPrompt label={t.signals.empty} />}
    </ToolPanel>
  );
}

function ResearchOpsPanel({ ticker, t }: { ticker: string; t: Copy }) {
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState<string | null>(null);

  async function run(title: string, request: () => Promise<unknown>) {
    setIsRunning(title);
    setError(null);
    try {
      const payload = await request();
      setResult({ title, payload });
    } catch (err) {
      setError(errorMessage(err, t.requestFailed));
    } finally {
      setIsRunning(null);
    }
  }

  return (
    <ToolPanel
      actionLabel={t.researchOps.action}
      description={t.researchOps.desc}
      icon={ListChecks}
      isRunning={isRunning !== null}
      onRun={() =>
        run(t.researchOps.strategyTemplates, () => apiRequest("/api/options/tools/strategy/templates"))
      }
      runningLabel={t.running}
      sourceDescription={t.sourceNotes.research}
      sourceLabel={t.sourceNotes.researchLabel}
      title={t.tabs.researchOps}
    >
      {error ? <ErrorLine message={error} /> : null}
      <ActionGrid
        runningLabel={t.running}
        actions={[
          {
            label: t.researchOps.strategyTemplates,
            onClick: () =>
              run(t.researchOps.strategyTemplates, () => apiRequest("/api/options/tools/strategy/templates")),
          },
          {
            label: t.researchOps.buildStrategy,
            onClick: () =>
              run(t.researchOps.buildStrategy, () =>
                apiPost("/api/options/tools/strategy/build", {
                  mode: "template",
                  template_id: "bull_call_spread",
                  spot: 100,
                  expiry_days: 45,
                  strikes: [90, 95, 100, 105, 110],
                  iv: 0.28,
                  symbol: ticker,
                }),
              ),
          },
          {
            label: t.researchOps.addWatchlist,
            onClick: () =>
              run(t.researchOps.addWatchlist, () =>
                apiPost("/api/options/tools/watchlist", {
                  ticker,
                  tags: ["local-research"],
                }),
              ),
          },
          {
            label: t.researchOps.loadWatchlist,
            onClick: () => run(t.researchOps.loadWatchlist, () => apiRequest("/api/options/tools/watchlist")),
          },
          {
            label: t.researchOps.evaluateAlerts,
            onClick: () =>
              run(t.researchOps.evaluateAlerts, () =>
                apiPost("/api/options/tools/alerts/evaluate", {
                  alerts: [
                    { id: "price-break", ticker, type: "price_above", threshold: 95 },
                    { id: "iv-high", ticker, type: "iv_rank_above", threshold: 70 },
                  ],
                  context: {
                    ticker,
                    price: 101,
                    iv_rank: 74,
                    unusual_activity_count: 1,
                  },
                }),
              ),
          },
          {
            label: t.researchOps.healthCheck,
            onClick: () =>
              run(t.researchOps.healthCheck, () =>
                apiPost("/api/options/tools/health-check", {
                  today: "2026-05-25",
                  stale_after_days: 14,
                  profiles: [
                    { ticker, updated_at: "2026-05-20", thesis: "Options research profile." },
                    { ticker: "OLD", updated_at: "2026-04-01", thesis: "" },
                  ],
                }),
              ),
          },
        ]}
        isRunning={isRunning}
      />
      {result ? <JsonResult title={result.title} payload={result.payload} responseLabel={t.response} /> : <EmptyPrompt label={t.researchOps.empty} />}
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
  runningLabel,
  sourceDescription,
  sourceLabel,
  title,
}: {
  actionLabel: string;
  children: ReactNode;
  controls?: ReactNode;
  description: string;
  icon: typeof Calculator;
  isRunning: boolean;
  onRun: () => void;
  runningLabel: string;
  sourceDescription?: string;
  sourceLabel?: string;
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
            {sourceLabel && sourceDescription ? (
              <div className="mt-2 flex max-w-2xl flex-wrap items-center gap-2 rounded border border-border-subtle bg-surface-muted px-3 py-2 font-body-sm text-text-secondary">
                <span className="rounded border border-warning/40 bg-warning/10 px-2 py-0.5 font-label-caps uppercase text-warning">
                  {sourceLabel}
                </span>
                <span>{sourceDescription}</span>
              </div>
            ) : null}
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
            <span>{isRunning ? runningLabel : actionLabel}</span>
          </button>
        </div>
      </div>
      {children}
    </div>
  );
}

function TickerInput({ onChange, value, label }: { onChange: (value: string) => void; value: string; label: string }) {
  return (
    <label className="flex flex-col gap-1 font-body-sm text-text-primary">
      {label}
      <input
        className="h-9 w-28 rounded border border-border-subtle bg-surface-container px-3 font-data-mono uppercase text-text-primary"
        onChange={(event) => onChange(event.target.value)}
        value={value}
      />
    </label>
  );
}

function MetricGrid({ items }: { items: Array<[ReactNode, ReactNode]> }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {items.map(([label, value], index) => (
        <div className="rounded border border-border-subtle bg-bg-surface p-4" key={index}>
          <div className="font-label-caps uppercase text-text-secondary">{label}</div>
          <div className="mt-2 break-words font-data-mono text-lg text-text-primary">{formatDisplay(value)}</div>
        </div>
      ))}
    </div>
  );
}

function DataTable({ columns, rows }: { columns: ReactNode[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded border border-border-subtle bg-bg-surface">
      <table className="min-w-full border-collapse font-body-sm">
        <thead className="bg-surface-container text-left font-label-caps uppercase text-text-secondary">
          <tr>
            {columns.map((column, columnIndex) => (
              <th className="whitespace-nowrap px-3 py-2" key={columnIndex}>
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

function MiniPnlChart({ rows, label }: { rows: Array<{ price: number; pnl: number }>; label: string }) {
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
        {label}
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

function SurfaceGrid({ result, t }: { result: SurfaceResult; t: Copy }) {
  return (
    <div className="space-y-4">
      <MetricGrid
        items={[
          [t.labels.ticker, result.ticker],
          [t.labels.price, money(result.price)],
          [t.labels.shape, result.shape],
        ]}
      />
      <div className="overflow-x-auto rounded border border-border-subtle bg-bg-surface">
        <table className="min-w-full border-collapse font-body-sm">
          <thead className="bg-surface-container text-left font-label-caps uppercase text-text-secondary">
            <tr>
              <th className="px-3 py-2">{t.labels.expiry}</th>
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

function ActionGrid({
  actions,
  isRunning,
  runningLabel,
}: {
  actions: Array<{ label: string; onClick: () => void }>;
  isRunning: string | null;
  runningLabel: string;
}) {
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {actions.map((action) => (
        <button
          className="rounded border border-border-subtle bg-bg-surface px-3 py-2 text-left font-body-sm text-text-primary hover:bg-surface-container disabled:cursor-not-allowed disabled:opacity-60"
          disabled={isRunning !== null}
          key={action.label}
          onClick={action.onClick}
          type="button"
        >
          {isRunning === action.label ? runningLabel : action.label}
        </button>
      ))}
    </div>
  );
}

function JsonResult({ payload, title, responseLabel }: { payload: unknown; title: string; responseLabel: string }) {
  return (
    <section className="rounded border border-border-subtle bg-bg-surface p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="font-label-caps text-text-primary">{title}</h3>
        <span className="font-label-caps text-text-secondary">{responseLabel}</span>
      </div>
      <pre className="max-h-[360px] overflow-auto rounded bg-surface-muted p-3 font-code-sm text-text-primary">
        {JSON.stringify(payload, null, 2)}
      </pre>
    </section>
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

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiClientError) {
    return error.message;
  }
  return error instanceof Error ? error.message : fallback;
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

function formatDisplay(value: ReactNode) {
  if (value === null || value === undefined || value === "") {
    return "--";
  }
  return value;
}
