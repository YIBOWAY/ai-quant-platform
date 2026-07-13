import { ComposerDock } from "@/components/hermes/ComposerDock";
import { HermesCapabilityNotice } from "@/components/hermes/shell/HermesCapabilityNotice";
import { HermesInternalNav } from "@/components/hermes/shell/HermesInternalNav";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import type { HermesDeliveryState } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";

export type HermesWorkbenchShellProps = {
  locale: Locale;
  /** Static delivery fact only — never a live capability probe. */
  deliveryState?: HermesDeliveryState;
  children: React.ReactNode;
};

/**
 * F1 Hermes workbench chrome: internal nav, capability notice, single scroll
 * region, and a permanently disabled composer. No mutations or live probes.
 */
export function HermesWorkbenchShell({
  locale,
  deliveryState = "blocked_in_this_slice",
  children,
}: HermesWorkbenchShellProps) {
  const copy = hermesWorkbenchCopy(locale);

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-[var(--color-hermes-canvas)]">
      <HermesInternalNav locale={locale} />

      <div
        className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto"
        data-page-scroll-region
      >
        <div className="mx-auto flex w-full max-w-[var(--spacing-hermes-content-max)] flex-col gap-4 p-4 lg:p-6">
          <HermesCapabilityNotice deliveryState={deliveryState} locale={locale} />
          {children}
        </div>
      </div>

      <div className="min-h-[var(--spacing-hermes-composer-min)] shrink-0">
        <ComposerDock
          allowSubmit={false}
          disabled
          label={copy.composer.label}
          placeholder={copy.composer.placeholder}
          sendLabel={copy.composer.sendDisabled}
          unavailableHint={copy.composer.unavailable}
        />
      </div>
    </div>
  );
}
