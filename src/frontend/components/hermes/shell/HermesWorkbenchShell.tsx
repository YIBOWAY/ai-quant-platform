import { ComposerSubmitController } from "@/components/hermes/ComposerSubmitController";
import { HermesCapabilityNotice } from "@/components/hermes/shell/HermesCapabilityNotice";
import { HermesInternalNav } from "@/components/hermes/shell/HermesInternalNav";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { hermesFeatureFlags } from "@/lib/hermes/featureFlags";
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
 * region, and composer. Composer stays disabled unless the local chat flag is on.
 * When chat is unlocked, L2a-Send wires same-origin submit-turn (owner cookie + CSRF).
 */
export function HermesWorkbenchShell({
  locale,
  deliveryState,
  children,
}: HermesWorkbenchShellProps) {
  const copy = hermesWorkbenchCopy(locale);
  const flags = hermesFeatureFlags();
  const resolvedDelivery =
    deliveryState ?? flags.deliveryState ?? "blocked_in_this_slice";
  const composerOpen = flags.chat === true;

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-[var(--color-hermes-canvas)]">
      <HermesInternalNav locale={locale} />

      <div
        className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto [overflow-anchor:none]"
        data-page-scroll-region
      >
        <div className="mx-auto flex w-full max-w-[var(--spacing-hermes-content-max)] flex-col gap-4 p-4 lg:p-6">
          <HermesCapabilityNotice deliveryState={resolvedDelivery} locale={locale} />
          {children}
        </div>
      </div>

      <div className="min-h-[var(--spacing-hermes-composer-min)] shrink-0">
        <ComposerSubmitController
          allowSubmit={composerOpen}
          disabled={!composerOpen}
          label={copy.composer.label}
          networkSubmit={composerOpen}
          placeholder={
            composerOpen
              ? copy.composer.placeholderOpen
              : copy.composer.placeholder
          }
          sendLabel={
            composerOpen ? copy.composer.sendEnabled : copy.composer.sendDisabled
          }
          unavailableHint={copy.composer.unavailable}
        />
      </div>
    </div>
  );
}
