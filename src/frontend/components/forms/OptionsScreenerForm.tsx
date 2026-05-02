'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiClientError, apiPost } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };
const copy = {
  en: {
    title: "Options Screener",
    intro: "Read-only Futu data. No orders, no account unlock, no live trading.",
    ticker: "Ticker",
    strategy: "Strategy",
    sellPut: "Sell Put",
    coveredCall: "Covered Call / Sell Call",
    expiration: "Expiration",
    expirationPlaceholder: "auto nearest, or YYYY-MM-DD",
    minIv: "Min IV",
    maxDelta: "Max Delta",
    minPremium: "Min Premium",
    maxSpread: "Max Spread",
    trendFilter: "Trend filter",
    hvIvFilter: "HV / IV timing filter",
    run: "Run Screener",
    running: "Running...",
    warning: "Research-only output. These rows are not trade instructions and cannot place orders.",
    emptyTitle: "No screener run yet",
    emptyBody: "Enter a ticker and run a read-only Futu options screen.",
    underlying: "Underlying",
    candidates: "Candidates",
    assumptions: "Assumptions",
    headings: ["Symbol", "Type", "Strike", "Bid", "Ask", "Mid", "Yield", "Spread", "IV", "Delta", "Rating"],
  },
  zh: {
    title: "期权筛选器",
    intro: "只读 Futu 数据。不下单、不解锁账户、不接入实盘。",
    ticker: "标的",
    strategy: "策略",
    sellPut: "卖出 Put",
    coveredCall: "备兑 Call / 卖出 Call",
    expiration: "到期日",
    expirationPlaceholder: "自动选择最近到期日，或输入 YYYY-MM-DD",
    minIv: "最低 IV",
    maxDelta: "最大 Delta",
    minPremium: "最低权利金",
    maxSpread: "最大价差",
    trendFilter: "趋势过滤",
    hvIvFilter: "HV / IV 时机过滤",
    run: "运行筛选",
    running: "运行中...",
    warning: "仅用于研究。这些结果不是交易建议，也不能发出真实订单。",
    emptyTitle: "还没有运行筛选",
    emptyBody: "输入标的后运行一次只读 Futu 期权筛选。",
    underlying: "正股价格",
    candidates: "候选数",
    assumptions: "假设说明",
    headings: ["代码", "类型", "行权价", "买价", "卖价", "中间价", "年化估算", "价差", "IV", "Delta", "评级"],
  },
};

const screenerSchema = z.object({
  ticker: z.string().min(1),
  strategy_type: z.enum(["sell_put", "covered_call"]),
  expiration: z.string().optional(),
  min_iv: z.coerce.number().nonnegative(),
  max_delta: z.coerce.number().nonnegative().max(1),
  min_premium: z.coerce.number().nonnegative(),
  max_spread_pct: z.coerce.number().nonnegative(),
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
  historical_volatility?: number | null;
  delta?: number | null;
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

export function OptionsScreenerForm({ locale = "en" }: { locale?: "en" | "zh" }) {
  const isHydrated = useIsHydrated();
  const text = copy[locale];
  const form = useForm<ScreenerValues>({
    resolver: zodResolver(screenerSchema),
    defaultValues: {
      ticker: "AAPL",
      strategy_type: "sell_put",
      expiration: "",
      min_iv: 0,
      max_delta: 0.35,
      min_premium: 0.1,
      max_spread_pct: 0.35,
      trend_filter: true,
      hv_iv_filter: false,
      provider: "futu",
    },
  });
  const mutation = useMutation({
    mutationFn: (values: ScreenerValues) =>
      apiPost<ScreenerResult>("/api/options/screener", {
        ...values,
        expiration: values.expiration?.trim() || null,
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
  const run = form.handleSubmit((values) => mutation.mutate(values));
  const result = mutation.data;

  return (
    <div className="grid h-full min-h-0 grid-cols-[340px_1fr] overflow-hidden">
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
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.ticker}
            <input
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
              {...form.register("ticker")}
            />
          </label>
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
            {text.expiration}
            <input
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
              placeholder={text.expirationPlaceholder}
              {...form.register("expiration")}
            />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              {text.minIv}
              <input
                className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary"
                step={0.01}
                type="number"
                {...form.register("min_iv", { valueAsNumber: true })}
              />
            </label>
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              {text.maxDelta}
              <input
                className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary"
                step={0.01}
                type="number"
                {...form.register("max_delta", { valueAsNumber: true })}
              />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              {text.minPremium}
              <input
                className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary"
                step={0.01}
                type="number"
                {...form.register("min_premium", { valueAsNumber: true })}
              />
            </label>
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              {text.maxSpread}
              <input
                className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary"
                step={0.01}
                type="number"
                {...form.register("max_spread_pct", { valueAsNumber: true })}
              />
            </label>
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
          <div className="rounded border border-border-subtle bg-bg-surface p-6">
            <h3 className="font-headline-lg text-text-primary">{text.emptyTitle}</h3>
            <p className="mt-2 font-body-sm text-text-secondary">
              {text.emptyBody}
            </p>
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
                      <td className="px-3 py-2">{candidate.rating}</td>
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-3">
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className="mt-2 font-data-mono text-lg font-bold text-text-primary">{value}</div>
    </div>
  );
}
