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
  deliveryState?: HermesDeliveryState;
  chatWriteReady?: boolean;
  children: React.ReactNode;
};

/**
 * Official Hermes desk. The blotter + remote rail are the workbench.
 * Do not wrap today in LocalChatBoundary: that extra box breaks the desk grid.
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

  return (
    <HermesDeskProvider>
      <div
        className="h-full min-h-0 w-full overflow-hidden bg-[var(--color-hermes-canvas)]"
        data-hermes-workbench-a11y={WORKBENCH_A11Y_MARKER}
      >
        <HermesDeskFrame>
          <div
            aria-label={
              locale === "zh" ? "Hermes 工作台主区" : "Hermes workbench main"
            }
            className="contents"
            data-hermes-workbench-main
            role="region"
          >
            {children}
          </div>
        </HermesDeskFrame>
        <div className="sr-only">
          <div className={workbenchContentPadClass(false)}>
            <HermesCapabilityNotice
              deliveryState={resolvedDelivery}
              locale={locale}
            />
          </div>
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
    </HermesDeskProvider>
  );
}
