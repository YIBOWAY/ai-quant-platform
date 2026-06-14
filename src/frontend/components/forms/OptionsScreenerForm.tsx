'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useForm, type UseFormRegisterReturn } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiClientError, apiPost } from "@/lib/apiClient";
import { InfoTip, type GlossaryKey } from "@/components/InfoTip";
import { useIsHydrated } from "@/lib/hydration";
import { localizePath } from "@/lib/locale";

const selectClass =
  "rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 text-text-primary";

// Maps screener column index to a glossary term so headers can show a hint.
const headingTips: Record<number, GlossaryKey> = {
  7: "apr",
  8: "spread",
  9: "ivRank",
  10: "delta",
  11: "openInterest",
};
// Phase 12 fix (2026-05): every preset now sets every numeric field so that
// switching presets cannot leave stale values from a previous selection.
const presets = {
  conservative: {
    max_delta: 0.2,
    min_apr: 8,
    min_dte: 14,
    max_dte: 45,
    max_spread_pct_input: 5,
    min_open_interest: 200,
    max_hv_iv: 0.75,
    min_premium: 0.2,
    min_iv_input: 15,
    min_mid_price: 0.2,
    min_avg_daily_volume: 1_000_000,
    min_market_cap: 10_000_000_000,
    trend_filter: true,
    hv_iv_filter: true,
  },
  balanced: {
    max_delta: 0.3,
    min_apr: 15,
    min_dte: 10,
    max_dte: 60,
    max_spread_pct_input: 10,
    min_open_interest: 100,
    max_hv_iv: 1.2,
    min_premium: 0.15,
    min_iv_input: 10,
    min_mid_price: 0.15,
    min_avg_daily_volume: 500_000,
    min_market_cap: 2_000_000_000,
    trend_filter: true,
    hv_iv_filter: true,
  },
  aggressive: {
    max_delta: 0.45,
    min_apr: 25,
    min_dte: 7,
    max_dte: 60,
    max_spread_pct_input: 15,
    min_open_interest: 50,
    max_hv_iv: 1.0,
    min_premium: 0.1,
    min_iv_input: 0,
    min_mid_price: 0.1,
    min_avg_daily_volume: 100_000,
    min_market_cap: 0,
    trend_filter: true,
    hv_iv_filter: false,
  },
} as const;

const copy = {
  en: {
    title: "Options Income Screener",
    intro: "Read-only Futu data for Sell Put and Covered Call screening. No orders, no account unlock, no live trading.",
    ticker: "Ticker",
    strategy: "Strategy",
    sellPut: "Sell Put",
    coveredCall: "Covered Call / Sell Call",
    preset: "Preset",
    presetNone: "-- Preset --",
    conservative: "Conservative",
    balanced: "Balanced",
    aggressive: "Aggressive",
    maxDelta: "Max Delta",
    minApr: "Min APR (%)",
    minDte: "Min DTE",
    maxDte: "Max DTE",
    dteWindow: "DTE Window",
    maxSpread: "Max Spread (%)",
    minOi: "Min Open Interest",
    maxHvIv: "Max HV/IV",
    minIv: "Min IV (%)",
    trendFilter: "Trend filter",
    hvIvFilter: "HV / IV timing filter",
    run: "Run Screener",
    running: "Running...",
    warning: "Research-only output. These rows are not trade instructions and cannot place orders.",
    emptyTitle: "No screener run yet",
    emptyBody: "Set the DTE window and filters. The backend will scan all Futu expirations inside that window automatically.",
    underlying: "Underlying",
    scannedExpirations: "Scanned Expirations",
    candidates: "Candidates",
    assumptions: "Assumptions",
    strong: "Strong",
    watch: "Watch",
    avoid: "Avoid",
    regime: "Market regime",
    regimeUnknown: "Unknown - run `quant-system options refresh-vix` then re-run the screener.",
    regimeNormal: "Normal - no market-regime score penalty.",
    regimeElevated:
      "Elevated - market volatility is higher than usual. Short-premium margin and drawdown pressure can rise; control position size.",
    regimePanic:
      "Panic - market volatility is high. Selling options can require more margin and absorb sharper drawdowns; reduce size or wait.",
    ema21: "EMA21",
    sma50: "SMA50",
    hvIvStatus: "HV/IV Status",
    trendPassed: "Trend passed",
    trendWeak: "Trend warning",
    hvIvUnavailable: "No IV data",
    headings: ["Symbol", "Type", "Expiry", "Strike", "Bid", "Ask", "Mid", "APR", "Spread", "IV", "Delta", "OI", "Rating"],
    parameterHelp: [
      ["DTE Window", "The screener scans every available Futu expiration inside this range and ranks the contracts."],
      ["Max Delta", "Lower absolute delta is more conservative for short premium screening."],
      ["Min APR", "Minimum annualized premium estimate. It is a simplified screen, not a guaranteed return."],
      ["Max Spread", "Bid/ask spread cap. Lower is more liquid."],
      ["Min OI", "Open interest floor. Higher usually means better market depth."],
      ["Max HV/IV", "HV divided by IV. Lower values mean IV is richer versus recent realized movement."],
    ],
  },
  zh: {
    title: "卖方期权筛选器",
    intro: "使用 Futu 只读数据筛选 Sell Put 与 Covered Call。不会下单、不会解锁账户、不会接入实盘。",
    ticker: "标的代码",
    strategy: "策略类型",
    sellPut: "卖出看跌",
    coveredCall: "备兑看涨 / 卖出看涨",
    preset: "预设",
    presetNone: "-- 预设 --",
    conservative: "保守",
    balanced: "平衡",
    aggressive: "激进",
    maxDelta: "最大 Delta",
    minApr: "最低年化 (%)",
    minDte: "最小 DTE",
    maxDte: "最大 DTE",
    dteWindow: "DTE 窗口",
    maxSpread: "最大价差 (%)",
    minOi: "最低未平仓量",
    maxHvIv: "最大 HV/IV",
    minIv: "最低 IV (%)",
    trendFilter: "趋势过滤",
    hvIvFilter: "HV / IV 择时过滤",
    run: "开始分析",
    running: "分析中...",
    warning: "仅用于研究筛选。这些结果不是交易指令，也不能发出真实订单。",
    emptyTitle: "还没有运行筛选",
    emptyBody: "设置 DTE 窗口和筛选条件后，后端会自动扫描这个范围内的全部 Futu 到期日。",
    underlying: "正股价格",
    scannedExpirations: "扫描到期日",
    candidates: "候选合约",
    assumptions: "假设说明",
    strong: "强烈",
    watch: "观察",
    avoid: "避开",
    regime: "市场状态",
    regimeUnknown: "未知 - 请先运行 `quant-system options refresh-vix` 刷新 VIX 历史后再筛选。",
    regimeNormal: "Normal - 不施加市场状态扣分。",
    regimeElevated: "Elevated - 市场波动偏大，卖权保证金和回撤压力可能上升，注意控制仓位。",
    regimePanic: "Panic - 市场波动很大，卖权保证金和回撤压力会更高，建议降低仓位或等待。",
    ema21: "EMA21",
    sma50: "SMA50",
    hvIvStatus: "HV/IV 状态",
    trendPassed: "趋势通过",
    trendWeak: "趋势提醒",
    hvIvUnavailable: "缺少 IV 数据",
    headings: ["代码", "类型", "到期日", "行权价", "买价", "卖价", "中间价", "年化", "价差", "IV", "Delta", "未平仓", "评级"],
    parameterHelp: [
      ["DTE 窗口", "筛选器会扫描这个范围内的全部 Futu 到期日，并把合约统一排序。"],
      ["Max Delta", "绝对 Delta 越低越保守，适合卖方期权筛选。"],
      ["Min APR", "最低年化权利金估算。它只是筛选条件，不代表确定收益。"],
      ["Max Spread", "买卖价差上限。越低通常流动性越好。"],
      ["Min OI", "未平仓量下限。更高通常代表市场深度更好。"],
      ["Max HV/IV", "历史波动率除以隐含波动率。越低说明 IV 相对近期波动更充足。"],
    ],
  },
};

const screenerSchema = z.object({
  ticker: z.string().min(1),
  strategy_type: z.enum(["sell_put", "covered_call"]),
  min_iv_input: z.coerce.number().nonnegative(),
  max_delta: z.coerce.number().nonnegative().max(1),
  min_premium: z.coerce.number().nonnegative(),
  min_apr: z.coerce.number().nonnegative(),
  min_dte: z.coerce.number().int().nonnegative(),
  max_dte: z.coerce.number().int().nonnegative(),
  max_spread_pct_input: z.coerce.number().nonnegative(),
  min_open_interest: z.coerce.number().nonnegative(),
  max_hv_iv: z.coerce.number().nonnegative(),
  min_mid_price: z.coerce.number().nonnegative(),
  min_avg_daily_volume: z.coerce.number().nonnegative(),
  min_market_cap: z.coerce.number().nonnegative(),
  trend_filter: z.boolean(),
  hv_iv_filter: z.boolean(),
  provider: z.literal("futu"),
});

type ScreenerValues = z.infer<typeof screenerSchema>;

type ScreenerCandidate = {
  symbol: string;
  option_type: string;
  expiry: string;
  strike: number;
  bid?: number | null;
  ask?: number | null;
  mid?: number | null;
  annualized_yield?: number | null;
  spread_pct?: number | null;
  implied_volatility?: number | null;
  delta?: number | null;
  open_interest?: number | null;
  rating: string;
  notes: string[];
  market_regime?: "Normal" | "Elevated" | "Panic" | "Unknown" | null;
  market_regime_penalty?: number | null;
};

type ScreenerResult = {
  ticker: string;
  provider: "futu";
  strategy_type: string;
  expiration?: string | null;
  scanned_expirations: string[];
  expiration_count: number;
  underlying_price: number;
  historical_volatility?: number | null;
  trend_reference?: number | null;
  ema_21?: number | null;
  sma_50?: number | null;
  hv_iv_threshold?: number | null;
  hv_iv_pass_count?: number;
  hv_iv_contract_count?: number;
  hv_iv_min?: number | null;
  hv_iv_max?: number | null;
  market_regime?: "Normal" | "Elevated" | "Panic" | "Unknown" | null;
  market_regime_penalty?: number | null;
  market_regime_w_vix?: number | null;
  market_regime_vix_density?: number | null;
  market_regime_term_ratio?: number | null;
  candidates: ScreenerCandidate[];
  rejected_count?: number;
  rejection_summary?: Record<string, number>;
  assumptions: string[];
};

function formatNumber(value?: number | null, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function formatPercent(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${(value * 100).toFixed(2)}%`
    : "--";
}

function formatRatio(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "--";
}

function trendHelp(
  result: ScreenerResult,
  locale: "en" | "zh",
  text: (typeof copy)["en"] | (typeof copy)["zh"],
) {
  const price = result.underlying_price;
  const ema21 = result.ema_21;
  const sma50 = result.sma_50;
  if (
    typeof ema21 !== "number"
    || !Number.isFinite(ema21)
    || typeof sma50 !== "number"
    || !Number.isFinite(sma50)
  ) {
    return locale === "zh" ? "均线数据不足，趋势只作参考。" : "Moving-average data is incomplete; trend is reference-only.";
  }
  const warnings = [];
  if (price < ema21) {
    warnings.push(locale === "zh" ? "低于 EMA21" : "below EMA21");
  }
  if (price < sma50) {
    warnings.push(locale === "zh" ? "低于 SMA50" : "below SMA50");
  }
  if (!warnings.length) {
    return text.trendPassed;
  }
  return `${text.trendWeak}: ${warnings.join(locale === "zh" ? "、" : " / ")}`;
}

function hvIvStatus(
  result: ScreenerResult,
  locale: "en" | "zh",
  text: (typeof copy)["en"] | (typeof copy)["zh"],
) {
  const total = result.hv_iv_contract_count ?? 0;
  if (total <= 0) {
    return text.hvIvUnavailable;
  }
  const passed = result.hv_iv_pass_count ?? 0;
  return locale === "zh" ? `${passed}/${total} 通过` : `${passed}/${total} pass`;
}

function hvIvHelp(result: ScreenerResult, locale: "en" | "zh") {
  const total = result.hv_iv_contract_count ?? 0;
  if (total <= 0) {
    return locale === "zh" ? "没有可用的 IV，无法判断 HV/IV。" : "No usable IV, so HV/IV cannot be judged.";
  }
  const threshold = formatRatio(result.hv_iv_threshold);
  const low = formatRatio(result.hv_iv_min);
  const high = formatRatio(result.hv_iv_max);
  return locale === "zh"
    ? `上限 ${threshold}；范围 ${low}-${high}`
    : `Limit ${threshold}; range ${low}-${high}`;
}

function ratingLabel(rating: string, locale: "en" | "zh") {
  if (locale === "en") {
    return rating;
  }
  if (rating === "Strong") {
    return copy.zh.strong;
  }
  if (rating === "Watch") {
    return copy.zh.watch;
  }
  return copy.zh.avoid;
}

const assumptionZh: Record<string, string> = {
  "Read-only data mode; no order placement is available.": "只读数据模式；不会下单。",
  "When expiration is omitted, the screener scans all Futu expirations inside the configured DTE window.":
    "未指定到期日时，后端会扫描 DTE 范围内所有 Futu 到期日。",
  "Avoid-rated contracts are hidden by default; set include_rejected=true to audit rejected rows.":
    "默认隐藏 Avoid 合约；需要排查时可启用 include_rejected 查看被过滤行。",
  "Premium uses mid price when bid and ask are available.": "买卖价可用时，权利金按中间价估算。",
  "Yield estimates are simplified and ignore assignment, taxes, and commissions.":
    "收益率是简化估算，未计入行权、税费和佣金。",
  "Missing IV/Greeks fields reduce confidence; they are not invented.": "缺少 IV 或希腊值会降低可信度，系统不会编造这些数据。",
  "VIX market regime is read from the offline Yahoo cache and discounts seller ratings under Elevated / Panic conditions.":
    "VIX 市场状态来自本地缓存；市场偏紧张时会下调卖方候选评级。",
};

const rejectionReasonZh: Record<string, string> = {
  "missing or non-positive bid/ask": "缺少有效买卖价",
  "premium below minimum": "权利金低于最低要求",
  "mid below absolute floor": "中间价低于最低要求",
  "spread too wide": "买卖价差过宽",
  "APR below minimum": "年化收益低于最低要求",
  "DTE missing": "缺少到期天数",
  "DTE outside range": "到期天数不在范围内",
  "open interest missing": "缺少未平仓量",
  "open interest below minimum": "未平仓量低于要求",
  "IV missing": "缺少 IV",
  "IV below minimum": "IV 低于最低要求",
  "delta missing": "缺少 Delta",
  "delta above limit": "Delta 超过上限",
  "sell put strike is above spot": "卖出看跌行权价高于现价",
  "covered call strike is below spot": "covered call 行权价低于现价",
  "trend filter failed": "趋势过滤未通过",
  "price below EMA21": "价格低于 EMA21",
  "price below SMA50": "价格低于 SMA50",
  "IV/HV filter failed": "IV/HV 过滤未通过",
  "underlying ADV missing": "缺少正股成交量",
  "underlying ADV below minimum": "正股成交量低于要求",
  "market cap missing": "缺少市值",
  "market cap below minimum": "市值低于要求",
};

function translateAssumption(value: string, locale: "en" | "zh") {
  return locale === "zh" ? assumptionZh[value] ?? value : value;
}

function translateRejectionReason(value: string, locale: "en" | "zh") {
  return locale === "zh" ? rejectionReasonZh[value] ?? value : value;
}

export function OptionsScreenerForm({ locale = "en" }: { locale?: "en" | "zh" }) {
  const isHydrated = useIsHydrated();
  const text = copy[locale];
  const form = useForm<ScreenerValues>({
    resolver: zodResolver(screenerSchema),
    defaultValues: {
      ticker: "SPY",
      strategy_type: "sell_put",
      min_iv_input: 10,
      max_delta: 0.3,
      min_premium: 0.15,
      min_apr: 15,
      min_dte: 10,
      max_dte: 60,
      max_spread_pct_input: 10,
      min_open_interest: 100,
      max_hv_iv: 1.2,
      min_mid_price: 0.15,
      min_avg_daily_volume: 500_000,
      min_market_cap: 2_000_000_000,
      trend_filter: true,
      hv_iv_filter: true,
      provider: "futu",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: ScreenerValues) =>
      apiPost<ScreenerResult>("/api/options/screener", {
        ...values,
        ticker: values.ticker.trim().toUpperCase(),
        min_iv: values.min_iv_input / 100,
        max_spread_pct: values.max_spread_pct_input / 100,
        min_mid_price: values.min_mid_price,
        min_avg_daily_volume: values.min_avg_daily_volume,
        min_market_cap: values.min_market_cap,
      }),
    onSuccess: (payload) => {
      toast.success(
        locale === "zh"
          ? `期权筛选返回 ${payload.candidates.length} 个候选合约`
          : `Options screener returned ${payload.candidates.length} candidates`,
      );
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;
  const run = form.handleSubmit((values) => mutation.mutate(values));
  const result = mutation.data;

  const [preset, setPreset] = useState<keyof typeof presets | "">("");
  function applyPreset(name: keyof typeof presets) {
    const selected = presets[name];
    Object.entries(selected).forEach(([key, value]) => {
      form.setValue(key as keyof ScreenerValues, value, { shouldValidate: true });
    });
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-[380px_1fr] overflow-hidden">
      <aside className="overflow-y-auto border-r border-border-subtle bg-bg-surface p-4">
        <h2 className="font-headline-lg text-text-primary">{text.title}</h2>
        <p className="mt-1 font-body-sm text-text-secondary">{text.intro}</p>
        <a
          className="mt-3 inline-flex font-body-sm text-info"
          href={localizePath("/options-screener", locale === "zh" ? "en" : "zh")}
        >
          {locale === "zh" ? "English" : "中文"}
        </a>
        <form className="mt-4 flex flex-col gap-4" onSubmit={(event) => event.preventDefault()}>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              {text.strategy}
              <select
                className={selectClass}
                {...form.register("strategy_type")}
              >
                <option value="sell_put">
                  {text.sellPut}
                </option>
                <option value="covered_call">
                  {text.coveredCall}
                </option>
              </select>
            </label>
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              {text.ticker}
              <input
                className="rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 font-data-mono uppercase text-text-primary"
                {...form.register("ticker")}
              />
            </label>
          </div>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.preset}
            <select
              className={selectClass}
              value={preset}
              onChange={(event) => {
                const value = event.target.value as keyof typeof presets | "";
                setPreset(value);
                if (value) {
                  applyPreset(value);
                }
              }}
            >
              <option value="">
                {text.presetNone}
              </option>
              <option value="conservative">
                {text.conservative}
              </option>
              <option value="balanced">
                {text.balanced}
              </option>
              <option value="aggressive">
                {text.aggressive}
              </option>
            </select>
          </label>
          <div className="grid grid-cols-2 gap-2">
            <NumberField label={text.maxDelta} registration={form.register("max_delta", { valueAsNumber: true })} step={0.01} />
            <NumberField label={text.minApr} registration={form.register("min_apr", { valueAsNumber: true })} step={1} />
            <NumberField label={text.minDte} registration={form.register("min_dte", { valueAsNumber: true })} step={1} />
            <NumberField label={text.maxDte} registration={form.register("max_dte", { valueAsNumber: true })} step={1} />
            <NumberField label={text.maxSpread} registration={form.register("max_spread_pct_input", { valueAsNumber: true })} step={0.5} />
            <NumberField label={text.minOi} registration={form.register("min_open_interest", { valueAsNumber: true })} step={10} />
            <NumberField label={text.maxHvIv} registration={form.register("max_hv_iv", { valueAsNumber: true })} step={0.1} />
            <NumberField label={text.minIv} registration={form.register("min_iv_input", { valueAsNumber: true })} step={1} />
          </div>
          <label className="flex items-center gap-2 font-body-sm text-text-primary">
            <input type="checkbox" {...form.register("trend_filter")} />
            {text.trendFilter}
          </label>
          <label className="flex items-center gap-2 font-body-sm text-text-primary">
            <input type="checkbox" {...form.register("hv_iv_filter")} />
            {text.hvIvFilter}
          </label>
          {error ? <p className="font-body-sm text-danger">{error}</p> : null}
          <button
            className="rounded-lg bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!isHydrated || mutation.isPending}
            onClick={() => void run()}
            type="button"
          >
            {mutation.isPending ? text.running : text.run}
          </button>
        </form>
      </aside>

      <section className="min-w-0 overflow-y-auto bg-bg-base p-4">
        <div className="mb-4 rounded-lg border border-warning/40 bg-warning/10 p-3 font-body-sm text-warning">
          {text.warning}
        </div>
        {!result ? (
          <div className="grid grid-cols-3 gap-3">
            {text.parameterHelp.map(([label, description]) => (
              <div className="rounded-lg border border-border-subtle bg-bg-surface p-4" key={label}>
                <h3 className="font-label-caps text-text-primary">{label}</h3>
                <p className="mt-2 font-body-sm text-text-secondary">{description}</p>
              </div>
            ))}
            <div className="col-span-3 rounded-lg border border-border-subtle bg-bg-surface p-4">
              <h3 className="font-label-caps text-text-primary">{text.emptyTitle}</h3>
              <p className="mt-2 font-body-sm text-text-secondary">{text.emptyBody}</p>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <RegimeStatusBar result={result} text={text} locale={locale} />
            <CompactMetrics result={result} text={text} locale={locale} />
            {result.candidates.length === 0 ? (
              <div className="rounded-lg border border-warning/40 bg-warning/10 p-4 font-body-sm text-warning">
                {locale === "zh" ? (
                  <>
                    <p className="font-semibold">
                      已扫描 {result.expiration_count ?? result.scanned_expirations?.length ?? 0} 个到期日、过滤掉
                      {" "}
                      {result.rejected_count ?? 0} 个合约，当前过滤条件下没有合格候选。
                    </p>
                    <p className="mt-2 text-text-secondary">
                      这通常说明筛选条件相对该标的过严，而不是程序出错。像 LMT 这类低波动标的，权利金年化往往达不到较高的 Min APR。可以尝试：
                    </p>
                    <RejectionSummary locale={locale} summary={result.rejection_summary} />
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-text-secondary">
                      <li>调低「最低年化 (%)」（当前 IV 越低，能达到的年化越低）。</li>
                      <li>放宽「最大 Delta」或「最大价差 (%)」。</li>
                      <li>关闭「趋势过滤」或「HV / IV 择时过滤」。</li>
                    </ul>
                  </>
                ) : (
                  <>
                    <p className="font-semibold">
                      Scanned {result.expiration_count ?? result.scanned_expirations?.length ?? 0} expirations and
                      filtered out {result.rejected_count ?? 0} contracts — none passed the current filters.
                    </p>
                    <p className="mt-2 text-text-secondary">
                      This usually means the filters are too strict for this ticker, not a malfunction. Low-volatility
                      names like LMT rarely reach a high Min APR. Try:
                    </p>
                    <RejectionSummary locale={locale} summary={result.rejection_summary} />
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-text-secondary">
                      <li>Lowering Min APR (low IV caps the achievable annualized yield).</li>
                      <li>Relaxing Max Delta or Max Spread.</li>
                      <li>Turning off the trend filter or HV/IV timing filter.</li>
                    </ul>
                  </>
                )}
              </div>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-border-subtle bg-bg-surface">
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="border-b border-border-subtle">
                      {text.headings.map((heading, index) => (
                        <th className="px-3 py-2 font-label-caps text-text-secondary" key={heading}>
                          <span className="inline-flex items-center gap-1">
                            {heading}
                            {headingTips[index] ? (
                              <InfoTip term={headingTips[index]} locale={locale} />
                            ) : null}
                          </span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="font-data-mono text-data-mono text-text-primary">
                    {result.candidates.map((candidate) => (
                      <tr className="border-b border-border-subtle/50" key={candidate.symbol}>
                        <td className="px-3 py-2">{candidate.symbol}</td>
                        <td className="px-3 py-2">{candidate.option_type}</td>
                        <td className="px-3 py-2">{candidate.expiry}</td>
                        <td className="px-3 py-2">{formatNumber(candidate.strike)}</td>
                        <td className="px-3 py-2">{formatNumber(candidate.bid)}</td>
                        <td className="px-3 py-2">{formatNumber(candidate.ask)}</td>
                        <td className="px-3 py-2">{formatNumber(candidate.mid)}</td>
                        <td className="px-3 py-2">{formatPercent(candidate.annualized_yield)}</td>
                        <td className="px-3 py-2">{formatPercent(candidate.spread_pct)}</td>
                        <td className="px-3 py-2">{formatPercent(candidate.implied_volatility)}</td>
                        <td className="px-3 py-2">{formatNumber(candidate.delta, 3)}</td>
                        <td className="px-3 py-2">{formatNumber(candidate.open_interest, 0)}</td>
                        <td className="px-3 py-2">{ratingLabel(candidate.rating, locale)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="rounded-lg border border-border-subtle bg-bg-surface p-4">
              <h3 className="font-label-caps text-text-secondary">{text.assumptions}</h3>
              <ul className="mt-2 list-disc space-y-1 pl-5 font-body-sm text-text-secondary">
                {result.assumptions.map((assumption) => (
                  <li key={assumption}>{translateAssumption(assumption, locale)}</li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function NumberField({
  label,
  registration,
  step,
}: {
  label: string;
  registration: UseFormRegisterReturn;
  step: number;
}) {
  return (
    <label className="flex flex-col gap-1 font-body-sm text-text-primary">
      {label}
      <input
        className="rounded-lg border border-border-subtle bg-bg-surface-muted px-2 py-2 font-data-mono text-text-primary"
        step={step}
        type="number"
        {...registration}
      />
    </label>
  );
}

// Compact single-line metric: label on top, value below, optional tooltip on
// hover. Keeps the whole summary strip short instead of growing with help text.
function MetricInline({
  label,
  value,
  help,
  tone = "primary",
}: {
  label: string;
  value: string;
  help?: string;
  tone?: "primary" | "success" | "warning" | "danger";
}) {
  const toneClass =
    tone === "success"
      ? "text-accent-success"
      : tone === "warning"
        ? "text-warning"
        : tone === "danger"
          ? "text-danger"
          : "text-text-primary";
  return (
    <div
      className="flex min-w-0 flex-col gap-0.5 px-3 py-2"
      title={help}
    >
      <span className="truncate font-label-caps text-[10px] uppercase text-text-secondary">
        {label}
      </span>
      <span className={`truncate font-data-mono text-sm font-bold ${toneClass}`}>{value}</span>
    </div>
  );
}

// One compact row of core metrics, divided by hairlines. Replaces the tall
// 8-card grid so the candidate table is visible above the fold.
function CompactMetrics({
  result,
  text,
  locale,
}: {
  result: ScreenerResult;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  locale: "en" | "zh";
}) {
  const expirationCount = result.expiration_count ?? result.scanned_expirations?.length ?? 0;
  return (
    <div className="flex flex-wrap items-stretch divide-x divide-border-subtle rounded-lg border border-border-subtle bg-bg-surface">
      <MetricInline
        label={text.underlying}
        value={formatNumber(result.underlying_price)}
        help={trendHelp(result, locale, text)}
      />
      <MetricInline label={text.scannedExpirations} value={String(expirationCount)} />
      <MetricInline label="HV" value={formatPercent(result.historical_volatility)} />
      <MetricInline
        label={text.hvIvStatus}
        value={hvIvStatus(result, locale, text)}
        help={hvIvHelp(result, locale)}
      />
      <MetricInline
        label={text.candidates}
        value={String(result.candidates.length)}
        tone={result.candidates.length > 0 ? "success" : "warning"}
      />
      <MetricInline
        label={locale === "zh" ? "已过滤" : "Filtered out"}
        value={String(result.rejected_count ?? 0)}
        tone={(result.rejected_count ?? 0) > 0 ? "warning" : "primary"}
        help={
          locale === "zh"
            ? "被过滤的 Avoid 合约，例如深度价内、零 OI、价差过宽、趋势或 HV/IV 过滤失败。"
            : "Avoid-rated contracts filtered out, such as deep ITM, zero OI, wide spread, or failed trend/HV-IV filters."
        }
      />
      <MetricInline
        label="EMA21 / SMA50"
        value={`${formatNumber(result.ema_21)} / ${formatNumber(result.sma_50)}`}
        help={trendHelp(result, locale, text)}
      />
    </div>
  );
}

function RejectionSummary({
  locale,
  summary,
}: {
  locale: "en" | "zh";
  summary?: Record<string, number>;
}) {
  const rows = Object.entries(summary ?? {}).slice(0, 5);
  if (!rows.length) {
    return null;
  }
  return (
    <div className="mt-3 rounded-lg border border-border-subtle bg-bg-surface/70 p-3">
      <div className="font-label-caps text-text-secondary">
        {locale === "zh" ? "主要过滤原因" : "Main filter reasons"}
      </div>
      <ul className="mt-2 space-y-1 font-body-sm text-text-secondary">
        {rows.map(([reason, count]) => (
          <li className="flex justify-between gap-4" key={reason}>
            <span>{translateRejectionReason(reason, locale)}</span>
            <span className="font-data-mono text-text-primary">{count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

type RegimeLabel = "Normal" | "Elevated" | "Panic" | "Unknown";

function RegimeStatusBar({
  result,
  text,
  locale,
}: {
  result: ScreenerResult;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  locale: "en" | "zh";
}) {
  const label: RegimeLabel = (result.market_regime ?? "Unknown") as RegimeLabel;
  const palette: Record<RegimeLabel, string> = {
    Normal: "border-accent-success/40 bg-accent-success/10 text-accent-success",
    Elevated: "border-warning/40 bg-warning/10 text-warning",
    Panic: "border-danger/40 bg-danger/10 text-danger",
    Unknown: "border-border-subtle bg-bg-surface text-text-secondary",
  };
  const detail =
    label === "Normal"
      ? text.regimeNormal
      : label === "Elevated"
        ? text.regimeElevated
        : label === "Panic"
          ? text.regimePanic
          : text.regimeUnknown;
  const penalty = result.market_regime_penalty;
  const penaltyText =
    typeof penalty === "number" && Number.isFinite(penalty) && penalty !== 0
      ? ` (${penalty > 0 ? "+" : ""}${penalty.toFixed(0)})`
      : "";
  return (
    <div
      className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-3 py-1.5 ${palette[label]}`}
    >
      <span className="font-label-caps text-[10px] uppercase">{text.regime}</span>
      <span className="font-data-mono text-sm font-bold">
        {label}
        {penaltyText}
      </span>
      {/* Full explanation stays accessible but no longer eats a whole banner. */}
      <span className="min-w-0 flex-1 truncate font-body-sm opacity-80" title={detail}>
        {detail}
      </span>
    </div>
  );
}
