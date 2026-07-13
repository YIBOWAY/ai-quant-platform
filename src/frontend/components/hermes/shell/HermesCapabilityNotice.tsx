import { hermesCapabilityCopy } from "@/lib/hermes/copy";
import type { Locale } from "@/lib/locale";
import type { HermesDeliveryState } from "@/lib/hermes/types";

export type HermesCapabilityNoticeProps = {
  locale: Locale;
  deliveryState: HermesDeliveryState;
};

/**
 * Static delivery-state notice. Does not probe health/gateway/capability APIs
 * and must never repeat the global safety banner.
 */
export function HermesCapabilityNotice({
  locale,
  deliveryState,
}: HermesCapabilityNoticeProps) {
  const copy = hermesCapabilityCopy(locale, deliveryState);

  return (
    <section
      className="rounded-lg border border-border-subtle bg-bg-surface-muted px-4 py-3"
      data-delivery-state={deliveryState}
      data-testid="hermes-capability-notice"
    >
      <p className="font-body-md font-semibold text-text-primary">{copy.title}</p>
      <p className="mt-1 font-body-sm text-text-secondary">{copy.body}</p>
    </section>
  );
}
