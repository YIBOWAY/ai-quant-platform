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
import { useEffect, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import type {
  BuySideAssistantResponse,
  BuySideRecommendation,
  BuySideStrategyLeg,
} from "@/lib/api";
import { ApiClientError, apiPost } from "@/lib/apiClient";
import { buildBuySideOptionsPayload } from "@/lib/buySideOptionsPayload";
import { InfoTip, type GlossaryKey } from "@/components/InfoTip";
import {
  Card,
  MetricStat,
  SectionTitle,
  StatusPill,
  TerminalToolbarButton,
  terminalInputClass,
} from "@/components/ui/primitives";
import { useIsHydrated } from "@/lib/hydration";

const copy = {
  en: {
    title: "Buy-Side Options Assistant",
    intro: "Read-only Futu option-chain analysis for bullish long-premium structures. No orders, no account unlock, no live trading.",
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
    riskPreference: "Risk preference",
    allowCappedUpside: "Allow capped upside",
    avoidHighIv: "Avoid high IV",
    volatilityView: "Volatility view",
    eventRisk: "Event risk",
    expectedIvChange: "Expected IV change",
    scenarioSpot: "Scenario spot %",
    scenarioIv: "Scenario IV point change",
    scenarioHorizon: "Scenario horizon date",
    scenarioHorizonHelp: "The lab converts this date into 0 / midpoint / horizon-day checks.",
    run: "Run Assistant",
    running: "Running...",
    empty: "Enter a thesis, then run the assistant to rank Long Call, Bull Call Spread, LEAPS Call, and LEAPS Call Spread candidates.",
    error: "Request failed",
    noMarketData: "not available",
    dataSource: "Data source",
    dataSourceValue: "Backend Futu option chain",
    spot: "Spot",
    timestamp: "Timestamp",
    earnings: "Next event",
    ivRank: "IV rank",
    regime: "Market regime",
    qualityWarnings: "Data warnings",
    rankedStructures: (n: number) => `${n} ranked structures from backend option-chain data`,
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
    subjectiveEvHelp: "Enter subjective scenario probabilities. This is your own expected value estimate, not a market-implied probability.",
    evProbability: "Prob.",
    evSpot: "Spot %",
    evIv: "IV pts",
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
      ivDependency: "Strategy depends too much on IV staying high?",
      spotUpIvDown: "If direction is right but IV falls, can it still profit?",
    },
    yes: "Yes",
    no: "No",
    unknown: "Unknown",
    noWarning: "No core warning",
    scenarioGreekNote:
      "Greek approximation only. Reliability falls for large spot moves, long time passed, and near-expiration theta acceleration.",
    scenarioLabels: {
      best: "Best case",
      worst: "Worst case",
      flatCrush: "Flat + IV crush",
      spotUpIvDown: "Spot up + IV down",
      thetaOnly: "Theta only",
    },
    contracts: "Selected contracts",
    runHint: "Read-only. No orders are placed.",
  },
  zh: {
    title: "买方期权策略助手",
    intro: "基于 Futu 只读期权链，分析看涨买方结构。不下单、不解锁账户、不接入实盘。",
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
    scenarioIv: "情景 IV 点数变化",
    scenarioHorizon: "情景目标日期",
    scenarioHorizonHelp: "系统会自动转换为 0 天 / 中点 / 目标日的检查。",
    run: "运行分析",
    running: "分析中...",
    empty: "输入交易假设后运行，系统会排序 Long Call、Bull Call Spread、LEAPS Call 和 LEAPS Call Spread 候选。",
    error: "请求失败",
    noMarketData: "暂无数据",
    dataSource: "数据来源",
    dataSourceValue: "后端 Futu 期权链",
    spot: "现价",
    timestamp: "时间戳",
    earnings: "最近事件",
    ivRank: "IV Rank",
    regime: "市场状态",
    qualityWarnings: "数据警告",
    rankedStructures: (n: number) => `${n} 个结构，来自后端期权链数据`,
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
    subjectiveEvHelp: "输入你自己的看涨 / 基准 / 看跌概率，用于测算主观期望值。这不是市场隐含概率。",
    evProbability: "概率",
    evSpot: "价格 %",
    evIv: "IV 点",
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
      ivDependency: "是否过度依赖 IV 维持高位？",
      spotUpIvDown: "方向对但 IV 下降时还能否盈利？",
    },
    yes: "是",
    no: "否",
    unknown: "未知",
    noWarning: "暂无核心警告",
    scenarioGreekNote:
      "仅为希腊字母近似估算。在价格大幅波动、时间推移较久、临近到期 theta 加速时可靠性下降。",
    scenarioLabels: {
      best: "最好情形",
      worst: "最坏情形",
      flatCrush: "横盘 + IV 回落",
      spotUpIvDown: "上涨 + IV 下降",
      thetaOnly: "仅 theta",
    },
    contracts: "所选合约",
    runHint: "只读，不会下单。",
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
  risk_preference: z.enum(["aggressive", "balanced", "conservative"]),
  allow_capped_upside: z.boolean(),
  avoid_high_iv: z.boolean(),
  volatility_view: z.enum(["auto", "prefer_low_iv", "expect_iv_crush", "expect_iv_expansion"]),
  event_risk: z.enum(["none", "earnings", "fomc", "cpi", "product_event", "user_defined"]),
  expected_iv_change_vol_points: z.coerce.number(),
  scenario_spot_changes: z.string().min(1),
  scenario_iv_changes: z.string().min(1),
  scenario_horizon_date: z.string().min(1),
  bull_probability: z.coerce.number().min(0).max(1),
  bull_spot_change_pct: z.coerce.number(),
  bull_iv_change_vol_points: z.coerce.number(),
  base_probability: z.coerce.number().min(0).max(1),
  base_spot_change_pct: z.coerce.number(),
  base_iv_change_vol_points: z.coerce.number(),
  bear_probability: z.coerce.number().min(0).max(1),
  bear_spot_change_pct: z.coerce.number(),
  bear_iv_change_vol_points: z.coerce.number(),
});

type FormValues = z.infer<typeof schema>;

const viewPresets: Record<FormValues["view_type"], Partial<FormValues>> = {
  long_term_aggressive_bullish: {
    risk_preference: "aggressive",
    allow_capped_upside: false,
    avoid_high_iv: false,
    volatility_view: "auto",
    event_risk: "none",
    expected_iv_change_vol_points: -5,
    target_date: addDaysIso(540),
    scenario_horizon_date: addDaysIso(180),
    scenario_spot_changes: "-20,-10,0,10,20,30",
    scenario_iv_changes: "-15,-10,-5,0,5",
  },
  long_term_conservative_bullish: {
    risk_preference: "conservative",
    allow_capped_upside: true,
    avoid_high_iv: true,
    volatility_view: "prefer_low_iv",
    event_risk: "none",
    expected_iv_change_vol_points: -5,
    target_date: addDaysIso(540),
    scenario_horizon_date: addDaysIso(180),
    scenario_spot_changes: "-15,-5,0,8,15,25",
    scenario_iv_changes: "-15,-10,-5,0,5",
  },
  short_term_speculative_bullish: {
    risk_preference: "aggressive",
    allow_capped_upside: false,
    avoid_high_iv: false,
    volatility_view: "expect_iv_expansion",
    event_risk: "none",
    expected_iv_change_vol_points: 5,
    target_date: addDaysIso(45),
    scenario_horizon_date: addDaysIso(30),
    scenario_spot_changes: "-15,-5,0,10,20,30",
    scenario_iv_changes: "-10,-5,0,5,10",
  },
  short_term_conservative_bullish: {
    risk_preference: "balanced",
    allow_capped_upside: true,
    avoid_high_iv: true,
    volatility_view: "auto",
    event_risk: "none",
    expected_iv_change_vol_points: -5,
    target_date: addDaysIso(60),
    scenario_horizon_date: addDaysIso(45),
    scenario_spot_changes: "-10,-5,0,5,10,20",
    scenario_iv_changes: "-10,-5,0,5",
  },
  event_driven_bullish: {
    risk_preference: "balanced",
    allow_capped_upside: true,
    avoid_high_iv: true,
    volatility_view: "expect_iv_crush",
    event_risk: "earnings",
    expected_iv_change_vol_points: -10,
    target_date: addDaysIso(30),
    scenario_horizon_date: addDaysIso(14),
    scenario_spot_changes: "-20,-10,0,10,20,30",
    scenario_iv_changes: "-20,-10,-5,0,5",
  },
};

export function BuySideOptionsAssistant({ locale = "en" }: { locale?: "en" | "zh" }) {
  const hydrated = useIsHydrated();
  const text = copy[locale];
  const [expanded, setExpanded] = useState<number[]>([0]);
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      ticker: "AAPL",
      view_type: "short_term_conservative_bullish",
      target_price: 330,
      target_date: addDaysIso(60),
      risk_preference: "balanced",
      allow_capped_upside: true,
      avoid_high_iv: true,
      volatility_view: "auto",
      event_risk: "none",
      expected_iv_change_vol_points: -5,
      scenario_spot_changes: "-10,0,10,20",
      scenario_iv_changes: "-10,-5,0,5",
      scenario_horizon_date: addDaysIso(45),
      bull_probability: 0.35,
      bull_spot_change_pct: 12,
      bull_iv_change_vol_points: -5,
      base_probability: 0.45,
      base_spot_change_pct: 4,
      base_iv_change_vol_points: -2,
      bear_probability: 0.2,
      bear_spot_change_pct: -8,
      bear_iv_change_vol_points: 3,
    },
  });
  const viewType = useWatch({
    control: form.control,
    name: "view_type",
  });

  useEffect(() => {
    const preset = viewPresets[viewType];
    Object.entries(preset).forEach(([key, value]) => {
      form.setValue(key as keyof FormValues, value, {
        shouldDirty: false,
        shouldValidate: true,
      });
    });
  }, [form, viewType]);

  const mutation = useMutation<BuySideAssistantResponse, ApiClientError, FormValues>({
    mutationFn: (values) =>
      apiPost<BuySideAssistantResponse>(
        "/api/options/buy-side/assistant",
        buildBuySideOptionsPayload(values),
      ),
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
    <div className="grid h-full min-h-0 grid-cols-1 overflow-hidden bg-bg-base text-text-primary lg:grid-cols-[380px_1fr]">
      <aside className="flex min-h-0 flex-col overflow-y-auto border-b border-border-subtle bg-bg-surface lg:border-b-0 lg:border-r">
        <div className="border-b border-border-subtle p-4">
          <p className="font-label-caps uppercase text-text-secondary">
            {locale === "zh" ? "买方期权" : "Buy-Side Options"}
          </p>
          <h1 className="mt-1 font-headline-lg text-text-primary">{text.title}</h1>
          <p className="mt-2 font-body-sm leading-relaxed text-text-secondary">{text.intro}</p>
          <div className="mt-3">
            <StatusPill label="" value={text.runHint} tone="info" />
          </div>
        </div>

        <form className="space-y-5 p-4" onSubmit={form.handleSubmit((values) => mutation.mutate(values))}>
          <PanelTitle icon={<SlidersHorizontal size={16} />} title={text.thesis} />
          <div className="grid grid-cols-2 gap-3">
            <Field label={text.ticker}>
              <input className={inputClass} {...form.register("ticker")} aria-label={text.ticker} />
            </Field>
            <Field label={text.viewType}>
              <select className={inputClass} {...form.register("view_type")}>
                <option value="long_term_aggressive_bullish">{viewTypeLabel("long_term_aggressive_bullish", locale)}</option>
                <option value="long_term_conservative_bullish">{viewTypeLabel("long_term_conservative_bullish", locale)}</option>
                <option value="short_term_speculative_bullish">{viewTypeLabel("short_term_speculative_bullish", locale)}</option>
                <option value="short_term_conservative_bullish">{viewTypeLabel("short_term_conservative_bullish", locale)}</option>
                <option value="event_driven_bullish">{viewTypeLabel("event_driven_bullish", locale)}</option>
              </select>
            </Field>
            <Field label={text.targetPrice}>
              <input className={inputClass} {...form.register("target_price")} aria-label={text.targetPrice} type="number" step="0.01" />
            </Field>
            <Field label={text.targetDate}>
              <input className={inputClass} {...form.register("target_date")} type="date" />
            </Field>
            <Field label={text.riskPreference}>
              <select className={inputClass} {...form.register("risk_preference")}>
                <option value="aggressive">{riskPreferenceLabel("aggressive", locale)}</option>
                <option value="balanced">{riskPreferenceLabel("balanced", locale)}</option>
                <option value="conservative">{riskPreferenceLabel("conservative", locale)}</option>
              </select>
            </Field>
            <Field label={text.volatilityView}>
              <select className={inputClass} {...form.register("volatility_view")}>
                <option value="auto">{volatilityViewLabel("auto", locale)}</option>
                <option value="prefer_low_iv">{volatilityViewLabel("prefer_low_iv", locale)}</option>
                <option value="expect_iv_crush">{volatilityViewLabel("expect_iv_crush", locale)}</option>
                <option value="expect_iv_expansion">{volatilityViewLabel("expect_iv_expansion", locale)}</option>
              </select>
            </Field>
            <Field label={text.eventRisk}>
              <select className={inputClass} {...form.register("event_risk")}>
                <option value="none">{eventRiskLabel("none", locale)}</option>
                <option value="earnings">{eventRiskLabel("earnings", locale)}</option>
                <option value="fomc">{eventRiskLabel("fomc", locale)}</option>
                <option value="cpi">{eventRiskLabel("cpi", locale)}</option>
                <option value="product_event">{eventRiskLabel("product_event", locale)}</option>
                <option value="user_defined">{eventRiskLabel("user_defined", locale)}</option>
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
            <Field label={text.scenarioHorizon}>
              <input className={inputClass} {...form.register("scenario_horizon_date")} type="date" />
              <span className="font-body-sm text-text-secondary">{text.scenarioHorizonHelp}</span>
            </Field>
          </div>
          <div className="rounded-lg border border-border-subtle bg-bg-surface-muted/30 p-3">
            <div className="mb-2 font-label-caps text-text-secondary">{text.subjectiveEv}</div>
            <p className="mb-3 font-body-sm leading-relaxed text-text-secondary">{text.subjectiveEvHelp}</p>
            <div className="mb-1 grid grid-cols-[70px_1fr_1fr_1fr] gap-2 font-label-caps text-text-secondary">
              <span />
              <span>{text.evProbability}</span>
              <span>{text.evSpot}</span>
              <span>{text.evIv}</span>
            </div>
            {(["bull", "base", "bear"] as const).map((row) => (
              <div className="mb-2 grid grid-cols-[70px_1fr_1fr_1fr] gap-2 last:mb-0" key={row}>
                <div className="pt-2 font-body-sm text-text-secondary">{scenarioRowLabel(row, locale)}</div>
                <input className={inputClass} {...form.register(`${row}_probability`)} aria-label={`${row} probability`} type="number" step="0.01" />
                <input className={inputClass} {...form.register(`${row}_spot_change_pct`)} aria-label={`${row} spot change`} type="number" step="1" />
                <input className={inputClass} {...form.register(`${row}_iv_change_vol_points`)} aria-label={`${row} iv change`} type="number" step="1" />
              </div>
            ))}
          </div>

          {Object.keys(form.formState.errors).length ? (
            <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 font-body-sm text-danger">
              {locale === "zh" ? "请检查输入参数。" : "Check the input fields."}
            </div>
          ) : null}
          {mutation.error ? (
            <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 font-body-sm text-danger">
              {text.error}: {mutation.error.message}
            </div>
          ) : null}
          <TerminalToolbarButton
            className="h-11 w-full justify-center"
            disabled={!hydrated || mutation.isPending}
            tone="info"
            type="submit"
          >
            {mutation.isPending ? text.running : text.run}
          </TerminalToolbarButton>
        </form>
      </aside>

      <main className="min-w-0 overflow-y-auto p-5">
        <Card tone="warning" padded className="mb-4 flex items-center gap-2 font-body-sm text-warning">
          <ShieldCheck className="shrink-0" size={18} />
          {text.safety}
        </Card>

        <section className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
          <MetricStat label={text.spot} value={money(result?.thesis.spot_price)} tone="neutral" />
          <MetricStat label={text.dataSource} value={result ? text.dataSourceValue : text.noMarketData} />
          <MetricStat label={text.timestamp} value={result?.generated_at ?? result?.thesis.as_of_date ?? text.noMarketData} />
          <MetricStat label={text.earnings} value={text.noMarketData} />
          <SnapshotMetric label={text.ivRank} value={score(result?.thesis.iv_rank)} tip="ivRank" locale={locale} />
        </section>

        <section className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-[1fr_320px]">
          <Card padded>
            <div className="mb-2 flex items-center justify-between gap-3">
              <h2 className="font-label-caps text-text-primary">{text.market}</h2>
              <StatusPill label="" value={top?.market_regime ?? text.unknown} tone={regimeTone(top?.market_regime)} />
            </div>
            <div className="font-body-sm text-text-secondary">
              {marketWarnings.length ? marketWarnings.join(" · ") : text.noMarketData}
            </div>
          </Card>
          <Card padded>
            <div className="font-label-caps text-text-secondary">{text.qualityWarnings}</div>
            <div className="mt-2 font-body-sm text-text-secondary">
              {recommendations.length ? text.rankedStructures(recommendations.length) : text.empty}
            </div>
          </Card>
        </section>

        {mutation.isPending ? (
          <LoadingState />
        ) : recommendations.length === 0 ? (
          <EmptyState text={text.empty} />
        ) : (
          <div className="space-y-6">
            <div>
              <SectionTitle title={text.recommendations} />
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                {recommendations.slice(0, 4).map((item, index) => (
                  <RecommendationCard
                    expanded={expanded.includes(index)}
                    item={item}
                    key={`${item.strategy_type}-${index}`}
                    locale={locale}
                    onToggle={() =>
                      setExpanded((current) =>
                        current.includes(index)
                          ? current.filter((item) => item !== index)
                          : [...current, index],
                      )
                    }
                    text={text}
                  />
                ))}
              </div>
            </div>

            <div>
              <SectionTitle title={text.comparison} />
              <ComparisonTable recommendations={recommendations} text={text} />
            </div>

            <div>
              <SectionTitle title={text.checklist} />
              <Checklist item={top} text={text} />
            </div>

            <div>
              <SectionTitle title={text.scenario} />
              <ScenarioLab item={top} text={text} />
            </div>
          </div>
        )}

        <Card tone="warning" padded className="mt-6 font-body-sm leading-relaxed text-warning">
          <AlertTriangle className="mr-2 inline" size={18} />
          {text.disclaimer}
        </Card>
      </main>
    </div>
  );
}

const inputClass =
  `${terminalInputClass} w-full text-sm`;

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

function SnapshotMetric({ label, value, tip, locale = "en" }: { label: string; value: string; tip?: GlossaryKey; locale?: "en" | "zh" }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface p-3">
      <div className="flex items-center gap-1 font-label-caps text-text-secondary">
        {label}
        {tip ? <InfoTip term={tip} locale={locale} /> : null}
      </div>
      <div className="mt-2 break-words font-data-mono text-lg font-bold text-text-primary">{value}</div>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border-subtle bg-bg-surface/70 p-8 text-center font-body-sm text-text-secondary">
      {text}
    </div>
  );
}

function LoadingState() {
  return (
    <div className="space-y-3">
      {[0, 1, 2].map((item) => (
        <div className="h-28 animate-pulse rounded-lg border border-border-subtle bg-bg-surface" key={item} />
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
  item: BuySideRecommendation;
  locale: "en" | "zh";
  onToggle: () => void;
  text: (typeof copy)["en"];
}) {
  const primary = item.primary_risk_source;
  return (
    <Card padded className="flex flex-col">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <StatusPill label="#" value={item.rank} tone="neutral" />
          <h3 className="mt-2 font-headline-lg text-text-primary">{strategyLabel(item.strategy_type)}</h3>
          <p className="mt-1 font-body-sm text-text-secondary">{item.one_line_summary}</p>
        </div>
        <div className="shrink-0 text-right">
          <div className="font-label-caps text-text-secondary">{text.score}</div>
          <div className="font-data-mono text-2xl font-bold text-accent-success">{num(item.score, 0)}</div>
        </div>
      </div>
      <SelectedContracts legs={item.legs ?? []} locale={locale} />
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MiniMetric label={text.buyerScore} value={score(item.buyer_friendliness_score)} accent />
        <MiniMetric label={text.netDebit} value={money(item.net_debit)} />
        <MiniMetric label={text.maxLoss} value={money(item.max_loss)} />
        <MiniMetric label={text.maxProfit} value={money(item.max_profit)} />
        <MiniMetric label={text.breakEven} value={money(item.break_even)} tip="breakEven" locale={locale} />
        <MiniMetric label={text.requiredMove} value={pct(item.required_move_pct)} tip="requiredMove" locale={locale} />
        <MiniMetric label={text.expectedMove} value={pct(item.expected_move_pct)} />
        <MiniMetric label={text.rewardRisk} value={ratio(item.risk_reward)} tip="rewardRisk" locale={locale} />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
        <MiniMetric label={text.thetaBurn} value={pct(item.theta_burn_7d_pct)} tip="thetaBurn" locale={locale} />
        <MiniMetric label={text.ivCrush} value={pct(item.estimated_iv_crush_loss_pct)} tip="ivCrush" locale={locale} />
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
          <span className="rounded-lg border border-accent-success/40 bg-accent-success/10 px-2 py-1 font-body-sm text-accent-success">
            {text.noWarning}
          </span>
        )}
        {item.demotion_badge ? <WarningChip warning={item.demotion_badge} /> : null}
      </div>
      <button
        className="mt-4 flex items-center gap-2 font-body-sm text-info hover:text-text-primary"
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
    </Card>
  );
}

function MiniMetric({ accent = false, label, value, tip, locale = "en" }: { accent?: boolean; label: string; value: string; tip?: GlossaryKey; locale?: "en" | "zh" }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface-muted/30 p-2">
      <div className="flex items-center gap-1 font-label-caps text-text-secondary">
        {label}
        {tip ? <InfoTip term={tip} locale={locale} /> : null}
      </div>
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
  attribution: BuySideRecommendation["risk_attribution"];
  primary: BuySideRecommendation["primary_risk_source"];
}) {
  return (
    <div className="grid gap-2">
      {(Object.keys(attribution) as Array<keyof BuySideRecommendation["risk_attribution"]>).map((key) => (
        <div className="grid grid-cols-[90px_1fr_42px] items-center gap-2" key={key}>
          <span className={key === primary ? "font-label-caps text-warning" : "font-label-caps text-text-secondary"}>{key}</span>
          <div className="h-2 overflow-hidden rounded-full bg-bg-surface-muted">
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
  recommendations: BuySideRecommendation[];
  text: (typeof copy)["en"];
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border-subtle bg-bg-surface">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-border-subtle">
            {text.tableHeadings.map((heading) => (
              <th className="whitespace-nowrap px-3 py-2 font-label-caps text-text-secondary" key={heading}>{heading}</th>
            ))}
          </tr>
        </thead>
        <tbody className="font-data-mono text-data-mono text-text-primary">
          {recommendations.map((item, index) => (
            <tr className="border-b border-border-subtle/50 last:border-b-0 hover:bg-bg-surface-muted/30" key={`${item.strategy_type}-${index}`}>
              <td className="whitespace-nowrap px-3 py-2">{strategyLabel(item.strategy_type)}</td>
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
  text,
}: {
  item?: BuySideRecommendation;
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
    ["ivDependency", (item?.iv_crash_risk_score ?? 0) > 70],
    ["spotUpIvDown", item?.scenario_summary?.spot_up_iv_down_pnl !== undefined && (item.scenario_summary.spot_up_iv_down_pnl ?? 0) <= 0],
  ] as const;
  return (
    <div className="grid grid-cols-1 gap-2 rounded-lg border border-border-subtle bg-bg-surface p-4 md:grid-cols-2 xl:grid-cols-3">
      {checks.map(([key, value]) => (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-border-subtle bg-bg-surface-muted/30 p-3" key={key}>
          <span className="font-body-sm text-text-secondary">{text.checklistItems[key]}</span>
          <StatusPill label="" value={value ? text.yes : text.no} tone={value ? "warning" : "success"} />
        </div>
      ))}
    </div>
  );
}

function ScenarioLab({ item, text }: { item?: BuySideRecommendation; text: (typeof copy)["en"] }) {
  const summary = item?.scenario_summary;
  const ev = item?.scenario_ev;
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
      <Card padded>
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
          <MiniMetric label={text.scenarioLabels.best} value={money(summary?.best_case_pnl)} accent />
          <MiniMetric label={text.scenarioLabels.worst} value={money(summary?.worst_case_pnl)} />
          <MiniMetric label={text.scenarioLabels.flatCrush} value={money(summary?.flat_spot_iv_crush_pnl)} />
          <MiniMetric label={text.scenarioLabels.spotUpIvDown} value={money(summary?.spot_up_iv_down_pnl)} />
          <MiniMetric label={text.scenarioLabels.thetaOnly} value={money(summary?.theta_only_pnl)} />
        </div>
        <p className="mt-3 font-body-sm leading-relaxed text-text-secondary">
          {text.scenarioGreekNote}
        </p>
      </Card>
      <Card padded>
        <div className="mb-1 font-label-caps text-text-secondary">{text.subjectiveEv}</div>
        <div className="mb-3 font-body-sm text-text-secondary">{text.subjectiveEvHelp}</div>
        <div className="font-data-mono text-xl font-bold text-accent-success">{money(ev?.expected_value)}</div>
        <div className="mt-3 space-y-2">
          {ev?.contributions?.length ? (
            ev.contributions.map((item) => (
              <div className="grid grid-cols-[1fr_70px_70px] gap-2 font-data-mono text-sm" key={item.label}>
                <span className="text-text-secondary">{item.label}</span>
                <span>{pct(item.probability)}</span>
                <span>{money(item.expected_value_contribution ?? item.weighted_pnl)}</span>
              </div>
            ))
          ) : (
            <div className="font-body-sm text-text-secondary">--</div>
          )}
        </div>
      </Card>
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
    <span className="rounded-lg border border-warning/40 bg-warning/10 px-2 py-1 font-data-mono text-[10px] uppercase text-warning">
      {warning}
    </span>
  );
}

function SelectedContracts({
  legs,
  locale,
}: {
  legs: BuySideStrategyLeg[];
  locale: "en" | "zh";
}) {
  if (!legs.length) {
    return null;
  }
  return (
    <div className="mt-4 rounded-lg border border-border-subtle bg-bg-surface-muted/30 p-3">
      <div className="mb-2 font-label-caps text-text-secondary">
        {locale === "zh" ? "所选合约" : "Selected contracts"}
      </div>
      <div className="grid gap-2">
        {legs.map((leg, index) => (
          <div
            className="grid grid-cols-[64px_1fr_88px] items-center gap-3 rounded-lg border border-border-subtle/70 bg-bg-surface px-3 py-2"
            key={`${leg.symbol ?? index}-${leg.side ?? leg.action ?? index}`}
          >
            <span className={legActionClass(leg)}>{legActionLabel(leg, locale)}</span>
            <div className="min-w-0">
              <div className="truncate font-data-mono text-sm text-text-primary">
                {leg.symbol ?? "--"}
              </div>
              <div className="font-body-sm text-text-secondary">
                {legTypeLabel(leg, locale)} · {leg.expiry ?? leg.expiration ?? "--"} ·{" "}
                {typeof leg.strike === "number" ? leg.strike.toFixed(0) : "--"}
              </div>
            </div>
            <div className="text-right font-data-mono text-sm text-text-primary">
              {money(leg.mid_price ?? leg.premium)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function addDaysIso(days: number) {
  const value = new Date();
  value.setHours(0, 0, 0, 0);
  value.setDate(value.getDate() + days);
  return value.toISOString().slice(0, 10);
}

function viewTypeLabel(value: FormValues["view_type"], locale: "en" | "zh") {
  const labels = {
    en: {
      long_term_aggressive_bullish: "Long-term aggressive bullish",
      long_term_conservative_bullish: "Long-term conservative bullish",
      short_term_speculative_bullish: "Short-term speculative bullish",
      short_term_conservative_bullish: "Short-term conservative bullish",
      event_driven_bullish: "Event-driven bullish",
    },
    zh: {
      long_term_aggressive_bullish: "长期激进看涨",
      long_term_conservative_bullish: "长期保守看涨",
      short_term_speculative_bullish: "短期投机看涨",
      short_term_conservative_bullish: "短期保守看涨",
      event_driven_bullish: "事件驱动看涨",
    },
  };
  return labels[locale][value];
}

function riskPreferenceLabel(value: FormValues["risk_preference"], locale: "en" | "zh") {
  const labels = {
    en: { aggressive: "Aggressive", balanced: "Balanced", conservative: "Conservative" },
    zh: { aggressive: "激进", balanced: "平衡", conservative: "保守" },
  };
  return labels[locale][value];
}

function volatilityViewLabel(value: FormValues["volatility_view"], locale: "en" | "zh") {
  const labels = {
    en: {
      auto: "Auto",
      prefer_low_iv: "Prefer low IV",
      expect_iv_crush: "Expect IV crush",
      expect_iv_expansion: "Expect IV expansion",
    },
    zh: {
      auto: "自动",
      prefer_low_iv: "偏好低 IV",
      expect_iv_crush: "预期 IV 回落",
      expect_iv_expansion: "预期 IV 扩张",
    },
  };
  return labels[locale][value];
}

function eventRiskLabel(value: FormValues["event_risk"], locale: "en" | "zh") {
  const labels = {
    en: {
      none: "None",
      earnings: "Earnings",
      fomc: "FOMC",
      cpi: "CPI",
      product_event: "Product event",
      user_defined: "User defined",
    },
    zh: {
      none: "无",
      earnings: "财报",
      fomc: "FOMC",
      cpi: "CPI",
      product_event: "产品事件",
      user_defined: "自定义",
    },
  };
  return labels[locale][value];
}

function scenarioRowLabel(value: "bull" | "base" | "bear", locale: "en" | "zh") {
  const labels = {
    en: { bull: "bull", base: "base", bear: "bear" },
    zh: { bull: "看涨", base: "基准", bear: "看跌" },
  };
  return labels[locale][value];
}

function strategyLabel(strategy: string) {
  return {
    long_call: "Long Call",
    bull_call_spread: "Bull Call Spread",
    leaps_call: "LEAPS Call",
    leaps_call_spread: "LEAPS Call Spread",
  }[strategy] ?? strategy;
}

function legActionLabel(leg: BuySideStrategyLeg, locale: "en" | "zh") {
  const side = (leg.action ?? leg.side ?? "").toLowerCase();
  const isShort = side === "sell" || side === "short";
  if (locale === "zh") {
    return isShort ? "卖出" : "买入";
  }
  return isShort ? "Sell" : "Buy";
}

function legActionClass(leg: BuySideStrategyLeg) {
  const side = (leg.action ?? leg.side ?? "").toLowerCase();
  const isShort = side === "sell" || side === "short";
  return isShort
    ? "rounded-lg border border-warning/40 bg-warning/10 px-2 py-1 text-center font-label-caps text-warning"
    : "rounded-lg border border-accent-success/40 bg-accent-success/10 px-2 py-1 text-center font-label-caps text-accent-success";
}

function legTypeLabel(leg: BuySideStrategyLeg, locale: "en" | "zh") {
  const type = (leg.option_type ?? "CALL").toUpperCase();
  if (locale === "zh") {
    return type === "PUT" ? "看跌" : "看涨";
  }
  return type;
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

function expirationLabel(legs?: BuySideStrategyLeg[]) {
  const expirations = [...new Set((legs ?? []).map((leg) => leg.expiry ?? leg.expiration).filter(Boolean))];
  return expirations.length ? expirations.join(" / ") : "--";
}

function strikeLabel(legs?: BuySideStrategyLeg[]) {
  const strikes = (legs ?? []).map((leg) => leg.strike).filter((item): item is number => typeof item === "number");
  return strikes.length ? strikes.map((item) => item.toFixed(0)).join(" / ") : "--";
}

function minDte(legs?: BuySideStrategyLeg[]) {
  const values = (legs ?? []).map((leg) => leg.dte).filter((item): item is number => typeof item === "number");
  return values.length ? Math.min(...values) : null;
}

function hasWarning(item: BuySideRecommendation | undefined, warning: string) {
  return item?.warnings?.includes(warning) ?? false;
}

function regimeTone(regime?: string | null): "neutral" | "success" | "warning" | "danger" {
  if (regime === "Panic") return "danger";
  if (regime === "Elevated") return "warning";
  if (regime === "Normal") return "success";
  return "neutral";
}
