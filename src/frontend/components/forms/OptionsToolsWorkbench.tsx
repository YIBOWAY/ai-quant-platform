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
import type {
  OptionContract,
  OptionsChainResponse,
  OptionsGreeksResponse,
  OptionsSimulationResponse,
  OptionsSnapshotResponse,
  OptionsVolSmileResponse,
  OptionsVolSurfaceResponse,
} from "@/lib/api";
import { ApiClientError, apiPost, apiRequest } from "@/lib/apiClient";
import { InfoTip } from "@/components/InfoTip";
import { Card, PageHeader, StatusPill } from "@/components/ui/primitives";
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

const tabs: Array<{ id: TabId; icon: typeof Calculator; live: boolean }> = [
  { id: "greeks", icon: Calculator, live: true },
  { id: "strategy", icon: ListChecks, live: true },
  { id: "score", icon: Gauge, live: true },
  { id: "simulate", icon: LineChart, live: true },
  { id: "surface", icon: BarChart3, live: true },
  { id: "smile", icon: Activity, live: true },
  { id: "signals", icon: Gauge, live: true },
  { id: "researchOps", icon: ListChecks, live: true },
];

const copy = {
  en: {
    brand: "Local AlphaGBM",
    title: "Options Tools",
    intro:
      "Read-only option research tools. Market-sensitive calculations first load the entered ticker from backend Futu data, then send those live inputs to local calculators.",
    ticker: "Ticker",
    researchOnly: "Research only",
    live: "Live",
    example: "Local",
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
      desc: "Loads the nearest live option chain, picks the at-the-money call, then calculates price sensitivity.",
      empty: "Run the calculation to inspect the live-chain Greeks table.",
    },
    strategy: {
      action: "Rank Strategies",
      desc: "Compares bullish strategy templates using the live spot, nearest expiry, IV, and listed strikes.",
      empty: "Run the local ranker with live Futu inputs.",
    },
    score: {
      action: "Score Contracts",
      desc: "Ranks the live option chain by liquidity, volatility value, delta fit, and premium quality.",
      empty: "Run the scorer to rank current listed contracts.",
    },
    simulate: {
      action: "Run Simulation",
      desc: "Builds a simple call spread from the live chain and shows the expiry payoff.",
      empty: "Run the simulator to see live-chain payoff bounds and the expiry curve.",
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
      desc: "Runs local signal endpoints with live option-chain context where the signal can be derived from the entered ticker.",
      empty: "Choose a signal button to run a live-chain research endpoint.",
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
      desc: "Runs local strategy library, watchlist, and alert endpoints with live ticker context where market data is needed.",
      empty: "Choose a research operation to call the connected backend endpoint.",
      strategyTemplates: "Strategy Templates",
      buildStrategy: "Build Strategy",
      addWatchlist: "Add Watchlist",
      loadWatchlist: "Load Watchlist",
      evaluateAlerts: "Evaluate Alerts",
      healthCheck: "Health Check",
    },
    sourceNotes: {
      exampleLabel: "Local input",
      example: "This call uses user or local context and does not fetch market data.",
      liveLabel: "Live Futu",
      live: "Fetched through backend read-only Futu option-chain endpoints before calculation.",
      researchLabel: "Backend local",
      research: "Calls backend research endpoints with live ticker context when market data is needed and never creates orders.",
    },
  },
  zh: {
    brand: "Local AlphaGBM",
    title: "期权工具",
    intro:
      "只读期权研究工具。凡是需要市场数据的计算，都会先从后端读取当前标的的 Futu 期权链，再交给本地计算器处理。",
    ticker: "标的代码",
    researchOnly: "仅供研究",
    live: "实时",
    example: "本地",
    running: "运行中...",
    response: "返回结果",
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
      expiry: "到期日",
      shape: "形态",
      atmIv: "平值 IV",
      skew25d: "25D 偏斜",
      iv: "IV",
      delta: "Delta",
    },
    greeks: {
      action: "计算希腊字母",
      desc: "读取最近一期实时期权链，选择接近平值的看涨合约，再计算价格敏感度。",
      empty: "运行计算后，可以查看当前期权链里的希腊字母结果。",
    },
    strategy: {
      action: "策略排名",
      desc: "使用实时现价、最近到期日、IV 和上市行权价，比较看涨策略模板。",
      empty: "用 Futu 实时输入运行本地策略排名器。",
    },
    score: {
      action: "合约评分",
      desc: "按流动性、波动率价值、Delta 匹配度和权利金质量，对当前期权链里的合约排名。",
      empty: "运行评分器，给当前上市合约排序。",
    },
    simulate: {
      action: "运行模拟",
      desc: "从实时期权链构建一个简单看涨价差，并显示到期盈亏。",
      empty: "运行模拟器，查看当前期权链下的盈亏边界和到期曲线。",
    },
    surface: {
      action: "加载曲面",
      desc: "从已配置的只读行情源读取当前期权 IV 分布。",
      empty: (ticker: string) => `点击“加载曲面”，通过 Futu 读取 ${ticker} 的实时 IV 数据。`,
    },
    smile: {
      action: "加载微笑曲线",
      desc: "从已配置的只读行情源读取最近到期日的波动率微笑。",
      empty: (ticker: string) => `点击“加载微笑曲线”，通过 Futu 读取 ${ticker} 的实时 IV 微笑数据。`,
    },
    signals: {
      action: "运行恐慌评分",
      desc: "运行本地信号接口；凡是能从输入标的推导的信号，都会先读取实时期权链。",
      empty: "选择一个信号按钮，运行实时期权链研究接口。",
      impliedVolatility: "隐含波动率",
      bullPutSignal: "牛市看跌价差信号",
      fearScore: "恐慌评分",
      ivRank: "IV 排名",
      marketSentiment: "市场情绪",
      earningsCrush: "财报 IV 回落",
      hedgeAdvisor: "对冲建议",
      unusualActivity: "异常活跃度",
    },
    researchOps: {
      action: "加载模板",
      desc: "运行本地策略库、自选清单和提醒接口；需要市场数据时会使用当前标的的实时上下文。",
      empty: "选择一个研究操作，调用已连接的后端接口。",
      strategyTemplates: "策略模板",
      buildStrategy: "构建策略",
      addWatchlist: "加入自选",
      loadWatchlist: "加载自选",
      evaluateAlerts: "评估提醒",
      healthCheck: "健康检查",
    },
    sourceNotes: {
      exampleLabel: "本地输入",
      example: "这个调用使用用户输入或本地上下文，不读取行情。",
      liveLabel: "实时 Futu",
      live: "计算前通过后端只读 Futu 期权链接口获取。",
      researchLabel: "本地后端",
      research: "调用后端研究接口；需要市场数据时使用当前标的上下文，不会创建订单。",
    },
  },
} as const;

type Copy = (typeof copy)[Locale];

type LiveContract = OptionContract;

type LiveContext = {
  ticker: string;
  spot: number;
  expiry: string;
  dte: number;
  atmIv: number | null;
  hv30d: number | null;
  ivRank: number | null;
  contracts: LiveContract[];
};

export function OptionsToolsWorkbench({ locale = "en" }: { locale?: Locale }) {
  const [activeTab, setActiveTab] = useState<TabId>("greeks");
  const [sharedTicker, setSharedTicker] = useState("AAPL");
  const text = copy[locale];

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="border-b border-border-subtle bg-bg-surface px-6 py-4">
        <PageHeader
          eyebrow={text.brand}
          title={text.title}
          subtitle={text.intro}
          actions={
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 font-body-sm text-text-secondary">
                {text.ticker}
                <input
                  className="h-9 w-28 rounded-lg border border-border-subtle bg-surface-container px-3 font-data-mono uppercase text-text-primary focus:border-accent-success/60 focus:outline-none"
                  onChange={(event) => setSharedTicker(event.target.value.toUpperCase())}
                  value={sharedTicker}
                />
              </label>
              <StatusPill label="●" value={text.researchOnly} tone="success" />
            </div>
          }
        />
      </div>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="w-[240px] shrink-0 overflow-y-auto border-r border-border-subtle bg-bg-surface p-3">
          <div className="space-y-0.5" role="tablist" aria-label={text.title}>
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const selected = activeTab === tab.id;
              return (
                <button
                  aria-selected={selected}
                  className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left font-body-sm transition-colors ${
                    selected
                      ? "bg-surface-container text-accent-success"
                      : "text-text-secondary hover:bg-surface-container/70 hover:text-text-primary"
                  }`}
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  role="tab"
                  type="button"
                >
                  <Icon size={16} className={selected ? "text-accent-success" : "text-text-secondary"} />
                  <span className="flex-1">{text.tabs[tab.id]}</span>
                  <span className={`rounded-lg px-1.5 py-0.5 text-[10px] font-label-caps uppercase ${tab.live ? "bg-info/10 text-info" : "bg-bg-surface-muted text-text-secondary"}`}>
                    {tab.live ? text.live : text.example}
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        <section className="min-w-0 flex-1 overflow-y-auto p-6" role="tabpanel">
          {activeTab === "greeks" ? <GreeksPanel ticker={sharedTicker} t={text} locale={locale} /> : null}
          {activeTab === "strategy" ? <StrategyRankPanel ticker={sharedTicker} t={text} locale={locale} /> : null}
          {activeTab === "score" ? <ScoreContractsPanel ticker={sharedTicker} t={text} locale={locale} /> : null}
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

function GreeksPanel({ ticker, t, locale }: { ticker: string; t: Copy; locale: Locale }) {
  const [result, setResult] = useState<OptionsGreeksResponse | null>(null);
  const [selectedContract, setSelectedContract] = useState<LiveContract | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  async function run() {
    setIsRunning(true);
    setError(null);
    try {
      const context = await loadLiveContext(ticker);
      const contract = pickAtmContract(context.contracts, context.spot, "CALL");
      if (!contract?.strike || !contract.implied_volatility) {
        throw new Error(`No usable live at-the-money call was found for ${context.ticker}.`);
      }
      const payload = await apiPost<OptionsGreeksResponse>("/api/options/tools/greeks", {
        spot: context.spot,
        strike: contract.strike,
        expiry_days: context.dte,
        iv: normalizeIv(contract.implied_volatility),
        option_type: "call",
      });
      setSelectedContract(contract);
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
      sourceDescription={t.sourceNotes.live}
      sourceLabel={t.sourceNotes.liveLabel}
      title={t.tabs.greeks}
    >
      {error ? <ErrorLine message={error} /> : null}
      {result ? (
        <div className="space-y-4">
          <MetricGrid
            items={[
              [t.labels.symbol, selectedContract?.symbol ?? "--"],
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
          <GreekGuide locale={locale} />
        </div>
      ) : (
        <div className="space-y-4">
          <EmptyPrompt label={t.greeks.empty} />
          <GreekGuide locale={locale} />
        </div>
      )}
    </ToolPanel>
  );
}

function StrategyRankPanel({ ticker, t, locale }: { ticker: string; t: Copy; locale: Locale }) {
  const [result, setResult] = useState<StrategyRankResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  async function run() {
    setIsRunning(true);
    setError(null);
    try {
      const context = await loadLiveContext(ticker);
      const strikes = liveStrikes(context);
      const payload = await apiPost<StrategyRankResult>("/api/options/tools/strategy/rank", {
        market_view: "bullish",
        spot: context.spot,
        expiry_days: context.dte,
        strikes,
        iv: context.atmIv ?? 0.3,
        symbol: context.ticker,
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
      sourceDescription={t.sourceNotes.live}
      sourceLabel={t.sourceNotes.liveLabel}
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

function ScoreContractsPanel({ ticker, t, locale }: { ticker: string; t: Copy; locale: Locale }) {
  const [result, setResult] = useState<ScoreContractsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  async function run() {
    setIsRunning(true);
    setError(null);
    try {
      const context = await loadLiveContext(ticker);
      const payload = await apiPost<ScoreContractsResult>("/api/options/tools/score-contracts", {
        spot: context.spot,
        objective: "sell_premium",
        top_n: 10,
        contracts: context.contracts,
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
      sourceDescription={t.sourceNotes.live}
      sourceLabel={t.sourceNotes.liveLabel}
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
  const [result, setResult] = useState<OptionsSimulationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  async function run() {
    setIsRunning(true);
    setError(null);
    try {
      const context = await loadLiveContext(ticker);
      const [longCall, shortCall] = buildLiveCallSpread(context);
      const payload = await apiPost<OptionsSimulationResponse>("/api/options/tools/simulate", {
        symbol: context.ticker,
        spot: context.spot,
        legs: [
          {
            action: "buy",
            option_type: "call",
            strike: longCall.strike,
            expiry_days: context.dte,
            iv: normalizeIv(longCall.implied_volatility),
            entry_price: midPrice(longCall),
          },
          {
            action: "sell",
            option_type: "call",
            strike: shortCall.strike,
            expiry_days: context.dte,
            iv: normalizeIv(shortCall.implied_volatility),
            entry_price: midPrice(shortCall),
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
      sourceDescription={t.sourceNotes.live}
      sourceLabel={t.sourceNotes.liveLabel}
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
  const [result, setResult] = useState<OptionsVolSurfaceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  async function run() {
    setIsRunning(true);
    setError(null);
    try {
      const payload = await apiRequest<OptionsVolSurfaceResponse>(
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
  const [result, setResult] = useState<OptionsVolSmileResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  async function run() {
    setIsRunning(true);
    setError(null);
    try {
      const payload = await apiRequest<OptionsVolSmileResponse>(
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
          liveFearScore(ticker),
        )
      }
      runningLabel={t.running}
      sourceDescription={t.sourceNotes.live}
      sourceLabel={t.sourceNotes.liveLabel}
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
                liveImpliedVolatility(ticker),
              ),
          },
          {
            label: t.signals.bullPutSignal,
            onClick: () =>
              run(t.signals.bullPutSignal, () =>
                liveBullPutSignal(ticker),
              ),
          },
          {
            label: t.signals.fearScore,
            onClick: () =>
              run(t.signals.fearScore, () =>
                liveFearScore(ticker),
              ),
          },
          {
            label: t.signals.ivRank,
            onClick: () =>
              run(t.signals.ivRank, () =>
                apiRequest(`/api/options/snapshot/${encodeURIComponent(ticker)}`),
              ),
          },
          {
            label: t.signals.earningsCrush,
            onClick: () =>
              run(t.signals.earningsCrush, () =>
                liveEarningsCrush(ticker),
              ),
          },
          {
            label: t.signals.unusualActivity,
            onClick: () =>
              run(t.signals.unusualActivity, () =>
                liveUnusualActivity(ticker),
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
                liveBuildStrategy(ticker),
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
                liveEvaluateAlerts(ticker),
              ),
          },
        ]}
        isRunning={isRunning}
      />
      {result ? <JsonResult title={result.title} payload={result.payload} responseLabel={t.response} /> : <EmptyPrompt label={t.researchOps.empty} />}
    </ToolPanel>
  );
}

async function loadLiveContext(ticker: string): Promise<LiveContext> {
  const normalized = ticker.trim().toUpperCase();
  if (!normalized) {
    throw new Error("Ticker is required.");
  }
  const snapshot = await apiRequest<OptionsSnapshotResponse>(
    `/api/options/snapshot/${encodeURIComponent(normalized)}`,
  );
  const expiry = snapshot.nearest_expiry;
  const params = new URLSearchParams({
    ticker: snapshot.ticker || normalized,
    expiration: expiry,
    option_type: "ALL",
  });
  const chain = await apiRequest<OptionsChainResponse>(
    `/api/options/chain?${params.toString()}`,
  );
  return {
    ticker: snapshot.ticker || chain.ticker || normalized,
    spot: snapshot.price,
    expiry,
    dte: daysToExpiry(expiry),
    atmIv: normalizeOptionalIv(snapshot.atm_iv),
    hv30d: snapshot.hv_30d ?? null,
    ivRank: snapshot.iv_rank ?? null,
    contracts: chain.contracts.map((contract) => ({
      ...contract,
      expiry: contract.expiry ?? chain.expiration,
    })),
  };
}

function usableContracts(
  contracts: LiveContract[],
  optionType?: "CALL" | "PUT",
): Array<LiveContract & { strike: number; implied_volatility: number }> {
  return contracts
    .filter((contract) => !optionType || contract.option_type.toUpperCase() === optionType)
    .map((contract) => ({
      ...contract,
      strike: typeof contract.strike === "number" ? contract.strike : Number.NaN,
      implied_volatility: normalizeOptionalIv(contract.implied_volatility) ?? Number.NaN,
    }))
    .filter(
      (contract): contract is LiveContract & { strike: number; implied_volatility: number } =>
        Number.isFinite(contract.strike) &&
        contract.strike > 0 &&
        Number.isFinite(contract.implied_volatility) &&
        contract.implied_volatility > 0,
    );
}

function pickAtmContract(
  contracts: LiveContract[],
  spot: number,
  optionType: "CALL" | "PUT",
) {
  const available = usableContracts(contracts, optionType);
  return available.sort((left, right) => Math.abs(left.strike - spot) - Math.abs(right.strike - spot))[0];
}

function liveStrikes(context: LiveContext) {
  const strikes = [...new Set(usableContracts(context.contracts).map((contract) => contract.strike))]
    .sort((left, right) => Math.abs(left - context.spot) - Math.abs(right - context.spot))
    .slice(0, 9)
    .sort((left, right) => left - right);
  if (strikes.length < 2) {
    throw new Error(`No usable live strikes were found for ${context.ticker}.`);
  }
  return strikes;
}

function buildLiveCallSpread(context: LiveContext) {
  const callsByStrike = usableContracts(context.contracts, "CALL")
    .filter((contract) => midPrice(contract) !== null)
    .sort((left, right) => left.strike - right.strike);
  const longCall = [...callsByStrike].sort(
    (left, right) => Math.abs(left.strike - context.spot) - Math.abs(right.strike - context.spot),
  )[0];
  if (!longCall) {
    throw new Error(`No usable live call was found for ${context.ticker}.`);
  }
  const shortCall = callsByStrike.find((contract) => contract.strike > longCall.strike);
  if (!shortCall) {
    throw new Error(`No higher-strike live call was found for ${context.ticker}.`);
  }
  return [longCall, shortCall] as const;
}

async function liveImpliedVolatility(ticker: string) {
  const context = await loadLiveContext(ticker);
  const contract = pickAtmContract(context.contracts, context.spot, "CALL");
  const marketPrice = contract ? midPrice(contract) : null;
  if (!contract || marketPrice === null) {
    throw new Error(`No usable live call quote was found for ${context.ticker}.`);
  }
  return apiPost("/api/options/tools/implied-volatility", {
    market_price: marketPrice,
    spot: context.spot,
    strike: contract.strike,
    expiry_days: context.dte,
    option_type: "call",
  });
}

async function liveFearScore(ticker: string) {
  const context = await loadLiveContext(ticker);
  return apiPost("/api/options/tools/fear-score", {
    iv_rank: context.ivRank,
  });
}

async function liveBullPutSignal(ticker: string) {
  const context = await loadLiveContext(ticker);
  const fear = await apiPost<{ fear_score: number }>("/api/options/tools/fear-score", {
    iv_rank: context.ivRank,
  });
  return apiPost("/api/options/tools/bull-put-signal", {
    contracts: context.contracts,
    spot: context.spot,
    fear_score: fear.fear_score,
  });
}

async function liveEarningsCrush(ticker: string) {
  const context = await loadLiveContext(ticker);
  const contract = pickAtmContract(context.contracts, context.spot, "CALL");
  const currentIv = context.atmIv ?? contract?.implied_volatility ?? null;
  if (currentIv === null) {
    throw new Error(`No live IV was found for ${context.ticker}.`);
  }
  return apiPost("/api/options/tools/earnings-crush", {
    ticker: context.ticker,
    current_iv: currentIv,
    historical_pre_post_iv: [],
  });
}

async function liveUnusualActivity(ticker: string) {
  const context = await loadLiveContext(ticker);
  return apiPost("/api/options/tools/unusual-activity", {
    contracts: context.contracts,
    min_volume_oi_ratio: 2,
    min_volume: 100,
  });
}

async function liveBuildStrategy(ticker: string) {
  const context = await loadLiveContext(ticker);
  return apiPost("/api/options/tools/strategy/build", {
    mode: "template",
    template_id: "bull_call_spread",
    spot: context.spot,
    expiry_days: context.dte,
    strikes: liveStrikes(context),
    iv: context.atmIv ?? 0.3,
    symbol: context.ticker,
  });
}

async function liveEvaluateAlerts(ticker: string) {
  const context = await loadLiveContext(ticker);
  return apiPost("/api/options/tools/alerts/evaluate", {
    alerts: [
      {
        id: "price-plus-5pct",
        ticker: context.ticker,
        type: "price_above",
        threshold: Number((context.spot * 1.05).toFixed(2)),
      },
      {
        id: "iv-rank-high",
        ticker: context.ticker,
        type: "iv_rank_above",
        threshold: 70,
      },
    ],
    context: {
      ticker: context.ticker,
      price: context.spot,
      iv_rank: context.ivRank,
      unusual_activity_count: 0,
    },
  });
}

function daysToExpiry(expiry: string) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const expiryDate = new Date(`${expiry}T00:00:00`);
  if (Number.isNaN(expiryDate.getTime())) {
    return 30;
  }
  return Math.max(1, Math.round((expiryDate.getTime() - today.getTime()) / 86_400_000));
}

function normalizeOptionalIv(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  return value > 5 ? value / 100 : value;
}

function normalizeIv(value: number | null | undefined) {
  return normalizeOptionalIv(value) ?? 0.3;
}

function midPrice(contract: LiveContract) {
  if (
    typeof contract.bid === "number" &&
    typeof contract.ask === "number" &&
    contract.bid > 0 &&
    contract.ask >= contract.bid
  ) {
    return (contract.bid + contract.ask) / 2;
  }
  return typeof contract.last === "number" && contract.last > 0 ? contract.last : null;
}

function GreekGuide({ locale }: { locale: Locale }) {
  const items =
    locale === "zh"
      ? [
          ["Delta", "正股涨 1 美元，期权大约跟着变动多少。"],
          ["Gamma", "Delta 本身变化的速度，越高越容易突然放大盈亏。"],
          ["Theta", "每天大约损耗多少时间价值，买方通常怕它太高。"],
          ["Vega", "IV 上升 1 个百分点时，期权价格大约变动多少。"],
          ["Rho", "利率变化对价格的影响，短期期权通常不是主因。"],
          ["Vanna / Volga", "二阶敏感度，用来观察 IV 与方向变化叠加时的风险。"],
        ]
      : [
          ["Delta", "Approximate option price change for a $1 move in the stock."],
          ["Gamma", "How quickly Delta changes; higher values can amplify P&L faster."],
          ["Theta", "Approximate daily time-value decay. Long option buyers usually want it controlled."],
          ["Vega", "Approximate option price change for a 1 percentage point IV move."],
          ["Rho", "Interest-rate sensitivity. Usually not the main driver for short-dated options."],
          ["Vanna / Volga", "Second-order checks for combined direction and volatility risk."],
        ];
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {items.map(([label, description]) => (
        <div className="rounded-lg border border-border-subtle bg-bg-surface p-3" key={label}>
          <div className="font-label-caps uppercase text-text-primary">{label}</div>
          <p className="mt-1 font-body-sm text-text-secondary">{description}</p>
        </div>
      ))}
    </div>
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
          <div className="mt-0.5 rounded-lg border border-border-subtle bg-surface-container p-2 text-accent-success">
            <Icon size={18} />
          </div>
          <div>
            <h2 className="font-headline-lg text-text-primary">{title}</h2>
            <p className="mt-1 max-w-2xl font-body-sm text-text-secondary">{description}</p>
            {sourceLabel && sourceDescription ? (
              <div className="mt-2 flex max-w-2xl flex-wrap items-center gap-2 rounded-lg border border-info/30 bg-info/5 px-3 py-2 font-body-sm text-text-secondary">
                <span className="rounded-lg border border-info/40 bg-info/10 px-2 py-0.5 font-label-caps uppercase text-info">
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
            className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-accent-success bg-accent-success px-3 py-2 font-label-caps uppercase text-bg-base transition-opacity hover:opacity-90 disabled:opacity-60"
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
        className="h-9 w-28 rounded-lg border border-border-subtle bg-surface-container px-3 font-data-mono uppercase text-text-primary focus:border-accent-success/60 focus:outline-none"
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
        <div className="rounded-lg border border-border-subtle bg-bg-surface p-3" key={index}>
          <div className="font-label-caps uppercase text-text-secondary">{label}</div>
          <div className="mt-2 break-words font-data-mono text-lg font-bold text-text-primary">{formatDisplay(value)}</div>
        </div>
      ))}
    </div>
  );
}

function DataTable({ columns, rows }: { columns: ReactNode[]; rows: ReactNode[][] }) {
  return (
    <Card padded={false} className="overflow-x-auto">
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
            <tr className="border-t border-border-subtle/70 hover:bg-surface-muted/50" key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td className="whitespace-nowrap px-3 py-2 font-data-mono text-text-primary" key={`${rowIndex}-${cellIndex}`}>
                  {formatDisplay(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
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
    <Card>
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
                className={positive ? "w-full rounded-sm bg-accent-success" : "w-full rounded-sm bg-danger"}
                style={{ height: `${height}%` }}
                title={`${num(row.price, 2)} / ${money(row.pnl)}`}
              />
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function SurfaceGrid({ result, t }: { result: OptionsVolSurfaceResponse; t: Copy }) {
  return (
    <div className="space-y-4">
      <MetricGrid
        items={[
          [t.labels.ticker, result.ticker],
          [t.labels.price, money(result.price)],
          [t.labels.shape, result.shape],
        ]}
      />
      <Card padded={false} className="overflow-x-auto">
        <table className="min-w-full border-collapse font-body-sm">
          <thead className="bg-surface-container text-left font-label-caps uppercase text-text-secondary">
            <tr>
              <th className="px-3 py-2">{t.labels.expiry}</th>
              {result.surface.moneyness_axis.map((point) => (
                <th className="px-3 py-2 font-data-mono" key={point}>
                  {num(point, 2)}x
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.surface.expiry_axis.map((expiry, rowIndex) => (
              <tr className="border-t border-border-subtle/70 hover:bg-surface-muted/50" key={expiry}>
                <td className="whitespace-nowrap px-3 py-2 font-data-mono text-text-primary">{expiry}</td>
                {result.surface.iv_grid[rowIndex]?.map((iv, cellIndex) => (
                  <td className="whitespace-nowrap px-3 py-2 font-data-mono text-text-primary" key={`${expiry}-${cellIndex}`}>
                    {pct(iv)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
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
          className="rounded-lg border border-border-subtle bg-bg-surface px-3 py-2 text-left font-body-sm text-text-primary transition-colors hover:border-accent-success/40 hover:bg-surface-container disabled:cursor-not-allowed disabled:opacity-60"
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
    <Card padded={false}>
      <div className="flex items-center justify-between gap-3 border-b border-border-subtle px-4 py-3">
        <h3 className="font-label-caps uppercase text-text-primary">{title}</h3>
        <span className="font-label-caps uppercase text-text-secondary">{responseLabel}</span>
      </div>
      <pre className="max-h-[360px] overflow-auto p-4 font-code-sm text-text-primary">
        {JSON.stringify(payload, null, 2)}
      </pre>
    </Card>
  );
}

function EmptyPrompt({ label }: { label: string }) {
  return (
    <div className="flex min-h-48 items-center justify-center rounded-lg border border-dashed border-border-subtle bg-bg-surface/60 p-6 text-center font-body-sm text-text-secondary">
      {label}
    </div>
  );
}

function ErrorLine({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 font-body-sm text-danger">
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
