import { HermesInternalNav } from "@/components/hermes/shell/HermesInternalNav";
import { HermesLocalChatBoundary } from "@/components/hermes/shell/HermesLocalChatBoundary";
import { ComposerDock } from "@/components/hermes/ComposerDock";
import { HermesCapabilityNotice } from "@/components/hermes/shell/HermesCapabilityNotice";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import {
  hermesChatAdmission,
  hermesFeatureFlags,
} from "@/lib/hermes/featureFlags";
import {
  WORKBENCH_A11Y_MARKER,
  WORKBENCH_CONTENT_PAD_CLASS,
} from "@/lib/hermes/workbenchA11y";
import type { HermesDeliveryState } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";

export type HermesWorkbenchShellProps = {
  locale: Locale;
  /** Static delivery fact only — never a live capability probe. */
  deliveryState?: HermesDeliveryState;
  /** Live backend release admission. The env flag remains deny-only. */
  chatWriteReady?: boolean;
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
  chatWriteReady = false,
  children,
}: HermesWorkbenchShellProps) {
  const copy = hermesWorkbenchCopy(locale);
  const flags = hermesFeatureFlags();
  const admission = hermesChatAdmission(flags, chatWriteReady);
  const resolvedDelivery =
    deliveryState ?? admission.deliveryState ?? "blocked_in_this_slice";
  const composerOpen = admission.chatOpen;

  return (
    <div
      className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-[var(--color-hermes-canvas)]"
      data-hermes-workbench-a11y={WORKBENCH_A11Y_MARKER}
    >
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
            retrySame: copy.composer.retrySame,
            unavailable: copy.composer.unavailable,
          }}
          deliveryState={resolvedDelivery}
          locale={locale}
        >
          {children}
        </HermesLocalChatBoundary>
      ) : (
        <>
          {/* role=region (not nested main element): root layout already owns document main. */}
          <div
            aria-label={
              locale === "zh" ? "Hermes 工作台主区" : "Hermes workbench main"
            }
            className="flex min-h-0 flex-1 flex-col overflow-hidden"
            data-hermes-workbench-main
            role="region"
          >
            <div
              className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto [overflow-anchor:none]"
              data-page-scroll-region
            >
              <div className={WORKBENCH_CONTENT_PAD_CLASS}>
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
          </div>
        </>
      )}
    </div>
  );
}
