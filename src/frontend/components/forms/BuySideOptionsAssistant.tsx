'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiClientError, apiPost } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };

const copy = {
  en: {
    title: "Buy-Side Options Assistant",
    intro: "Read-only Futu option-chain analysis for bullish long-premium structures. No orders, no account unlock, no live trading.",
    zh: "中文",
    thesis: "Trade Thesis",
    market: "Market Snapshot",
    recommendations: "Strategy Recommendations",
    comparison: "Strategy Comparison",
    checklist: "Anti-Pitfall Checklist",
    scenario: "Scenario Lab",
    disclaimer:
      "This tool provides quantitative decision support only and is not financial advice. Options involve risk and may lose value rapidly due to time decay, volatility changes, liquidity, and adverse underlying price movement. Review official options risk disclosures before trading.",
    safety: "Read-only decision support. These outputs are not trade instructions and cannot place orders.",
    ticker: "Ticker",
    viewType: "View type",
    targetPrice: "Target price",
    targetDate: "Target date",
    maxLossBudget: "Max loss budget",
    riskPreference: "Risk preference",
    allowCappedUpside: "Allow capped upside",
    avoidHighIv: "Avoid high IV",
    volatilityView: "Volatility view",
    eventRisk: "Event risk",
    expectedIvChange: "Expected IV change",
    scenarioSpot: "Scenario spot %",
    scenarioIv: "Scenario IV points",
    scenarioDays: "Scenario days",
    run: "Run Assistant",
    running: "Running...",
    empty: "Enter a thesis, then run the assistant to rank Long Call, Bull Call Spread, LEAPS Call, and LEAPS Call Spread candidates.",
    error: "Request failed",
    noMarketData: "not available",
    spot: "Spot",
    timestamp: "Timestamp",
    earnings: "Next event",
    ivRank: "IV rank",
    regime: "Market regime",
    qualityWarnings: "Data warnings",
    score: "Score",
    buyerScore: "Buyer score",
    bestUse: "Best use",
    netDebit: "Net debit",
    maxLoss: "Max loss",
    maxProfit: "Max profit",
    breakEven: "Break-even",
    requiredMove: "Required move",
    expectedMove: "Expected move",
    rewardRisk: "Reward/risk",
    thetaBurn: "Theta burn 7D",
    ivCrush: "IV crush loss",
    liquidity: "Liquidity",
    primaryRisk: "Primary risk",
    reasons: "Reasons",
    risks: "Risks",
    warnings: "Warnings",
    details: "Details",
    subjectiveEv: "Subjective EV",
    subjectiveEvHelp: "User-input subjective EV, not market-implied probability.",
    rows: ["bull", "base", "bear"],
    tableHeadings: [
      "Strategy",
      "Expiration",
      "Strikes",
      "Net debit",
      "Max loss",
      "Max profit",
      "Break-even",
      "Req move",
      "Score",
      "Theta",
      "IV crush",
      "Liquidity",
      "R/R",
      "Key warning",
    ],
    checklistItems: {
      highIv: "IV Rank too high?",
      event: "Crossing earnings/event?",
      theta: "7-day theta burn too high?",
      spread: "Bid-ask spread too wide?",
      breakeven: "Break-even too far?",
      lottery: "Low-delta lottery call?",
      dte: "DTE too short for thesis?",
      budget: "Max loss exceeds budget?",
      ivDependency: "Strategy depends too much on IV staying high?",
      spotUpIvDown: "If direction is right but IV falls, can it still profit?",
    },
    yes: "Yes",
    no: "No",
    unknown: "Unknown",
  },
  zh: {
    title: "买方期权策略助手",
    intro: "基于 Futu 只读期权链，分析看涨买方结构。不下单、不解锁账户、不接入实盘。",
    zh: "English",
    thesis: "交易假设",
    market: "市场快照",
    recommendations: "策略推荐",
    comparison: "策略对比",
    checklist: "避坑清单",
    scenario: "情景实验室",
    disclaimer:
      "本工具仅提供量化决策辅助，不构成投资建议。期权存在风险，可能因时间衰减、波动率变化、流动性和标的反向波动而快速贬值。交易前请阅读正式期权风险披露。",
    safety: "只读决策辅助。这些结果不是交易指令，也不能发出订单。",
    ticker: "标的代码",
    viewType: "观点类型",
    targetPrice: "目标价格",
    targetDate: "目标日期",
    maxLossBudget: "最大亏损预算",
    riskPreference: "风险偏好",
    allowCappedUpside: "允许收益封顶",
    avoidHighIv: "回避高 IV",
    volatilityView: "波动率观点",
    eventRisk: "事件风险",
    expectedIvChange: "预期 IV 变化",
    scenarioSpot: "情景价格变化 %",
    scenarioIv: "情景 IV 点数",
    scenarioDays: "情景天数",
    run: "运行分析",
    running: "分析中...",
    empty: "输入交易假设后运行，系统会排序 Long Call、Bull Call Spread、LEAPS Call 和 LEAPS Call Spread 候选。",
    error: "请求失败",
    noMarketData: "暂无数据",
    spot: "现价",
    timestamp: "时间戳",
    earnings: "最近事件",
    ivRank: "IV Rank",
    regime: "市场状态",
    qualityWarnings: "数据警告",
    score: "总分",
    buyerScore: "买方友好度",
    bestUse: "适用场景",
    netDebit: "净支出",
    maxLoss: "最大亏损",
    maxProfit: "最大收益",
    breakEven: "盈亏平衡",
    requiredMove: "所需涨幅",
    expectedMove: "隐含波动",
    rewardRisk: "收益/风险",
    thetaBurn: "7 天 theta",
    ivCrush: "IV 回落损失",
    liquidity: "流动性",
    primaryRisk: "主要风险",
    reasons: "匹配原因",
    risks: "主要风险",
    warnings: "警告",
    details: "详情",
    subjectiveEv: "主观 EV",
    subjectiveEvHelp: "这是用户输入的主观期望值，不是市场隐含概率。",
    rows: ["看涨", "基准", "看跌"],
    tableHeadings: [
      "策略",
      "到期日",
      "行权价",
      "净支出",
      "最大亏损",
      "最大收益",
      "盈亏平衡",
      "所需涨幅",
      "分数",
      "Theta",
      "IV 回落",
      "流动性",
      "收益/风险",
      "关键警告",
    ],
    checklistItems: {
      highIv: "IV Rank 是否过高？",
      event: "是否跨越财报/事件？",
      theta: "7 天 theta 损耗是否过高？",
      spread: "买卖价差是否过宽？",
      breakeven: "盈亏平衡是否太远？",
      lottery: "是否是低 delta 彩票型期权？",
      dte: "DTE 是否短于观点周期？",
      budget: "最大亏损是否超过预算？",
      ivDependency: "是否过度依赖 IV 维持高位？",
      spotUpIvDown: "方向对但 IV 下降时还能否盈利？",
    },
    yes: "是",
    no: "否",
    unknown: "未知",
  },
};

const schema = z.object({
  ticker: z.string().min(1),
  view_type: z.enum([
    "long_term_aggressive_bullish",
    "long_term_conservative_bullish",
    "short_term_speculative_bullish",
    "short_term_conservative_bullish",
    "event_driven_bullish",
  ]),
  target_price: z.coerce.number().positive(),
  target_date: z.string().min(1),
  max_loss_budget: z.coerce.number().positive(),
  risk_preference: z.enum(["aggressive", "balanced", "conservative"]),
  allow_capped_upside: z.boolean(),
  avoid_high_iv: z.boolean(),
  volatility_view: z.enum(["auto", "prefer_low_iv", "expect_iv_crush", "expect_iv_expansion"]),
  event_risk: z.enum(["none", "earnings", "fomc", "cpi", "product_event", "user_defined"]),
  expected_iv_change_vol_points: z.coerce.number(),
  scenario_spot_changes: z.string().min(1),
  scenario_iv_changes: z.string().min(1),
  scenario_days_passed: z.string().min(1),
  bull_probability: z.coerce.number().min(0).max(1),
  bull_spot_change_pct: z.coerce.number(),
  bull_iv_change_vol_points: z.coerce.number(),
  bull_days_passed: z.coerce.number().int().min(0),
  base_probability: z.coerce.number().min(0).max(1),
  base_spot_change_pct: z.coerce.number(),
  base_iv_change_vol_points: z.coerce.number(),
  base_days_passed: z.coerce.number().int().min(0),
  bear_probability: z.coerce.number().min(0).max(1),
  bear_spot_change_pct: z.coerce.number(),
  bear_iv_change_vol_points: z.coerce.number(),
  bear_days_passed: z.coerce.number().int().min(0),
});

type FormValues = z.infer<typeof schema>;

type StrategyLeg = {
  symbol?: string;
  option_type?: "CALL" | "PUT" | "call" | "put";
  side?: "long" | "short";
  action?: "buy" | "sell";
  expiry?: string;
  expiration?: string;
  strike?: number;
  bid?: number | null;
  ask?: number | null;
  mid_price?: number | null;
  premium?: number | null;
  quantity?: number;
  contract_size?: number;
  dte?: number;
};

type ScenarioSummary = {
  best_case_pnl?: number | null;
  worst_case_pnl?: number | null;
  flat_spot_iv_crush_pnl?: number | null;
  spot_up_iv_down_pnl?: number | null;
  theta_only_pnl?: number | null;
  probability_not_calculated?: boolean;
};

type ScenarioContribution = {
  label: string;
  probability: number;
  pnl: number;
  expected_value_contribution?: number;
  weighted_pnl?: number;
};

type ScenarioEv = {
  expected_value: number;
  contributions: ScenarioContribution[];
};

type Recommendation = {
  strategy_type: string;
  score: number;
  rank: number;
  one_line_summary: string;
  key_reasons: string[];
  key_risks: string[];
  max_loss?: number | null;
  max_profit?: number | null;
  net_debit?: number | null;
  legs?: StrategyLeg[];
  break_even?: number | null;
  required_move_pct?: number | null;
  theta_burn_7d_pct?: number | null;
  estimated_iv_crush_loss_pct?: number | null;
  liquidity_score?: number | null;
  risk_reward?: number | null;
  expected_move_pct?: number | null;
  target_vs_expected_move_ratio?: number | null;
  buyer_friendliness_score?: number | null;
  iv_crash_risk_score?: number | null;
  risk_attribution: Record<"direction" | "time" | "volatility" | "liquidity", number>;
  primary_risk_source: "direction" | "time" | "volatility" | "liquidity";
  market_regime?: string | null;
  market_regime_penalty?: number | null;
  warnings: string[];
  scenario_summary?: ScenarioSummary | null;
  scenario_ev?: ScenarioEv | null;
  demotion_badge?: string | null;
  demotion_reason?: string | null;
};

type AssistantResponse = {
  ticker: string;
  generated_at?: string;
  thesis: {
    ticker: string;
    spot_price: number;
    target_price: number;
    target_date: string;
    max_loss_budget?: number | null;
    iv_rank?: number | null;
    as_of_date?: string | null;
  };
  recommendations: Recommendation[];
  assumptions?: string[];
  warnings?: string[];
  safety?: {
    dry_run: boolean;
    paper_trading: boolean;
    live_trading_enabled: boolean;
    kill_switch: boolean;
  };
};

export function BuySideOptionsAssistant({ locale = "en" }: { locale?: "en" | "zh" }) {
  const hydrated = useIsHydrated();
  const text = copy[locale];
  const [expanded, setExpanded] = useState<number | null>(0);
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      ticker: "AAPL",
      view_type: "short_term_conservative_bullish",
      target_price: 220,
      target_date: "2026-12-31",
      max_loss_budget: 1200,
      risk_preference: "balanced",
      allow_capped_upside: true,
      avoid_high_iv: true,
      volatility_view: "auto",
      event_risk: "none",
      expected_iv_change_vol_points: -5,
      scenario_spot_changes: "-10,0,10,20",
      scenario_iv_changes: "-10,-5,0,5",
      scenario_days_passed: "0,7,14",
      bull_probability: 0.35,
      bull_spot_change_pct: 12,
      bull_iv_change_vol_points: -5,
      bull_days_passed: 14,
      base_probability: 0.45,
      base_spot_change_pct: 4,
      base_iv_change_vol_points: -2,
      base_days_passed: 14,
      bear_probability: 0.2,
      bear_spot_change_pct: -8,
      bear_iv_change_vol_points: 3,
      bear_days_passed: 14,
    },
  });
  const maxLossBudget = useWatch({
    control: form.control,
    name: "max_loss_budget",
  });

  const mutation = useMutation<AssistantResponse, ApiClientError, FormValues>({
    mutationFn: (values) => apiPost<AssistantResponse>("/api/options/buy-side/assistant", toPayload(values)),
    onSuccess: () => toast.success(locale === "zh" ? "买方期权分析完成" : "Buy-side analysis complete"),
    onError: (error) => toast.error(error.message),
  });

  const result = mutation.data;
  const recommendations = useMemo(
    () => result?.recommendations ?? [],
    [result?.recommendations],
  );
  const top = recommendations[0];
  const marketWarnings = useMemo(
    () => [...new Set(recommendations.flatMap((item) => item.warnings ?? []))],
    [recommendations],
  );

  return (
    <div className="grid h-full min-h-0 grid-cols-[380px_1fr] overflow-hidden bg-base text-text-primary">
      <aside className="overflow-y-auto border-r border-border-subtle bg-bg-surface p-4">
        <h1 className="font-headline-lg text-text-primary">{text.title}</h1>
        <p className="mt-2 font-body-sm text-text-secondary">{text.intro}</p>
        <a
          className="mt-3 inline-flex font-body-sm text-info"
          href={locale === "zh" ? "/options-buyside?lang=en" : "/options-buyside?lang=zh"}
        >
          {text.zh}
        </a>

        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((values) => mutation.mutate(values))}>
          <PanelTitle icon={<SlidersHorizontal size={16} />} title={text.thesis} />
          <div className="grid grid-cols-2 gap-3">
            <Field label={text.ticker}>
              <input className={inputClass} {...form.register("ticker")} aria-label={text.ticker} />
            </Field>
            <Field label={text.viewType}>
              <select className={inputClass} {...form.register("view_type")}>
                <option style={optionStyle} value="long_term_aggressive_bullish">Long-term aggressive</option>
                <option style={optionStyle} value="long_term_conservative_bullish">Long-term conservative</option>
                <option style={optionStyle} value="short_term_speculative_bullish">Short-term speculative</option>
                <option style={optionStyle} value="short_term_conservative_bullish">Short-term conservative</option>
                <option style={optionStyle} value="event_driven_bullish">Event-driven</option>
              </select>
            </Field>
            <Field label={text.targetPrice}>
              <input className={inputClass} {...form.register("target_price")} aria-label={text.targetPrice} type="number" step="0.01" />
            </Field>
            <Field label={text.targetDate}>
              <input className={inputClass} {...form.register("target_date")} type="date" />
            </Field>
            <Field label={text.maxLossBudget}>
              <input className={inputClass} {...form.register("max_loss_budget")} type="number" step="1" />
            </Field>
            <Field label={text.riskPreference}>
              <select className={inputClass} {...form.register("risk_preference")}>
                <option style={optionStyle} value="aggressive">Aggressive</option>
                <option style={optionStyle} value="balanced">Balanced</option>
                <option style={optionStyle} value="conservative">Conservative</option>
              </select>
            </Field>
            <Field label={text.volatilityView}>
              <select className={inputClass} {...form.register("volatility_view")}>
                <option style={optionStyle} value="auto">Auto</option>
                <option style={optionStyle} value="prefer_low_iv">Prefer low IV</option>
                <option style={optionStyle} value="expect_iv_crush">Expect IV crush</option>
                <option style={optionStyle} value="expect_iv_expansion">Expect IV expansion</option>
              </select>
            </Field>
            <Field label={text.eventRisk}>
              <select className={inputClass} {...form.register("event_risk")}>
                <option style={optionStyle} value="none">None</option>
                <option style={optionStyle} value="earnings">Earnings</option>
                <option style={optionStyle} value="fomc">FOMC</option>
                <option style={optionStyle} value="cpi">CPI</option>
                <option style={optionStyle} value="product_event">Product event</option>
                <option style={optionStyle} value="user_defined">User defined</option>
              </select>
            </Field>
            <Field label={text.expectedIvChange}>
              <input className={inputClass} {...form.register("expected_iv_change_vol_points")} type="number" step="1" />
            </Field>
            <label className="flex items-center gap-2 pt-6 font-body-sm text-text-secondary">
              <input type="checkbox" {...form.register("allow_capped_upside")} />
              {text.allowCappedUpside}
            </label>
            <label className="flex items-center gap-2 font-body-sm text-text-secondary">
              <input type="checkbox" {...form.register("avoid_high_iv")} />
              {text.avoidHighIv}
            </label>
          </div>

          <PanelTitle icon={<Activity size={16} />} title={text.scenario} />
          <div className="grid grid-cols-1 gap-3">
            <Field label={text.scenarioSpot}>
              <input className={inputClass} {...form.register("scenario_spot_changes")} />
            </Field>
            <Field label={text.scenarioIv}>
              <input className={inputClass} {...form.register("scenario_iv_changes")} />
            </Field>
            <Field label={text.scenarioDays}>
              <input className={inputClass} {...form.register("scenario_days_passed")} />
            </Field>
          </div>
          <div className="rounded border border-border-subtle bg-surface-muted/30 p-3">
            <div className="mb-2 font-label-caps text-text-secondary">{text.subjectiveEv}</div>
            {(["bull", "base", "bear"] as const).map((row) => (
              <div className="mb-2 grid grid-cols-[80px_1fr_1fr_1fr_1fr] gap-2 last:mb-0" key={row}>
                <div className="pt-2 font-body-sm text-text-secondary">{row}</div>
                <input className={inputClass} {...form.register(`${row}_probability`)} aria-label={`${row} probability`} type="number" step="0.01" />
                <input className={inputClass} {...form.register(`${row}_spot_change_pct`)} aria-label={`${row} spot change`} type="number" step="1" />
                <input className={inputClass} {...form.register(`${row}_iv_change_vol_points`)} aria-label={`${row} iv change`} type="number" step="1" />
                <input className={inputClass} {...form.register(`${row}_days_passed`)} aria-label={`${row} days passed`} type="number" step="1" />
              </div>
            ))}
          </div>

          {Object.keys(form.formState.errors).length ? (
            <div className="rounded border border-accent-danger/40 bg-accent-danger/10 p-3 font-body-sm text-accent-danger">
              {locale === "zh" ? "请检查输入参数。" : "Check the input fields."}
            </div>
          ) : null}
          {mutation.error ? (
            <div className="rounded border border-accent-danger/40 bg-accent-danger/10 p-3 font-body-sm text-accent-danger">
              {text.error}: {mutation.error.message}
            </div>
          ) : null}
          <button
            className="w-full rounded bg-accent-success px-4 py-3 font-body-sm font-semibold text-on-primary disabled:opacity-50"
            disabled={!hydrated || mutation.isPending}
            type="submit"
          >
            {mutation.isPending ? text.running : text.run}
          </button>
        </form>
      </aside>

      <main className="min-w-0 overflow-y-auto p-5">
        <div className="mb-4 flex items-center gap-2 rounded border border-warning/40 bg-warning/10 p-3 font-body-sm text-warning">
          <ShieldCheck size={18} />
          {text.safety}
        </div>

        <section className="mb-4 grid grid-cols-2 gap-4 xl:grid-cols-4">
          <SnapshotMetric label={text.spot} value={money(result?.thesis.spot_price)} />
          <SnapshotMetric label={text.timestamp} value={result?.generated_at ?? result?.thesis.as_of_date ?? text.noMarketData} />
          <SnapshotMetric label={text.earnings} value={text.noMarketData} />
          <SnapshotMetric label={text.ivRank} value={score(result?.thesis.iv_rank)} />
        </section>

        <section className="mb-4 grid grid-cols-[1fr_320px] gap-4">
          <div className="rounded border border-border-subtle bg-bg-surface p-4">
            <div className="mb-2 flex items-center justify-between gap-3">
              <h2 className="font-headline-sm text-text-primary">{text.market}</h2>
              <span className={regimeClass(top?.market_regime)}>{top?.market_regime ?? "Unknown"}</span>
            </div>
            <div className="font-body-sm text-text-secondary">
              {marketWarnings.length ? marketWarnings.join(" | ") : text.noMarketData}
            </div>
          </div>
          <div className="rounded border border-border-subtle bg-bg-surface p-4">
            <div className="font-label-caps text-text-secondary">{text.qualityWarnings}</div>
            <div className="mt-2 font-body-sm text-text-secondary">
              {recommendations.length ? `${recommendations.length} ranked structures` : text.empty}
            </div>
          </div>
        </section>

        {mutation.isPending ? (
          <LoadingState />
        ) : recommendations.length === 0 ? (
          <EmptyState text={text.empty} />
        ) : (
          <>
            <SectionHeader title={text.recommendations} />
            <div className="mb-5 grid grid-cols-1 gap-4 xl:grid-cols-2">
              {recommendations.slice(0, 4).map((item, index) => (
                <RecommendationCard
                  expanded={expanded === index}
                  item={item}
                  key={`${item.strategy_type}-${index}`}
                  locale={locale}
                  onToggle={() => setExpanded(expanded === index ? null : index)}
                  text={text}
                />
              ))}
            </div>

            <SectionHeader title={text.comparison} />
            <ComparisonTable recommendations={recommendations} text={text} />

            <SectionHeader title={text.checklist} />
            <Checklist item={top} maxLossBudget={maxLossBudget} text={text} />

            <SectionHeader title={text.scenario} />
            <ScenarioLab item={top} text={text} />
          </>
        )}

        <div className="mt-5 rounded border border-warning/40 bg-warning/10 p-4 font-body-sm leading-relaxed text-warning">
          <AlertTriangle className="mr-2 inline" size={18} />
          {text.disclaimer}
        </div>
      </main>
    </div>
  );
}

const inputClass =
  "w-full rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-sm text-text-primary outline-none focus:border-accent-success";

function Field({ children, label }: { children: ReactNode; label: string }) {
  return (
    <label className="flex flex-col gap-1 font-body-sm text-text-secondary">
      <span>{label}</span>
      {children}
    </label>
  );
}

function PanelTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2 border-t border-border-subtle pt-4 font-label-caps text-text-secondary first:border-t-0 first:pt-0">
      {icon}
      {title}
    </div>
  );
}

function SnapshotMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-3">
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className="mt-2 break-words font-data-mono text-base font-bold text-text-primary">{value}</div>
    </div>
  );
}

function SectionHeader({ title }: { title: string }) {
  return <h2 className="mb-3 mt-6 font-headline-sm text-text-primary">{title}</h2>;
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-8 text-center font-body-sm text-text-secondary">
      {text}
    </div>
  );
}

function LoadingState() {
  return (
    <div className="space-y-3">
      {[0, 1, 2].map((item) => (
        <div className="h-28 animate-pulse rounded border border-border-subtle bg-bg-surface" key={item} />
      ))}
    </div>
  );
}

function RecommendationCard({
  expanded,
  item,
  locale,
  onToggle,
  text,
}: {
  expanded: boolean;
  item: Recommendation;
  locale: "en" | "zh";
  onToggle: () => void;
  text: (typeof copy)["en"];
}) {
  const primary = item.primary_risk_source;
  return (
    <article className="rounded border border-border-subtle bg-bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-label-caps text-text-secondary">#{item.rank}</div>
          <h3 className="mt-1 font-headline-sm text-text-primary">{strategyLabel(item.strategy_type)}</h3>
          <p className="mt-1 font-body-sm text-text-secondary">{item.one_line_summary}</p>
        </div>
        <div className="text-right">
          <div className="font-label-caps text-text-secondary">{text.score}</div>
          <div className="font-data-mono text-2xl font-bold text-accent-success">{num(item.score, 0)}</div>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MiniMetric label={text.buyerScore} value={score(item.buyer_friendliness_score)} accent />
        <MiniMetric label={text.netDebit} value={money(item.net_debit)} />
        <MiniMetric label={text.maxLoss} value={money(item.max_loss)} />
        <MiniMetric label={text.maxProfit} value={money(item.max_profit)} />
        <MiniMetric label={text.breakEven} value={money(item.break_even)} />
        <MiniMetric label={text.requiredMove} value={pct(item.required_move_pct)} />
        <MiniMetric label={text.expectedMove} value={pct(item.expected_move_pct)} />
        <MiniMetric label={text.rewardRisk} value={ratio(item.risk_reward)} />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
        <MiniMetric label={text.thetaBurn} value={pct(item.theta_burn_7d_pct)} />
        <MiniMetric label={text.ivCrush} value={pct(item.estimated_iv_crush_loss_pct)} />
        <MiniMetric label={text.liquidity} value={score(item.liquidity_score)} />
      </div>
      <div className="mt-4">
        <div className="mb-2 flex items-center justify-between font-body-sm">
          <span className="text-text-secondary">{text.primaryRisk}</span>
          <span className="font-data-mono text-warning">{primary}</span>
        </div>
        <RiskBars attribution={item.risk_attribution} primary={primary} />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {item.warnings.length ? (
          item.warnings.map((warning) => <WarningChip key={warning} warning={warning} />)
        ) : (
          <span className="rounded border border-accent-success/40 bg-accent-success/10 px-2 py-1 font-body-sm text-accent-success">
            {locale === "zh" ? "暂无核心警告" : "No core warning"}
          </span>
        )}
        {item.demotion_badge ? <WarningChip warning={item.demotion_badge} /> : null}
      </div>
      <button
        className="mt-4 flex items-center gap-2 font-body-sm text-info"
        onClick={onToggle}
        type="button"
      >
        {text.details}
        <ChevronDown className={expanded ? "rotate-180 transition-transform" : "transition-transform"} size={16} />
      </button>
      {expanded ? (
        <div className="mt-3 grid gap-3 border-t border-border-subtle pt-3 lg:grid-cols-2">
          <ListBlock items={item.key_reasons} title={text.reasons} />
          <ListBlock items={item.key_risks} title={text.risks} />
        </div>
      ) : null}
    </article>
  );
}

function MiniMetric({ accent = false, label, value }: { accent?: boolean; label: string; value: string }) {
  return (
    <div className="rounded border border-border-subtle bg-surface-muted/30 p-2">
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className={`mt-1 font-data-mono text-sm font-bold ${accent ? "text-accent-success" : "text-text-primary"}`}>
        {value}
      </div>
    </div>
  );
}

function RiskBars({
  attribution,
  primary,
}: {
  attribution: Recommendation["risk_attribution"];
  primary: Recommendation["primary_risk_source"];
}) {
  return (
    <div className="grid gap-2">
      {(Object.keys(attribution) as Array<keyof Recommendation["risk_attribution"]>).map((key) => (
        <div className="grid grid-cols-[90px_1fr_42px] items-center gap-2" key={key}>
          <span className={key === primary ? "font-label-caps text-warning" : "font-label-caps text-text-secondary"}>{key}</span>
          <div className="h-2 overflow-hidden rounded bg-surface-muted">
            <div
              className={key === primary ? "h-full bg-warning" : "h-full bg-accent-success"}
              style={{ width: `${Math.min(Math.max(attribution[key], 0), 100)}%` }}
            />
          </div>
          <span className="font-data-mono text-xs text-text-secondary">{num(attribution[key], 0)}</span>
        </div>
      ))}
    </div>
  );
}

function ComparisonTable({
  recommendations,
  text,
}: {
  recommendations: Recommendation[];
  text: (typeof copy)["en"];
}) {
  return (
    <div className="overflow-x-auto rounded border border-border-subtle bg-bg-surface">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-border-subtle">
            {text.tableHeadings.map((heading) => (
              <th className="px-3 py-2 font-label-caps text-text-secondary" key={heading}>{heading}</th>
            ))}
          </tr>
        </thead>
        <tbody className="font-data-mono text-data-mono text-text-primary">
          {recommendations.map((item, index) => (
            <tr className="border-b border-border-subtle/50" key={`${item.strategy_type}-${index}`}>
              <td className="px-3 py-2">{strategyLabel(item.strategy_type)}</td>
              <td className="px-3 py-2">{expirationLabel(item.legs)}</td>
              <td className="px-3 py-2">{strikeLabel(item.legs)}</td>
              <td className="px-3 py-2">{money(item.net_debit)}</td>
              <td className="px-3 py-2">{money(item.max_loss)}</td>
              <td className="px-3 py-2">{money(item.max_profit)}</td>
              <td className="px-3 py-2">{money(item.break_even)}</td>
              <td className="px-3 py-2">{pct(item.required_move_pct)}</td>
              <td className="px-3 py-2">{num(item.score, 0)}</td>
              <td className="px-3 py-2">{pct(item.theta_burn_7d_pct)}</td>
              <td className="px-3 py-2">{pct(item.estimated_iv_crush_loss_pct)}</td>
              <td className="px-3 py-2">{score(item.liquidity_score)}</td>
              <td className="px-3 py-2">{ratio(item.risk_reward)}</td>
              <td className="px-3 py-2">{item.warnings[0] ?? "--"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Checklist({
  item,
  maxLossBudget,
  text,
}: {
  item?: Recommendation;
  maxLossBudget: number;
  text: (typeof copy)["en"];
}) {
  const checks = [
    ["highIv", (item?.iv_crash_risk_score ?? 0) > 70 || hasWarning(item, "HIGH_IV_RANK")],
    ["event", hasWarning(item, "EVENT_RISK")],
    ["theta", highPct(item?.theta_burn_7d_pct, 15) || hasWarning(item, "HIGH_THETA_BURN")],
    ["spread", hasWarning(item, "POOR_LIQUIDITY")],
    ["breakeven", hasWarning(item, "BREAK_EVEN_ABOVE_TARGET")],
    ["lottery", hasWarning(item, "LOTTERY_OPTION")],
    ["dte", minDte(item?.legs) !== null && (minDte(item?.legs) ?? 99) < 14],
    ["budget", item?.max_loss !== undefined && item?.max_loss !== null && item.max_loss > maxLossBudget],
    ["ivDependency", (item?.iv_crash_risk_score ?? 0) > 70],
    ["spotUpIvDown", item?.scenario_summary?.spot_up_iv_down_pnl !== undefined && (item.scenario_summary.spot_up_iv_down_pnl ?? 0) <= 0],
  ] as const;
  return (
    <div className="grid grid-cols-1 gap-2 rounded border border-border-subtle bg-bg-surface p-4 md:grid-cols-2 xl:grid-cols-3">
      {checks.map(([key, value]) => (
        <div className="flex items-center justify-between gap-3 rounded border border-border-subtle bg-surface-muted/30 p-3" key={key}>
          <span className="font-body-sm text-text-secondary">{text.checklistItems[key]}</span>
          <span className={value ? "font-data-mono text-warning" : "font-data-mono text-accent-success"}>
            {value ? text.yes : text.no}
          </span>
        </div>
      ))}
    </div>
  );
}

function ScenarioLab({ item, text }: { item?: Recommendation; text: (typeof copy)["en"] }) {
  const summary = item?.scenario_summary;
  const ev = item?.scenario_ev;
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
      <div className="rounded border border-border-subtle bg-bg-surface p-4">
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
          <MiniMetric label="Best" value={money(summary?.best_case_pnl)} />
          <MiniMetric label="Worst" value={money(summary?.worst_case_pnl)} />
          <MiniMetric label="Flat + IV crush" value={money(summary?.flat_spot_iv_crush_pnl)} />
          <MiniMetric label="Spot up + IV down" value={money(summary?.spot_up_iv_down_pnl)} />
          <MiniMetric label="Theta only" value={money(summary?.theta_only_pnl)} />
        </div>
        <p className="mt-3 font-body-sm text-text-secondary">
          Greek approximation only. Reliability falls for large spot moves, long time passed, and near-expiration theta acceleration.
        </p>
      </div>
      <div className="rounded border border-border-subtle bg-bg-surface p-4">
        <div className="mb-1 font-label-caps text-text-secondary">{text.subjectiveEv}</div>
        <div className="mb-3 font-body-sm text-text-secondary">{text.subjectiveEvHelp}</div>
        <div className="font-data-mono text-xl font-bold text-accent-success">{money(ev?.expected_value)}</div>
        <div className="mt-3 space-y-2">
          {ev?.contributions?.length ? (
            ev.contributions.map((item) => (
              <div className="grid grid-cols-[1fr_70px_70px] gap-2 font-data-mono text-sm" key={item.label}>
                <span>{item.label}</span>
                <span>{pct(item.probability)}</span>
                <span>{money(item.expected_value_contribution ?? item.weighted_pnl)}</span>
              </div>
            ))
          ) : (
            <div className="font-body-sm text-text-secondary">--</div>
          )}
        </div>
      </div>
    </div>
  );
}

function ListBlock({ items, title }: { items: string[]; title: string }) {
  return (
    <div>
      <div className="mb-2 font-label-caps text-text-secondary">{title}</div>
      <ul className="space-y-1 font-body-sm text-text-secondary">
        {items.length ? (
          items.map((item) => (
            <li className="flex gap-2" key={item}>
              <CheckCircle2 className="mt-0.5 shrink-0 text-accent-success" size={14} />
              <span>{item}</span>
            </li>
          ))
        ) : (
          <li>--</li>
        )}
      </ul>
    </div>
  );
}

function WarningChip({ warning }: { warning: string }) {
  return (
    <span className="rounded border border-warning/40 bg-warning/10 px-2 py-1 font-body-sm text-warning">
      {warning}
    </span>
  );
}

function toPayload(values: FormValues) {
  return {
    ticker: values.ticker.trim().toUpperCase(),
    view_type: values.view_type,
    target_price: values.target_price,
    target_date: values.target_date,
    max_loss_budget: values.max_loss_budget,
    risk_preference: values.risk_preference,
    allow_capped_upside: values.allow_capped_upside,
    avoid_high_iv: values.avoid_high_iv,
    volatility_view: values.volatility_view,
    event_risk: values.event_risk,
    expected_iv_change_vol_points: values.expected_iv_change_vol_points,
    scenario_spot_changes: numberList(values.scenario_spot_changes),
    scenario_iv_changes: numberList(values.scenario_iv_changes),
    scenario_days_passed: numberList(values.scenario_days_passed).map((item) => Math.max(0, Math.round(item))),
    user_scenarios: [
      {
        label: "bull",
        probability: values.bull_probability,
        spot_change_pct: values.bull_spot_change_pct,
        iv_change_vol_points: values.bull_iv_change_vol_points,
        days_passed: values.bull_days_passed,
      },
      {
        label: "base",
        probability: values.base_probability,
        spot_change_pct: values.base_spot_change_pct,
        iv_change_vol_points: values.base_iv_change_vol_points,
        days_passed: values.base_days_passed,
      },
      {
        label: "bear",
        probability: values.bear_probability,
        spot_change_pct: values.bear_spot_change_pct,
        iv_change_vol_points: values.bear_iv_change_vol_points,
        days_passed: values.bear_days_passed,
      },
    ],
  };
}

function numberList(value: string) {
  const parsed = value
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item));
  return parsed.length ? parsed : [0];
}

function strategyLabel(strategy: string) {
  return {
    long_call: "Long Call",
    bull_call_spread: "Bull Call Spread",
    leaps_call: "LEAPS Call",
    leaps_call_spread: "LEAPS Call Spread",
  }[strategy] ?? strategy;
}

function money(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: Math.abs(value) >= 100 ? 0 : 2,
  }).format(value);
}

function num(value?: number | null, digits = 1) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function score(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(0)}/100` : "--";
}

function pct(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  const normalized = Math.abs(value) > 1.5 ? value : value * 100;
  return `${normalized.toFixed(1)}%`;
}

function ratio(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)}x` : "--";
}

function highPct(value: number | null | undefined, thresholdPct: number) {
  if (typeof value !== "number") return false;
  const normalized = Math.abs(value) > 1.5 ? value : value * 100;
  return normalized > thresholdPct;
}

function expirationLabel(legs?: StrategyLeg[]) {
  const expirations = [...new Set((legs ?? []).map((leg) => leg.expiry ?? leg.expiration).filter(Boolean))];
  return expirations.length ? expirations.join(" / ") : "--";
}

function strikeLabel(legs?: StrategyLeg[]) {
  const strikes = (legs ?? []).map((leg) => leg.strike).filter((item): item is number => typeof item === "number");
  return strikes.length ? strikes.map((item) => item.toFixed(0)).join(" / ") : "--";
}

function minDte(legs?: StrategyLeg[]) {
  const values = (legs ?? []).map((leg) => leg.dte).filter((item): item is number => typeof item === "number");
  return values.length ? Math.min(...values) : null;
}

function hasWarning(item: Recommendation | undefined, warning: string) {
  return item?.warnings?.includes(warning) ?? false;
}

function regimeClass(regime?: string | null) {
  if (regime === "Panic") {
    return "rounded border border-accent-danger/40 bg-accent-danger/10 px-2 py-1 font-data-mono text-sm text-accent-danger";
  }
  if (regime === "Elevated") {
    return "rounded border border-warning/40 bg-warning/10 px-2 py-1 font-data-mono text-sm text-warning";
  }
  if (regime === "Normal") {
    return "rounded border border-accent-success/40 bg-accent-success/10 px-2 py-1 font-data-mono text-sm text-accent-success";
  }
  return "rounded border border-border-subtle bg-surface-muted px-2 py-1 font-data-mono text-sm text-text-secondary";
}
