'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import { useForm, useWatch, type UseFormRegisterReturn } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiClientError, apiPost, apiRequest } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };
const presets = {
  conservative: {
    max_delta: 0.2,
    min_apr: 5,
    min_dte: 14,
    max_dte: 45,
    max_spread_pct_input: 5,
    min_open_interest: 100,
    max_hv_iv: 0.75,
    trend_filter: true,
    hv_iv_filter: true,
  },
  balanced: {
    max_delta: 0.3,
    min_apr: 10,
    min_dte: 10,
    max_dte: 60,
    max_spread_pct_input: 15,
    min_open_interest: 50,
    max_hv_iv: 1.5,
    trend_filter: true,
    hv_iv_filter: true,
  },
  aggressive: {
    max_delta: 0.45,
    min_apr: 15,
    min_dte: 7,
    max_dte: 90,
    max_spread_pct_input: 25,
    min_open_interest: 20,
    max_hv_iv: 2,
    trend_filter: false,
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
    expiration: "Expiration",
    loadingExpirations: "Loading Futu expirations...",
    chain: "Option Chain Preview",
    chainHint: "Updates when ticker, strategy, or expiration changes.",
    noChain: "No option chain loaded",
    preset: "Preset",
    presetNone: "-- Preset --",
    conservative: "Conservative",
    balanced: "Balanced",
    aggressive: "Aggressive",
    maxDelta: "Max Delta",
    minApr: "Min APR (%)",
    minDte: "Min DTE",
    maxDte: "Max DTE",
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
    emptyBody: "Choose an expiration from Futu, tune the filters, then run the read-only screen.",
    underlying: "Underlying",
    candidates: "Candidates",
    assumptions: "Assumptions",
    strong: "Strong",
    watch: "Watch",
    avoid: "Avoid",
    headings: ["Symbol", "Type", "Strike", "Bid", "Ask", "Mid", "APR", "Spread", "IV", "Delta", "OI", "Rating"],
    parameterHelp: [
      ["Max Delta", "Lower absolute delta is more conservative for short premium screening."],
      ["Min APR", "Minimum annualized premium estimate. It is a simplified screen, not a guaranteed return."],
      ["DTE", "Expiration window. Very short DTE is noisy; very long DTE ties up capital."],
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
    expiration: "到期日",
    loadingExpirations: "正在读取 Futu 到期日...",
    chain: "期权链预览",
    chainHint: "标的、策略或到期日变化时自动刷新。",
    noChain: "尚未加载期权链",
    preset: "预设",
    presetNone: "-- 预设 --",
    conservative: "保守",
    balanced: "平衡",
    aggressive: "激进",
    maxDelta: "最大 Delta",
    minApr: "最低年化 (%)",
    minDte: "最小 DTE",
    maxDte: "最大 DTE",
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
    emptyBody: "先从 Futu 到期日列表选择日期，再调整筛选条件并运行。",
    underlying: "正股价格",
    candidates: "候选合约",
    assumptions: "假设说明",
    strong: "强烈",
    watch: "观察",
    avoid: "避开",
    headings: ["代码", "类型", "行权价", "买价", "卖价", "中间价", "年化", "价差", "IV", "Delta", "未平仓", "评级"],
    parameterHelp: [
      ["Max Delta", "绝对 Delta 越低越保守，适合卖方期权筛选。"],
      ["Min APR", "最低年化权利金估算。它只是筛选条件，不代表确定收益。"],
      ["DTE", "到期天数窗口。太短噪声大，太长资金占用久。"],
      ["Max Spread", "买卖价差上限。越低通常流动性越好。"],
      ["Min OI", "未平仓量下限。更高通常代表市场深度更好。"],
      ["Max HV/IV", "历史波动率除以隐含波动率。越低说明 IV 相对近期波动更充足。"],
    ],
  },
};

const screenerSchema = z.object({
  ticker: z.string().min(1),
  strategy_type: z.enum(["sell_put", "covered_call"]),
  expiration: z.string().min(1),
  min_iv_input: z.coerce.number().nonnegative(),
  max_delta: z.coerce.number().nonnegative().max(1),
  min_premium: z.coerce.number().nonnegative(),
  min_apr: z.coerce.number().nonnegative(),
  min_dte: z.coerce.number().int().nonnegative(),
  max_dte: z.coerce.number().int().nonnegative(),
  max_spread_pct_input: z.coerce.number().nonnegative(),
  min_open_interest: z.coerce.number().nonnegative(),
  max_hv_iv: z.coerce.number().nonnegative(),
  trend_filter: z.boolean(),
  hv_iv_filter: z.boolean(),
  provider: z.literal("futu"),
});

type ScreenerValues = z.infer<typeof screenerSchema>;

type ExpirationRow = {
  strike_time?: string;
  option_expiry_date_distance?: number;
  expiration_cycle?: string;
};

type ExpirationsResponse = {
  expirations: ExpirationRow[];
};

type ChainContract = {
  symbol: string;
  option_type?: string;
  strike?: number;
  expiry?: string;
  bid?: number | null;
  ask?: number | null;
  open_interest?: number | null;
};

type ChainResponse = {
  contracts: ChainContract[];
};

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
  historical_volatility?: number | null;
  hv_iv_ratio?: number | null;
  delta?: number | null;
  open_interest?: number | null;
  rating: string;
  notes: string[];
};

type ScreenerResult = {
  ticker: string;
  provider: "futu";
  strategy_type: string;
  expiration: string;
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

function dteLabel(row: ExpirationRow) {
  const date = row.strike_time ?? "";
  const distance = row.option_expiry_date_distance;
  if (typeof distance === "number") {
    return `${date} · ${distance} DTE`;
  }
  return date;
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
      expiration: "",
      min_iv_input: 0,
      max_delta: 0.3,
      min_premium: 0.1,
      min_apr: 10,
      min_dte: 10,
      max_dte: 60,
      max_spread_pct_input: 15,
      min_open_interest: 50,
      max_hv_iv: 1.5,
      trend_filter: true,
      hv_iv_filter: true,
      provider: "futu",
    },
  });
  const watched = useWatch({ control: form.control });
  const ticker = watched.ticker?.trim().toUpperCase() || "SPY";
  const strategyType = watched.strategy_type;
  const expiration = watched.expiration ?? "";
  const minDte = watched.min_dte ?? 0;
  const maxDte = watched.max_dte ?? 365;
  const optionType = strategyType === "sell_put" ? "PUT" : "CALL";

  const expirationsQuery = useQuery({
    queryKey: ["option-expirations", ticker],
    enabled: isHydrated && ticker.length > 0,
    queryFn: () =>
      apiRequest<ExpirationsResponse>(
        `/api/options/expirations?ticker=${encodeURIComponent(ticker)}&provider=futu`,
      ),
  });
  const expirations = useMemo(
    () =>
      (expirationsQuery.data?.expirations ?? [])
        .map((row) => ({ ...row, strike_time: row.strike_time ?? "" }))
        .filter((row) => row.strike_time),
    [expirationsQuery.data],
  );

  useEffect(() => {
    if (!expirations.length) {
      return;
    }
    const current = form.getValues("expiration");
    const eligible = expirations.find((row) => {
      const distance = row.option_expiry_date_distance;
      return typeof distance !== "number" || (distance >= minDte && distance <= maxDte);
    });
    const currentRow = expirations.find((row) => row.strike_time === current);
    const currentDistance = currentRow?.option_expiry_date_distance;
    const currentInRange =
      typeof currentDistance !== "number" || (currentDistance >= minDte && currentDistance <= maxDte);
    if (!current || !currentRow || !currentInRange) {
      form.setValue("expiration", eligible?.strike_time ?? expirations[0].strike_time ?? "", { shouldValidate: true });
    }
  }, [expirations, form, maxDte, minDte]);

  const chainQuery = useQuery({
    queryKey: ["option-chain", ticker, expiration, optionType],
    enabled: isHydrated && Boolean(ticker && expiration),
    queryFn: () =>
      apiRequest<ChainResponse>(
        `/api/options/chain?ticker=${encodeURIComponent(ticker)}&expiration=${encodeURIComponent(expiration)}&option_type=${optionType}&provider=futu`,
      ),
  });

  const mutation = useMutation({
    mutationFn: (values: ScreenerValues) =>
      apiPost<ScreenerResult>("/api/options/screener", {
        ...values,
        ticker: values.ticker.trim().toUpperCase(),
        min_iv: values.min_iv_input / 100,
        max_spread_pct: values.max_spread_pct_input / 100,
      }),
    onSuccess: (payload) => {
      toast.success(
        locale === "zh"
          ? `期权筛选返回 ${payload.candidates.length} 个候选`
          : `Options screener returned ${payload.candidates.length} candidates`,
      );
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;
  const expirationsError =
    expirationsQuery.error instanceof ApiClientError ? expirationsQuery.error.message : undefined;
  const chainError = chainQuery.error instanceof ApiClientError ? chainQuery.error.message : undefined;
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
        <p className="mt-1 font-body-sm text-text-secondary">
          {text.intro}
        </p>
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
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              {text.expiration}
              <select
                className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
                {...form.register("expiration")}
              >
                {expirations.length ? (
                  expirations.map((row) => (
                    <option key={row.strike_time} style={optionStyle} value={row.strike_time}>
                      {dteLabel(row)}
                    </option>
                  ))
                ) : (
                  <option style={optionStyle} value="">
                    {expirationsQuery.isLoading ? text.loadingExpirations : text.expiration}
                  </option>
                )}
              </select>
            </label>
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
          </div>
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
          {expirationsError ? <p className="font-body-sm text-danger">{expirationsError}</p> : null}
          {chainError ? <p className="font-body-sm text-danger">{chainError}</p> : null}
          {error ? <p className="font-body-sm text-danger">{error}</p> : null}
          <button
            className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!isHydrated || mutation.isPending || !expiration}
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
        <div className="mb-4 rounded border border-border-subtle bg-bg-surface p-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h3 className="font-headline-lg text-text-primary">{text.chain}</h3>
              <p className="font-body-sm text-text-secondary">{text.chainHint}</p>
            </div>
            <span className="font-data-mono text-data-mono text-text-secondary">
              {chainQuery.data?.contracts.length ?? 0} rows
            </span>
          </div>
          {chainQuery.data?.contracts.length ? (
            <div className="mt-3 max-h-48 overflow-auto">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b border-border-subtle">
                    <th className="py-2 font-label-caps text-text-secondary">Symbol</th>
                    <th className="py-2 text-right font-label-caps text-text-secondary">Strike</th>
                    <th className="py-2 text-right font-label-caps text-text-secondary">Bid</th>
                    <th className="py-2 text-right font-label-caps text-text-secondary">Ask</th>
                    <th className="py-2 text-right font-label-caps text-text-secondary">OI</th>
                  </tr>
                </thead>
                <tbody className="font-data-mono text-data-mono text-text-primary">
                  {chainQuery.data.contracts.slice(0, 12).map((contract) => (
                    <tr className="border-b border-border-subtle/50" key={contract.symbol}>
                      <td className="py-2">{contract.symbol}</td>
                      <td className="py-2 text-right">{formatNumber(contract.strike)}</td>
                      <td className="py-2 text-right">{formatNumber(contract.bid)}</td>
                      <td className="py-2 text-right">{formatNumber(contract.ask)}</td>
                      <td className="py-2 text-right">{formatNumber(contract.open_interest, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="mt-3 font-body-sm text-text-secondary">{text.noChain}</p>
          )}
        </div>
        {!result ? (
          <div className="grid grid-cols-3 gap-3">
            {text.parameterHelp.map(([label, description]) => (
              <div className="rounded border border-border-subtle bg-bg-surface p-4" key={label}>
                <h3 className="font-label-caps text-text-primary">{label}</h3>
                <p className="mt-2 font-body-sm text-text-secondary">{description}</p>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-4 gap-3">
              <Metric label={text.underlying} value={formatNumber(result.underlying_price)} />
              <Metric label={text.expiration} value={result.expiration} />
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
