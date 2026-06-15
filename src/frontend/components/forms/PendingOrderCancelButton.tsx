'use client';

import { useMutation } from "@tanstack/react-query";
import { XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ApiClientError, apiPost } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

type Locale = "en" | "zh";

const copy = {
  en: {
    cancel: "Cancel",
    cancelling: "Cancelling...",
    cancelled: "Pending order cancelled",
    cancelFailed: (message: string) =>
      message ? `Cancel failed: ${message}` : "Cancel failed",
    cancelAria: (orderId: string) => `Cancel pending limit order ${orderId}`,
  },
  zh: {
    cancel: "取消",
    cancelling: "取消中...",
    cancelled: "挂单已取消",
    cancelFailed: (message: string) =>
      message ? `取消失败：${message}` : "取消失败",
    cancelAria: (orderId: string) => `取消待处理限价单 ${orderId}`,
  },
} as const;

type CancelPendingOrderResult = {
  order: {
    status: string;
    order_id?: string | null;
    rejected_reason?: string | null;
  };
};

export function PendingOrderCancelButton({
  orderId,
  locale = "en",
}: {
  orderId: string;
  locale?: Locale;
}) {
  const router = useRouter();
  const isHydrated = useIsHydrated();
  const text = copy[locale];

  const mutation = useMutation({
    mutationFn: () =>
      apiPost<CancelPendingOrderResult>(
        `/api/paper/account/orders/${encodeURIComponent(orderId)}/cancel`,
        {},
      ),
    onSuccess: () => {
      toast.success(text.cancelled);
      router.refresh();
    },
    onError: (error) => {
      toast.error(
        text.cancelFailed(error instanceof ApiClientError ? error.message : ""),
      );
    },
  });

  return (
    <button
      aria-label={text.cancelAria(orderId)}
      className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-danger/40 bg-danger/10 px-2.5 py-1.5 font-body-sm text-xs font-semibold text-danger transition hover:bg-danger/15 disabled:cursor-not-allowed disabled:opacity-50"
      disabled={!isHydrated || mutation.isPending}
      onClick={() => mutation.mutate()}
      title={text.cancelAria(orderId)}
      type="button"
    >
      <XCircle size={13} />
      <span>{mutation.isPending ? text.cancelling : text.cancel}</span>
    </button>
  );
}
