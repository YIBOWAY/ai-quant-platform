'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { accountRebalanceStrategies } from "@/lib/accountRebalanceStrategies";
import type { StrategyMetadata } from "@/lib/api";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";
import { localizePath } from "@/lib/locale";
import { ArrowRight, RefreshCw } from "lucide-react";

type Locale = "en" | "zh";

const copy = {
  en: {
    manualTitle: "Manual Order",
    manualDesc: "Buy or sell a US stock at the current price (Futu snapshot, else last close).",
    symbol: "Symbol",
    symbolRequired: "Enter a symbol",
    side: "Side",
    buy: "Buy",
    sell: "Sell",
    sizeMode: "Size by",
    quantity: "Quantity",
    notional: "Notional ($)",
    sizeRequired: "Enter a positive size",
    limitPrice: "Limit price (optional)",
    limitPriceHint: "If the current paper price does not meet the limit, the order stays pending until a later check.",
    submit: "Submit Order",
    submitting: "Submitting...",
    checkPending: "Check Pending Limits",
    checkingPending: "Checking...",
    rebalanceTitle: "Strategy Rebalance",
    rebalanceDesc: "Apply a strategy's latest target weights to the account in one click.",
    strategy: "Strategy",
    candidates: "Candidate Symbols",
    topN: "Top N",
    lookback: "Lookback",
    rebalance: "Rebalance to Strategy",
    rebalancing: "Rebalancing...",
    freezeTitle: "Account Freeze",
    freezeDesc: "Freeze blocks all new orders on this paper account. It does not touch live trading.",
    frozen: "Account is FROZEN",
    active: "Account is ACTIVE",
    freeze: "Freeze account",
    unfreeze: "Unfreeze account",
    freezeFailed: (reason: string) => `Freeze toggle failed${reason ? `: ${reason}` : ""}`,
    orderOk: (s: string) => `Order ${s}`,
    orderPending: (reason: string) => `Limit order queued${reason ? `: ${reason}` : ""}`,
    orderPartial: (reason: string) => `Order partially filled${reason ? `: ${reason}` : ""}`,
    orderNotFilled: (reason: string) => `Order not filled${reason ? `: ${reason}` : ""}`,
    pendingChecked: (filled: number, pending: number) =>
      `Pending limits checked: ${filled} filled, ${pending} still pending`,
    pendingFailed: (reason: string) => `Pending check failed${reason ? `: ${reason}` : ""}`,
    rebalanceOk: (n: number) => `Rebalanced: ${n} legs filled`,
    rebalanceAborted: (reason: string) => `Rebalance stopped before trading${reason ? `: ${reason}` : ""}`,
    frozenToggle: (v: boolean) => (v ? "Account frozen" : "Account unfrozen"),
    receiptTitle: "Last rebalance",
    receiptSold: "Sold",
    receiptBought: "Bought",
    receiptNoFills: "No legs filled.",
    receiptShares: (q: number) => `${q.toLocaleString(undefined, { maximumFractionDigits: 2 })} sh`,
    targetWeights: "Target weights",
    viewOnMap: "View on position map",
    strategies: {
      cross_sectional_top_n: {
        name: "Cross-Sectional Momentum Top-N",
        hint: "Ranks the candidates by recent blended momentum score and holds the top N, equal weight.",
      },
      mean_reversion_top_n: {
        name: "Mean-Reversion Top-N",
        hint: "Buys the N most oversold candidates, betting on a short-term bounce back to the mean.",
      },
    } as Record<string, { name: string; hint: string }>,
  },
  zh: {
    manualTitle: "手动下单",
    manualDesc: "按当前价买入或卖出一只美股（优先 Futu 实时快照，否则用最近收盘价）。",
    symbol: "标的",
    symbolRequired: "请输入标的代码",
    side: "方向",
    buy: "买入",
    sell: "卖出",
    sizeMode: "下单方式",
    quantity: "数量（股）",
    notional: "金额（美元）",
    sizeRequired: "请输入大于 0 的数量/金额",
    limitPrice: "限价（可选）",
    limitPriceHint: "如果当前模拟价格未触及限价，订单会保留为待处理，后续可再次检查。",
    submit: "提交订单",
    submitting: "提交中...",
    checkPending: "检查挂单",
    checkingPending: "检查中...",
    rebalanceTitle: "策略再平衡",
    rebalanceDesc: "一键把某个策略的最新目标权重应用到账户。",
    strategy: "策略",
    candidates: "候选标的",
    topN: "持仓数 Top N",
    lookback: "回看窗口",
    rebalance: "按策略再平衡",
    rebalancing: "再平衡中...",
    freezeTitle: "账户冻结",
    freezeDesc: "冻结会阻止该模拟账户的所有新订单，不影响（也不存在）实盘交易。",
    frozen: "账户已冻结",
    active: "账户运行中",
    freeze: "冻结账户",
    unfreeze: "解冻账户",
    freezeFailed: (reason: string) => `冻结开关切换失败${reason ? `：${reason}` : ""}`,
    orderOk: (s: string) => `订单${s === "filled" ? "已成交" : s}`,
    orderPending: (reason: string) => `限价单已挂起${reason ? `：${reason}` : ""}`,
    orderPartial: (reason: string) => `订单部分成交${reason ? `：${reason}` : ""}`,
    orderNotFilled: (reason: string) => `订单未成交${reason ? `：${reason}` : ""}`,
    pendingChecked: (filled: number, pending: number) =>
      `挂单检查完成：${filled} 笔成交，${pending} 笔仍待处理`,
    pendingFailed: (reason: string) => `挂单检查失败${reason ? `：${reason}` : ""}`,
    rebalanceOk: (n: number) => `再平衡完成：${n} 笔成交`,
    rebalanceAborted: (reason: string) => `再平衡已在成交前停止${reason ? `：${reason}` : ""}`,
    frozenToggle: (v: boolean) => (v ? "账户已冻结" : "账户已解冻"),
    receiptTitle: "本次再平衡变化",
    receiptSold: "卖出",
    receiptBought: "买入",
    receiptNoFills: "没有成交。",
    receiptShares: (q: number) => `${q.toLocaleString(undefined, { maximumFractionDigits: 2 })} 股`,
    targetWeights: "目标权重",
    viewOnMap: "在持仓地图查看",
    strategies: {
      cross_sectional_top_n: {
        name: "横截面动量 Top-N",
        hint: "按近期混合动量得分给候选标的排序，等权持有得分最高的前 N 名。",
      },
      mean_reversion_top_n: {
        name: "均值回归 Top-N",
        hint: "买入近期超跌最深的前 N 名，押注短期向均值反弹。",
      },
    } as Record<string, { name: string; hint: string }>,
  },
} as const;

const manualSchema = z
  .object({
    symbol: z.string().min(1),
    side: z.enum(["buy", "sell"]),
    sizeMode: z.enum(["quantity", "notional"]),
    quantity: z.coerce.number().positive().optional(),
    notional: z.coerce.number().positive().optional(),
    limit_price: z.number().positive().optional(),
  })
  .refine((v) => (v.sizeMode === "quantity" ? v.quantity != null : v.notional != null), {
    message: "size",
    path: ["quantity"],
  });

type ManualValues = z.infer<typeof manualSchema>;

const rebalanceSchema = z.object({
  strategy_id: z.string().min(1),
  symbols: z.string().min(1),
  top_n: z.coerce.number().int().positive(),
  lookback: z.coerce.number().int().positive(),
});

type RebalanceValues = z.infer<typeof rebalanceSchema>;

type OrderResult = { order: { status: string; rejected_reason?: string } };
type ProcessPendingResult = {
  orders: Array<{ status: string }>;
};
type RebalanceLeg = {
  status: string;
  symbol: string;
  side: string;
  filled_quantity: number;
  price: number;
};
type RebalanceResult = {
  rebalance: {
    aborted: boolean;
    note?: string;
    orders: RebalanceLeg[];
    target_weights?: Record<string, number>;
    as_of?: string;
  };
};

type Receipt = {
  legs: RebalanceLeg[];
  targetWeights: Record<string, number> | null;
};

const inputClass =
  "rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 font-data-mono text-text-primary";
const labelClass = "flex flex-col gap-1 font-body-sm text-text-primary";

export function AccountTradePanel({
  locale = "en",
  killSwitch = false,
  pendingOrderCount = 0,
  strategies = [],
}: {
  locale?: Locale;
  killSwitch?: boolean;
  pendingOrderCount?: number;
  strategies?: StrategyMetadata[];
}) {
  const router = useRouter();
  const isHydrated = useIsHydrated();
  const text = copy[locale];
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const rebalanceStrategies = accountRebalanceStrategies(strategies);
  const defaultRebalanceStrategyId =
    rebalanceStrategies[0]?.id ?? "cross_sectional_top_n";

  const manualForm = useForm<ManualValues>({
    resolver: zodResolver(manualSchema),
    defaultValues: { symbol: "AAPL", side: "buy", sizeMode: "quantity", quantity: 100 },
  });
  const rebalanceForm = useForm<RebalanceValues>({
    resolver: zodResolver(rebalanceSchema),
    defaultValues: {
      strategy_id: defaultRebalanceStrategyId,
      symbols: "SPY,QQQ,IWM,DIA",
      top_n: 3,
      lookback: 20,
    },
  });

  const manualMutation = useMutation({
    mutationFn: (values: ManualValues) =>
      apiPost<OrderResult>("/api/paper/account/orders", {
        symbol: values.symbol.toUpperCase().trim(),
        side: values.side,
        quantity: values.sizeMode === "quantity" ? values.quantity : undefined,
        notional: values.sizeMode === "notional" ? values.notional : undefined,
        limit_price: values.limit_price,
      }),
    onSuccess: (payload) => {
      if (payload.order.status === "filled") {
        toast.success(text.orderOk(payload.order.status), {
          action: {
            label: text.viewOnMap,
            onClick: () => router.push(localizePath("/position-map", locale)),
          },
        });
      } else if (payload.order.status === "partially_filled") {
        toast.warning(text.orderPartial(payload.order.rejected_reason ?? ""));
      } else if (payload.order.status === "pending") {
        toast.warning(text.orderPending(payload.order.rejected_reason ?? ""));
      } else {
        toast.warning(text.orderNotFilled(payload.order.rejected_reason ?? ""));
      }
      router.refresh();
    },
  });

  const rebalanceMutation = useMutation({
    mutationFn: (values: RebalanceValues) =>
      apiPost<RebalanceResult>("/api/paper/account/rebalance", {
        strategy_id: values.strategy_id,
        symbols: splitSymbols(values.symbols),
        top_n: values.top_n,
        lookback: values.lookback,
      }),
    onSuccess: (payload) => {
      const filled = payload.rebalance.orders.filter((o) => o.status === "filled").length;
      if (payload.rebalance.aborted) {
        toast.error(text.rebalanceAborted(payload.rebalance.note ?? ""));
        setReceipt(null);
      } else {
        toast.success(text.rebalanceOk(filled), {
          action: {
            label: text.viewOnMap,
            onClick: () => router.push(localizePath("/position-map", locale)),
          },
        });
        setReceipt({
          legs: payload.rebalance.orders.filter((o) => o.filled_quantity > 0),
          targetWeights: payload.rebalance.target_weights ?? null,
        });
      }
      router.refresh();
    },
  });

  const freezeMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      apiPost<unknown>("/api/paper/account/kill-switch", { enabled }),
    onSuccess: (_payload, enabled) => {
      toast.success(text.frozenToggle(enabled));
      router.refresh();
    },
    onError: (error) => {
      toast.error(
        text.freezeFailed(error instanceof ApiClientError ? error.message : ""),
      );
    },
  });

  const processPendingMutation = useMutation({
    mutationFn: () => apiPost<ProcessPendingResult>("/api/paper/account/orders/process", {}),
    onSuccess: (payload) => {
      const filled = payload.orders.filter((order) => order.status === "filled").length;
      const pending = payload.orders.filter((order) => order.status === "pending").length;
      toast.info(text.pendingChecked(filled, pending));
      router.refresh();
    },
    onError: (error) => {
      toast.error(
        text.pendingFailed(error instanceof ApiClientError ? error.message : ""),
      );
    },
  });

  const manualError =
    manualMutation.error instanceof ApiClientError ? manualMutation.error.message : undefined;
  const rebalanceError =
    rebalanceMutation.error instanceof ApiClientError ? rebalanceMutation.error.message : undefined;
  const sizeMode = useWatch({ control: manualForm.control, name: "sizeMode" });
  const selectedStrategy = useWatch({ control: rebalanceForm.control, name: "strategy_id" });
  const manualFieldErrors = manualForm.formState.errors;

  return (
    <div className="flex flex-col gap-4">
      <form
        className="flex flex-col gap-3 rounded-lg border border-border-subtle bg-bg-surface p-4"
        onSubmit={manualForm.handleSubmit((v) => manualMutation.mutate(v))}
      >
        <fieldset
          className="contents"
          disabled={!isHydrated || killSwitch || manualMutation.isPending}
        >
        <div>
          <h2 className="font-label-caps text-text-primary">{text.manualTitle}</h2>
          <p className="mt-1 font-body-sm text-text-secondary">{text.manualDesc}</p>
        </div>
        <label className={labelClass}>
          {text.symbol}
          <input className={inputClass} {...manualForm.register("symbol")} />
          {manualFieldErrors.symbol ? (
            <span className="font-body-sm text-danger">{text.symbolRequired}</span>
          ) : null}
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className={labelClass}>
            {text.side}
            <select className={inputClass} {...manualForm.register("side")}>
              <option value="buy">{text.buy}</option>
              <option value="sell">{text.sell}</option>
            </select>
          </label>
          <label className={labelClass}>
            {text.sizeMode}
            <select className={inputClass} {...manualForm.register("sizeMode")}>
              <option value="quantity">{text.quantity}</option>
              <option value="notional">{text.notional}</option>
            </select>
          </label>
        </div>
        {sizeMode === "quantity" ? (
          <label className={labelClass}>
            {text.quantity}
            <input className={inputClass} type="number" step="any" min={0}
              {...manualForm.register("quantity", { valueAsNumber: true })} />
            {manualFieldErrors.quantity ? (
              <span className="font-body-sm text-danger">{text.sizeRequired}</span>
            ) : null}
          </label>
        ) : (
          <label className={labelClass}>
            {text.notional}
            <input className={inputClass} type="number" step="any" min={0}
              {...manualForm.register("notional", { valueAsNumber: true })} />
            {manualFieldErrors.notional || manualFieldErrors.quantity ? (
              <span className="font-body-sm text-danger">{text.sizeRequired}</span>
            ) : null}
          </label>
        )}
        <label className={labelClass}>
          {text.limitPrice}
          <input
            className={inputClass}
            min={0}
            step="any"
            type="number"
            {...manualForm.register("limit_price", {
              setValueAs: (value) => (value === "" ? undefined : Number(value)),
            })}
          />
          <span className="font-body-sm text-text-secondary">{text.limitPriceHint}</span>
        </label>
        {manualError ? <p className="font-body-sm text-danger">{manualError}</p> : null}
        <button
          className="rounded-lg bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isHydrated || killSwitch || manualMutation.isPending}
          type="submit"
        >
          {manualMutation.isPending ? text.submitting : text.submit}
        </button>
        </fieldset>
      </form>

      <button
        className="flex items-center justify-center gap-2 rounded-lg border border-info/40 bg-info/10 px-4 py-2 font-body-sm font-semibold text-info disabled:cursor-not-allowed disabled:opacity-50"
        disabled={
          !isHydrated ||
          killSwitch ||
          pendingOrderCount === 0 ||
          processPendingMutation.isPending
        }
        onClick={() => processPendingMutation.mutate()}
        type="button"
      >
        <RefreshCw size={15} />
        {processPendingMutation.isPending ? text.checkingPending : text.checkPending}
        {pendingOrderCount > 0 ? (
          <span className="font-data-mono text-xs">({pendingOrderCount})</span>
        ) : null}
      </button>

      <form
        className="flex flex-col gap-3 rounded-lg border border-border-subtle bg-bg-surface p-4"
        onSubmit={rebalanceForm.handleSubmit((v) => rebalanceMutation.mutate(v))}
      >
        <fieldset
          className="contents"
          disabled={!isHydrated || killSwitch || rebalanceMutation.isPending}
        >
        <div>
          <h2 className="font-label-caps text-text-primary">{text.rebalanceTitle}</h2>
          <p className="mt-1 font-body-sm text-text-secondary">{text.rebalanceDesc}</p>
        </div>
        <label className={labelClass}>
          {text.strategy}
          <select className={inputClass} {...rebalanceForm.register("strategy_id")}>
            {rebalanceStrategies.map((strategy) => (
              <option key={strategy.id} value={strategy.id}>
                {text.strategies[strategy.id]?.name ?? strategy.name}
              </option>
            ))}
          </select>
          <span className="font-body-sm text-text-secondary">
            {text.strategies[selectedStrategy]?.hint ??
              rebalanceStrategies.find((strategy) => strategy.id === selectedStrategy)
                ?.description}
            <span className="ml-1 font-data-mono text-[10px] text-text-secondary/70">
              ({selectedStrategy})
            </span>
          </span>
        </label>
        <label className={labelClass}>
          {text.candidates}
          <input className={inputClass} {...rebalanceForm.register("symbols")} />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className={labelClass}>
            {text.topN}
            <input className={inputClass} type="number" min={1}
              {...rebalanceForm.register("top_n", { valueAsNumber: true })} />
          </label>
          <label className={labelClass}>
            {text.lookback}
            <input className={inputClass} type="number" min={1}
              {...rebalanceForm.register("lookback", { valueAsNumber: true })} />
          </label>
        </div>
        {rebalanceError ? <p className="font-body-sm text-danger">{rebalanceError}</p> : null}
        <button
          className="rounded-lg border border-accent-success bg-accent-success/10 px-4 py-2 font-body-sm font-semibold text-accent-success disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isHydrated || killSwitch || rebalanceMutation.isPending}
          type="submit"
        >
          {rebalanceMutation.isPending ? text.rebalancing : text.rebalance}
        </button>
        </fieldset>
      </form>

      {receipt ? (
        <div className="flex flex-col gap-2 rounded-lg border border-info/30 bg-info/5 p-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-label-caps text-text-primary">{text.receiptTitle}</h2>
            <Link
              className="flex items-center gap-1 font-body-sm text-info underline-offset-2 hover:underline"
              href={localizePath("/position-map", locale)}
            >
              {text.viewOnMap}
              <ArrowRight size={13} />
            </Link>
          </div>
          {receipt.targetWeights && Object.keys(receipt.targetWeights).length ? (
            <p className="font-data-mono text-xs text-text-secondary">
              {text.targetWeights}:{" "}
              {Object.entries(receipt.targetWeights)
                .sort(([, a], [, b]) => b - a)
                .map(([symbol, weight]) => `${symbol} ${(weight * 100).toFixed(0)}%`)
                .join(" · ")}
            </p>
          ) : null}
          {receipt.legs.length === 0 ? (
            <p className="font-body-sm text-text-secondary">{text.receiptNoFills}</p>
          ) : (
            <ul className="flex flex-col gap-1 font-data-mono text-sm">
              {receipt.legs.map((leg, index) => {
                const isBuy = leg.side.toLowerCase().includes("buy");
                return (
                  <li
                    key={`${leg.symbol}-${index}`}
                    className="flex items-center justify-between gap-3"
                  >
                    <span className={isBuy ? "text-accent-success" : "text-danger"}>
                      {isBuy ? text.receiptBought : text.receiptSold} {leg.symbol}
                    </span>
                    <span className="text-text-secondary">
                      {text.receiptShares(leg.filled_quantity)} @ {leg.price.toFixed(2)}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : null}

      <div className="flex flex-col gap-3 rounded-lg border border-border-subtle bg-bg-surface p-4">
        <div>
          <h2 className="font-label-caps text-text-primary">{text.freezeTitle}</h2>
          <p className="mt-1 font-body-sm text-text-secondary">{text.freezeDesc}</p>
        </div>
        <div className={`font-data-mono ${killSwitch ? "text-danger" : "text-accent-success"}`}>
          {killSwitch ? text.frozen : text.active}
        </div>
        <button
          className="rounded-lg border border-warning/40 bg-warning/10 px-4 py-2 font-body-sm text-warning disabled:opacity-50"
          disabled={!isHydrated || freezeMutation.isPending}
          onClick={() => freezeMutation.mutate(!killSwitch)}
          type="button"
        >
          {killSwitch ? text.unfreeze : text.freeze}
        </button>
      </div>
    </div>
  );
}
