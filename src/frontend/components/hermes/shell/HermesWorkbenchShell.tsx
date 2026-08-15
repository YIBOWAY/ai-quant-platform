import { HermesLocalChatBoundary } from "@/components/hermes/shell/HermesLocalChatBoundary";
import { ComposerDock } from "@/components/hermes/ComposerDock";
import { HermesCapabilityNotice } from "@/components/hermes/shell/HermesCapabilityNotice";
import { HermesDeskFrame } from "@/components/hermes/desk/HermesDeskFrame";
import { HermesDeskProvider } from "@/components/hermes/desk/HermesDeskContext";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import {
  hermesChatAdmission,
  hermesFeatureFlags,
} from "@/lib/hermes/featureFlags";
import {
  WORKBENCH_A11Y_MARKER,
  workbenchContentPadClass,
} from "@/lib/hermes/workbenchA11y";
import type { HermesDeliveryState } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";

export type HermesWorkbenchShellProps = {
  locale: Locale;
  /** User-facing admission state resolved from operator policy and backend readiness. */
  deliveryState?: HermesDeliveryState;
  /** Live backend release admission. The env flag remains deny-only. */
  chatWriteReady?: boolean;
  children: React.ReactNode;
};

/**
 * Hermes workbench is the official desk: blotter + remote + existing
 * session/result routes. Public composer stays gated.
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
    <HermesDeskProvider>
      <div
        className="h-full min-h-0 w-full overflow-hidden bg-[var(--color-hermes-canvas)]"
        data-hermes-workbench-a11y={WORKBENCH_A11Y_MARKER}
      >
        <HermesDeskFrame>
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
            <HermesDeskClosedRegion locale={locale} deliveryState={resolvedDelivery}>
              {children}
            </HermesDeskClosedRegion>
          )}
        </HermesDeskFrame>
      </div>
    </HermesDeskProvider>
  );
}

function HermesDeskClosedRegion({
  locale,
  deliveryState,
  children,
}: {
  locale: Locale;
  deliveryState: HermesDeliveryState;
  children: React.ReactNode;
}) {
  return (
    <>
      <div
        aria-label={locale === "zh" ? "Hermes 工作台主区" : "Hermes workbench main"}
        className="contents"
        data-hermes-workbench-main
        role="region"
      >
        {children}
      </div>
      <div className="sr-only">
        <div className={workbenchContentPadClass(false)}>
          <HermesCapabilityNotice deliveryState={deliveryState} locale={locale} />
        </div>
        <ComposerDock
          allowSubmit={false}
          disabled
          label={hermesWorkbenchCopy(locale).composer.label}
          placeholder={hermesWorkbenchCopy(locale).composer.placeholder}
          sendLabel={hermesWorkbenchCopy(locale).composer.sendDisabled}
          unavailableHint={hermesWorkbenchCopy(locale).composer.unavailable}
        />
      </div>
    </>
  );
}
