'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useForm, useWatch, type UseFormRegisterReturn } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import type { OptionsScreenerResult } from "@/lib/api";
import { apiPost } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";
import { localizePath } from "@/lib/locale";
import { optionsErrorMessage } from "@/lib/optionsErrorPresentation";
import {
  OptionsScreenerResults,
  partitionScreenerCandidates,
} from "@/components/forms/OptionsScreenerResults";
import {
  TerminalSplitShell,
  TerminalToolbarButton,
  terminalInputClass,
  terminalInputCompactClass,
} from "@/components/ui/primitives";

const selectClass = terminalInputClass;

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
    min_market_cap: 0,
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
    min_market_cap: 0,
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
    groupBasics: "Window & yield",
    groupVolatility: "Volatility & liquidity",
    maxDelta: "Max Delta",
    minApr: "Min gross premium APR (%)",
    fees: "Estimated round-trip fees / contract (USD, blank = unknown)",
    feeHelp: "Bid is a conservative quoted premium, not a fill. Fees exclude buyback cost, assignment and stock gains/losses.",
    minDte: "Min DTE",
    maxDte: "Max DTE",
    maxSpread: "Max Spread (%)",
    minOi: "Min Open Interest",
    maxHvIv: "Max HV/IV",
    minIv: "Min IV (%)",
    qualityFilters: "Quality Filters",
    minMid: "Min Mid (USD)",
    minAdv: "Min Underlying ADV (0=off)",
    minMarketCap: "Min Market Cap (0=off)",
    trendFilter: "Trend filter",
    hvIvFilter: "HV / IV timing filter",
    showRejected: "Show rejected contracts",
    showRejectedHelp:
      "Contracts rejected by quality, personal filters or market regime appear below the eligible table when this is selected for the run.",
    run: "Run Screener",
    running: "Running...",
    warning: "Research-only output. These rows are not trade instructions and cannot place orders.",
    emptyTitle: "No screener run yet",
    emptyBody: "Set the DTE window and filters. The backend will scan all Futu expirations inside that window automatically.",
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
    groupBasics: "窗口与收益",
    groupVolatility: "波动与流动性",
    maxDelta: "最大 Delta",
    minApr: "最低权利金年化 (%)",
    fees: "每张开平仓费用估计 (美元，留空=未知)",
    feeHelp: "买一价表示保守报价，不保证成交。费用估计不含买回成本、指派和持股盈亏。",
    minDte: "最小 DTE",
    maxDte: "最大 DTE",
    maxSpread: "最大价差 (%)",
    minOi: "最低未平仓量",
    maxHvIv: "最大 HV/IV",
    minIv: "最低 IV (%)",
    qualityFilters: "质量过滤",
    minMid: "最低中间价 (美元)",
    minAdv: "最低正股日均量 (0=关闭)",
    minMarketCap: "最低市值 (0=关闭)",
    trendFilter: "趋势过滤",
    hvIvFilter: "HV / IV 择时过滤",
    showRejected: "显示未入选合约",
    showRejectedHelp:
      "勾选后重新运行，会在合格候选下方展示未满足基础质量、个人条件或市场状态要求的合约，便于核对排除原因。",
    run: "开始分析",
    running: "分析中...",
    warning: "仅用于研究筛选。这些结果不是交易指令，也不能发出真实订单。",
    emptyTitle: "还没有运行筛选",
    emptyBody: "设置 DTE 窗口和筛选条件后，后端会自动扫描这个范围内的全部 Futu 到期日。",
    parameterHelp: [
      ["DTE 窗口", "筛选器会扫描这个范围内的全部 Futu 到期日，并把合约统一排序。"],
      ["Max Delta", "绝对 Delta 越低越保守，适合卖方期权筛选。"],
      ["Min APR", "按中间价估算的毛权利金年化，低于门槛不会进入合格候选。它不是策略实际收益率。"],
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
  include_rejected: z.boolean(),
  provider: z.literal("futu"),
  estimated_round_trip_fee_per_contract: z.number().nonnegative().nullable().optional(),
});

type ScreenerValues = z.infer<typeof screenerSchema>;

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
      min_market_cap: 0,
      trend_filter: true,
      hv_iv_filter: true,
      include_rejected: false,
      provider: "futu",
      estimated_round_trip_fee_per_contract: null,
    },
  });

  const mutation = useMutation({
    mutationFn: (values: ScreenerValues) =>
      apiPost<OptionsScreenerResult>("/api/options/screener", {
        ...values,
        ticker: values.ticker.trim().toUpperCase(),
        min_iv: values.min_iv_input / 100,
        max_spread_pct: values.max_spread_pct_input / 100,
        min_mid_price: values.min_mid_price,
        min_avg_daily_volume: values.min_avg_daily_volume,
        min_market_cap: values.min_market_cap,
      }),
    onSuccess: (payload) => {
      const { eligible } = partitionScreenerCandidates(payload.candidates);
      toast.success(
        locale === "zh"
          ? `筛选完成：${payload.eligible_count ?? eligible.length} 个合约满足全部条件，展示 ${eligible.length} 个`
          : `Done: ${payload.eligible_count ?? eligible.length} contracts meet all filters, showing ${eligible.length}`,
      );
    },
  });
  const error = mutation.error ? optionsErrorMessage(mutation.error, locale) : undefined;
  const run = form.handleSubmit((values) => mutation.mutate(values));
  const result = mutation.data;
  const showRejected = useWatch({ control: form.control, name: "include_rejected" });

  const [preset, setPreset] = useState<keyof typeof presets | "">("");
  function applyPreset(name: keyof typeof presets) {
    const selected = presets[name];
    Object.entries(selected).forEach(([key, value]) => {
      form.setValue(key as keyof ScreenerValues, value, { shouldValidate: true });
    });
  }

  return (
    <TerminalSplitShell
      sidebar={
        <>
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
          <div>
            <div className="mb-2 font-label-caps text-text-secondary">{text.groupBasics}</div>
            <div className="grid grid-cols-2 gap-2">
              <NumberField label={text.minDte} registration={form.register("min_dte", { valueAsNumber: true })} step={1} />
              <NumberField label={text.maxDte} registration={form.register("max_dte", { valueAsNumber: true })} step={1} />
              <NumberField label={text.maxDelta} registration={form.register("max_delta", { valueAsNumber: true })} step={0.01} />
              <NumberField label={text.minApr} registration={form.register("min_apr", { valueAsNumber: true })} step={1} />
            </div>
          </div>
          <div>
            <div className="mb-2 font-label-caps text-text-secondary">{text.groupVolatility}</div>
            <div className="grid grid-cols-2 gap-2">
              <NumberField label={text.minIv} registration={form.register("min_iv_input", { valueAsNumber: true })} step={1} />
              <NumberField label={text.maxHvIv} registration={form.register("max_hv_iv", { valueAsNumber: true })} step={0.1} />
              <NumberField label={text.maxSpread} registration={form.register("max_spread_pct_input", { valueAsNumber: true })} step={0.5} />
              <NumberField label={text.minOi} registration={form.register("min_open_interest", { valueAsNumber: true })} step={10} />
            </div>
          </div>
          <div className="rounded-lg border border-border-subtle bg-bg-surface-muted p-3">
            <div className="mb-2 font-label-caps text-text-secondary">{text.qualityFilters}</div>
            <div className="grid grid-cols-2 gap-2">
              <NumberField label={text.minMid} registration={form.register("min_mid_price", { valueAsNumber: true })} step={0.05} />
              <NumberField label={text.minAdv} registration={form.register("min_avg_daily_volume", { valueAsNumber: true })} step={100000} />
              <div className="col-span-2">
                <NumberField label={text.minMarketCap} registration={form.register("min_market_cap", { valueAsNumber: true })} step={1000000000} />
              </div>
            </div>
          </div>
          <label className="flex items-center gap-2 font-body-sm text-text-primary">
            <input type="checkbox" {...form.register("trend_filter")} />
            {text.trendFilter}
          </label>
          <label className="flex items-center gap-2 font-body-sm text-text-primary">
            <input type="checkbox" {...form.register("hv_iv_filter")} />
            {text.hvIvFilter}
          </label>
          <label className="flex items-center gap-2 font-body-sm text-text-primary" title={text.showRejectedHelp}>
            <input type="checkbox" {...form.register("include_rejected")} />
            {text.showRejected}
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.fees}
            <input className={terminalInputCompactClass} type="number" min="0" step="0.01"
              {...form.register("estimated_round_trip_fee_per_contract", {
                setValueAs: (value: string) => value === "" ? null : Number(value),
              })} />
            <span className="text-text-secondary">{text.feeHelp}</span>
          </label>
          {error ? <p className="font-body-sm text-danger">{error}</p> : null}
          <TerminalToolbarButton
            className="h-10 w-full justify-center"
            disabled={!isHydrated || mutation.isPending}
            onClick={() => void run()}
            tone="info"
            type="button"
          >
            {mutation.isPending ? text.running : text.run}
          </TerminalToolbarButton>
        </form>
        </>
      }
      sidebarClassName="p-4 lg:w-[380px]"
      mainClassName="p-4"
    >

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
          <OptionsScreenerResults locale={locale} result={result} showRejected={showRejected} />
        )}
    </TerminalSplitShell>
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
        className={terminalInputCompactClass}
        step={step}
        type="number"
        {...registration}
      />
    </label>
  );
}
