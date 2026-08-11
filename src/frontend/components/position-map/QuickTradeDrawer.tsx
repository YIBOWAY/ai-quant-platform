'use client';

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import type { AccountPositionView, PaperAccountOrderResponse } from "@/lib/api";
import { ApiClientError, apiPost } from "@/lib/apiClient";

type Locale = "en" | "zh";
type Side = "buy" | "sell";

const drawerCopy = {
  en: {
    title: "Quick Order",
    paperBadge: "Paper",
    desc: "Submits straight to the paper account — same endpoint as the Paper Trading page.",
    symbol: "Symbol",
    side: "Side",
    buy: "Buy",
    sell: "Sell",
    quantity: "Quantity (shares)",
    limitPrice: "Limit price (optional)",
    limitHint: "Leave empty for the current paper price (Futu snapshot, else last close).",
    est: "Estimated value",
    submit: "Submit paper order",
    submitting: "Submitting...",
    all: "All",
    close: "Close",
    needValues: "Enter a quantity and a limit price (or leave price empty for market).",
    frozen: "Account is frozen — unfreeze on Paper Trading before submitting orders.",
    filled: (sym: string, side: Side, qty: number) =>
      `Filled: ${side === "buy" ? "bought" : "sold"} ${qty.toLocaleString()} ${sym}`,
    pending: (reason: string) => `Limit order queued${reason ? `: ${reason}` : ""}`,
    partial: (reason: string) => `Order partially filled${reason ? `: ${reason}` : ""}`,
    notFilled: (reason: string) => `Order not filled${reason ? `: ${reason}` : ""}`,
    failed: (reason: string) => `Order failed${reason ? `: ${reason}` : ""}`,
  },
  zh: {
    title: "快捷下单",
    paperBadge: "模拟",
    desc: "直接提交到模拟账户，与「模拟交易」页同一接口。",
    symbol: "标的",
    side: "方向",
    buy: "买入",
    sell: "卖出",
    quantity: "数量（股）",
    limitPrice: "限价（可选）",
    limitHint: "留空则按当前模拟价成交（优先 Futu 快照，否则最近收盘）。",
    est: "预估金额",
    submit: "提交模拟订单",
    submitting: "提交中...",
    all: "全部",
    close: "关闭",
    needValues: "请填写数量；价格留空按市价成交。",
    frozen: "账户已冻结 — 请先到「模拟交易」页解冻后再下单。",
    filled: (sym: string, side: Side, qty: number) =>
      `已成交：${side === "buy" ? "买入" : "卖出"} ${sym} ${qty.toLocaleString()} 股`,
    pending: (reason: string) => `限价单已挂起${reason ? `：${reason}` : ""}`,
    partial: (reason: string) => `订单部分成交${reason ? `：${reason}` : ""}`,
    notFilled: (reason: string) => `订单未成交${reason ? `：${reason}` : ""}`,
    failed: (reason: string) => `下单失败${reason ? `：${reason}` : ""}`,
  },
} as const;

export type QuickTradeRequest = { symbol?: string; side?: Side };

const inputClass =
  "w-full rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 font-data-mono text-sm text-text-primary outline-none transition-colors focus:border-info";
const labelClass = "block font-label-caps text-text-secondary";

export function QuickTradeDrawer({
  locale,
  positions,
  request,
  onClose,
  accountFrozen = false,
}: {
  locale: Locale;
  positions: AccountPositionView[];
  /** Non-null => drawer is open. */
  request: QuickTradeRequest | null;
  onClose: () => void;
  /** Paper account kill_switch / freeze — mirror Paper Trading form disabled state. */
  accountFrozen?: boolean;
}) {
  const router = useRouter();
  const text = drawerCopy[locale];
  const open = request !== null;

  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState<Side>("buy");
  const [quantity, setQuantity] = useState("");
  const [limitPrice, setLimitPrice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const formDisabled = accountFrozen || submitting;

  const position = useMemo(
    () => positions.find((row) => row.symbol === symbol.trim().toUpperCase()),
    [positions, symbol],
  );
  const maxSellQty = side === "sell" && position ? Math.abs(position.quantity) : null;

  // Seed fields whenever the drawer is opened with a fresh request.
  // Render-time adjustment (react.dev "You Might Not Need an Effect"):
  // `request` is a new object on every open, so identity change = reseed.
  const [lastRequest, setLastRequest] = useState<QuickTradeRequest | null>(null);
  if (request !== lastRequest) {
    setLastRequest(request);
    if (request) {
      const sym = request.symbol ?? "";
      const nextSide = request.side ?? "buy";
      const pos = positions.find((row) => row.symbol === sym);
      setSymbol(sym);
      setSide(nextSide);
      setQuantity(nextSide === "sell" && pos ? String(Math.abs(pos.quantity)) : "");
      setLimitPrice(pos && Number.isFinite(pos.last_price) ? pos.last_price.toFixed(2) : "");
    }
  }

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const qtyNum = Number(quantity);
  const priceNum = Number(limitPrice);
  const estimate =
    Number.isFinite(qtyNum) && qtyNum > 0 && Number.isFinite(priceNum) && priceNum > 0
      ? qtyNum * priceNum
      : null;

  async function submit() {
    if (accountFrozen) {
      toast.warning(text.frozen);
      return;
    }
    const sym = symbol.trim().toUpperCase();
    if (!sym || !(qtyNum > 0)) {
      toast.warning(text.needValues);
      return;
    }
    setSubmitting(true);
    try {
      const payload = await apiPost<PaperAccountOrderResponse>("/api/paper/account/orders", {
        symbol: sym,
        side,
        quantity: qtyNum,
        limit_price: Number.isFinite(priceNum) && priceNum > 0 ? priceNum : undefined,
      });
      const status = payload.order.status;
      const reason = payload.order.rejected_reason ?? "";
      if (status === "filled") {
        toast.success(text.filled(sym, side, qtyNum));
        onClose();
      } else if (status === "partially_filled") {
        toast.warning(text.partial(reason));
        onClose();
      } else if (status === "pending") {
        toast.warning(text.pending(reason));
        onClose();
      } else {
        toast.warning(text.notFilled(reason));
      }
      router.refresh();
    } catch (error) {
      toast.error(text.failed(error instanceof ApiClientError ? error.message : ""));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <div
        aria-hidden
        onClick={onClose}
        className={`fixed inset-0 z-40 bg-black/50 backdrop-blur-[2px] transition-opacity duration-200 ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />
      <aside
        role="dialog"
        aria-label={text.title}
        className={`fixed inset-y-0 right-0 z-50 flex w-[400px] max-w-[92vw] flex-col border-l border-border-subtle bg-bg-surface shadow-[-24px_0_60px_rgba(0,0,0,0.45)] transition-transform duration-300 ease-out ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border-subtle px-5 py-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-label-caps text-text-primary">{text.title}</h2>
              <span className="rounded-full border border-info/40 bg-info/10 px-2 py-0.5 font-data-mono text-[10px] uppercase text-info">
                {text.paperBadge}
              </span>
            </div>
            <p className="mt-1 font-body-sm text-text-secondary">{text.desc}</p>
            {accountFrozen ? (
              <p className="mt-2 font-body-sm text-danger" data-position-map-frozen="true">
                {text.frozen}
              </p>
            ) : null}
          </div>
          <button
            aria-label={text.close}
            className="rounded-md px-2 py-1 text-text-secondary transition-colors hover:bg-bg-surface-muted hover:text-text-primary"
            onClick={onClose}
            type="button"
          >
            ✕
          </button>
        </div>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-5 py-5">
          <fieldset className="contents" disabled={formDisabled}>
          <div>
            <label className={labelClass} htmlFor="qtd-symbol">{text.symbol}</label>
            <input
              autoComplete="off"
              className={`${inputClass} mt-1.5`}
              id="qtd-symbol"
              list="qtd-symbols"
              onChange={(event) => setSymbol(event.target.value.toUpperCase())}
              placeholder="MU"
              value={symbol}
            />
            <datalist id="qtd-symbols">
              {positions.map((row) => (
                <option key={row.symbol} value={row.symbol} />
              ))}
            </datalist>
          </div>

          <div>
            <span className={labelClass}>{text.side}</span>
            <div className="mt-1.5 grid grid-cols-2 gap-2">
              <button
                className={`rounded-lg border px-3 py-2 font-body-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                  side === "buy"
                    ? "border-info bg-info/15 text-info"
                    : "border-border-subtle bg-bg-surface-muted text-text-secondary hover:text-text-primary"
                }`}
                disabled={formDisabled}
                onClick={() => setSide("buy")}
                type="button"
              >
                {text.buy}
              </button>
              <button
                className={`rounded-lg border px-3 py-2 font-body-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                  side === "sell"
                    ? "border-danger bg-danger/15 text-danger"
                    : "border-border-subtle bg-bg-surface-muted text-text-secondary hover:text-text-primary"
                }`}
                disabled={formDisabled}
                onClick={() => setSide("sell")}
                type="button"
              >
                {text.sell}
              </button>
            </div>
          </div>

          <div>
            <label className={labelClass} htmlFor="qtd-qty">{text.quantity}</label>
            <input
              className={`${inputClass} mt-1.5`}
              id="qtd-qty"
              inputMode="decimal"
              min="0"
              onChange={(event) => setQuantity(event.target.value)}
              type="number"
              value={quantity}
            />
            {maxSellQty !== null ? (
              <div className="mt-2 grid grid-cols-3 gap-2">
                {[0.25, 0.5, 1].map((pct) => (
                  <button
                    className="rounded-md border border-border-subtle px-2 py-1 font-data-mono text-[11px] text-text-secondary transition-colors hover:border-info hover:text-info"
                    key={pct}
                    onClick={() => setQuantity(String(Math.floor(maxSellQty * pct)))}
                    type="button"
                  >
                    {pct === 1 ? text.all : `${pct * 100}%`}
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <div>
            <label className={labelClass} htmlFor="qtd-price">{text.limitPrice}</label>
            <input
              className={`${inputClass} mt-1.5`}
              id="qtd-price"
              inputMode="decimal"
              min="0"
              onChange={(event) => setLimitPrice(event.target.value)}
              step="0.01"
              type="number"
              value={limitPrice}
            />
            <p className="mt-1.5 font-body-sm text-text-secondary">{text.limitHint}</p>
          </div>

          <div className="flex items-center justify-between rounded-lg border border-dashed border-border-subtle bg-bg-surface-muted px-3 py-2.5 font-data-mono text-sm">
            <span className="text-text-secondary">{text.est}</span>
            <span className="font-semibold text-text-primary">
              {estimate !== null
                ? `$${estimate.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                : "--"}
            </span>
          </div>

          <button
            className="rounded-lg border border-[#0C6B56] bg-[#0C6B56] px-4 py-2.5 text-center font-body-sm font-semibold text-[#DFF3EC] transition-colors hover:bg-[#0E7E66] disabled:cursor-not-allowed disabled:opacity-50"
            disabled={formDisabled}
            onClick={submit}
            type="button"
          >
            {submitting ? text.submitting : text.submit}
          </button>
          </fieldset>
        </div>
      </aside>
    </>
  );
}
