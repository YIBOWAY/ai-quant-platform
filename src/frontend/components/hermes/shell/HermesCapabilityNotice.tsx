import { Info } from "lucide-react";
import { hermesCapabilityCopy } from "@/lib/hermes/copy";
import type { Locale } from "@/lib/locale";
import type { HermesDeliveryState } from "@/lib/hermes/types";

export type HermesCapabilityNoticeProps = {
  locale: Locale;
  deliveryState: HermesDeliveryState;
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
}: HermesCapabilityNoticeProps) {
  const copy = hermesCapabilityCopy(locale, deliveryState);

  return (
    <section
      className="flex items-start gap-2"
      data-delivery-state={deliveryState}
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
