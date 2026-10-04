import { Info } from "lucide-react";
import { hermesCapabilityCopy } from "@/lib/hermes/copy";
import type { Locale } from "@/lib/locale";
import type { HermesDeliveryState } from "@/lib/hermes/types";

export type HermesCapabilityNoticeProps = {
  locale: Locale;
  deliveryState: HermesDeliveryState;
  readState?: "available" | "loading" | "unavailable";
};

/**
 * UI-1 Direction A: static delivery-state notice folded into one small text
 * line under the shell chrome (was a persistent card). Delivery-state
 * semantics are preserved verbatim; still not a live capability probe and
 * never repeats the global safety banner.
 */
export function HermesCapabilityNotice({
  locale,
  deliveryState,
  readState,
}: HermesCapabilityNoticeProps) {
  const blocked = deliveryState === "blocked_in_this_slice";
  const copy = blocked && readState === "available" ? {
    title: locale === "zh" ? "当前为只读模式" : "Read-only mode",
    body: locale === "zh" ? "可查看已保存会话和研究记录；暂不能发送新消息。" : "Saved conversations and research remain readable; new messages cannot be sent.",
  } : blocked && readState === "loading" ? {
    title: locale === "zh" ? "正在读取连接状态" : "Reading connection status",
    body: locale === "zh" ? "确认前暂不开放发送。" : "Sending stays disabled until the connection is checked.",
  } : hermesCapabilityCopy(locale, deliveryState);

  return (
    <section
      className="flex items-start gap-2"
      data-delivery-state={deliveryState}
      data-read-state={readState}
      data-testid="hermes-capability-notice"
    >
      <Info
        aria-hidden
        className="mt-0.5 shrink-0 text-text-secondary"
        size={14}
      />
      <p className="font-body-sm text-text-secondary">
        <span className="font-semibold text-text-primary">{copy.title}</span>
        {locale === "zh" ? "。" : ". "}
        {copy.body}
      </p>
    </section>
  );
}
