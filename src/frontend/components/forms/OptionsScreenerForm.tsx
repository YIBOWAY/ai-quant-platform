'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm, type UseFormRegisterReturn } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiClientError, apiPost } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };
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
    max_hv_iv: 1.0,
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
  candidates: ScreenerCandidate[];
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
      max_hv_iv: 1.0,
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

  function applyPreset(name: keyof typeof presets) {
    const preset = presets[name];
    Object.entries(preset).forEach(([key, value]) => {
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
          href={locale === "zh" ? "/options-screener?lang=en" : "/options-screener?lang=zh"}
        >
          {locale === "zh" ? "English" : "中文"}
        </a>
        <form className="mt-4 flex flex-col gap-4" onSubmit={(event) => event.preventDefault()}>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              {text.strategy}
              <select
                className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary"
                {...form.register("strategy_type")}
              >
                <option value="sell_put" style={optionStyle}>
                  {text.sellPut}
                </option>
                <option value="covered_call" style={optionStyle}>
                  {text.coveredCall}
                </option>
              </select>
            </label>
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              {text.ticker}
              <input
                className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono uppercase text-text-primary"
                {...form.register("ticker")}
              />
            </label>
          </div>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.preset}
            <select
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary"
              defaultValue=""
              onChange={(event) => {
                const value = event.target.value as keyof typeof presets | "";
                if (value) {
                  applyPreset(value);
                }
                event.currentTarget.value = "";
              }}
            >
              <option style={optionStyle} value="">
                {text.presetNone}
              </option>
              <option style={optionStyle} value="conservative">
                {text.conservative}
              </option>
              <option style={optionStyle} value="balanced">
                {text.balanced}
              </option>
              <option style={optionStyle} value="aggressive">
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
            className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!isHydrated || mutation.isPending}
            onClick={() => void run()}
            type="button"
          >
            {mutation.isPending ? text.running : text.run}
          </button>
        </form>
      </aside>

      <section className="min-w-0 overflow-y-auto bg-base p-4">
        <div className="mb-4 rounded border border-warning/40 bg-warning/10 p-3 font-body-sm text-warning">
          {text.warning}
        </div>
        {!result ? (
          <div className="grid grid-cols-3 gap-3">
            {text.parameterHelp.map(([label, description]) => (
              <div className="rounded border border-border-subtle bg-bg-surface p-4" key={label}>
                <h3 className="font-label-caps text-text-primary">{label}</h3>
                <p className="mt-2 font-body-sm text-text-secondary">{description}</p>
              </div>
            ))}
            <div className="col-span-3 rounded border border-border-subtle bg-bg-surface p-4">
              <h3 className="font-label-caps text-text-primary">{text.emptyTitle}</h3>
              <p className="mt-2 font-body-sm text-text-secondary">{text.emptyBody}</p>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-4 gap-3">
              <Metric label={text.underlying} value={formatNumber(result.underlying_price)} />
              <Metric
                label={text.scannedExpirations}
                value={String(result.expiration_count ?? result.scanned_expirations?.length ?? 0)}
              />
              <Metric label="HV" value={formatPercent(result.historical_volatility)} />
              <Metric label={text.candidates} value={String(result.candidates.length)} />
            </div>
            <div className="overflow-x-auto rounded border border-border-subtle bg-bg-surface">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b border-border-subtle">
                    {text.headings.map((heading) => (
                      <th className="px-3 py-2 font-label-caps text-text-secondary" key={heading}>
                        {heading}
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
            <div className="rounded border border-border-subtle bg-bg-surface p-4">
              <h3 className="font-label-caps text-text-secondary">{text.assumptions}</h3>
              <ul className="mt-2 list-disc space-y-1 pl-5 font-body-sm text-text-secondary">
                {result.assumptions.map((assumption) => (
                  <li key={assumption}>{assumption}</li>
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
        className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary"
        step={step}
        type="number"
        {...registration}
      />
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-3">
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className="mt-2 font-data-mono text-lg font-bold text-text-primary">{value}</div>
    </div>
  );
}
