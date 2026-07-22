import { HermesInternalNav } from "@/components/hermes/shell/HermesInternalNav";
import { HermesLocalChatBoundary } from "@/components/hermes/shell/HermesLocalChatBoundary";
import { ComposerDock } from "@/components/hermes/ComposerDock";
import { HermesCapabilityNotice } from "@/components/hermes/shell/HermesCapabilityNotice";
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
 * F1 Hermes workbench chrome: internal nav + scroll region + composer.
 * Local chat open → L3a client boundary (active session + transcript + submit).
 * Chat closed → server-only locked composer (no cookie/fetch island).
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

      {composerOpen ? (
        <HermesLocalChatBoundary
          chatOpen
          composer={{
            label: copy.composer.label,
            placeholder: copy.composer.placeholder,
            placeholderOpen: copy.composer.placeholderOpen,
            sendEnabled: copy.composer.sendEnabled,
            sendDisabled: copy.composer.sendDisabled,
            unavailable: copy.composer.unavailable,
          }}
          deliveryState={resolvedDelivery}
          locale={locale}
        >
          {children}
        </HermesLocalChatBoundary>
      ) : (
        <>
          <div
            className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto [overflow-anchor:none]"
            data-page-scroll-region
          >
            <div className="mx-auto flex w-full max-w-[var(--spacing-hermes-content-max)] flex-col gap-4 p-4 lg:p-6">
              <HermesCapabilityNotice
                deliveryState={resolvedDelivery}
                locale={locale}
              />
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
        </>
      )}
    </div>
  );
}
