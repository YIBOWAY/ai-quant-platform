import { HermesDeskFrame } from "@/components/hermes/desk/HermesDeskFrame";
import { HermesDeskProvider } from "@/components/hermes/desk/HermesDeskContext";
import { HermesWorkbenchDock } from "@/components/hermes/shell/HermesWorkbenchDock";
import { ActiveHermesSessionProvider } from "@/lib/hermes/activeSession";
import {
  hermesChatAdmission,
  hermesFeatureFlags,
} from "@/lib/hermes/featureFlags";
import { WORKBENCH_A11Y_MARKER } from "@/lib/hermes/workbenchA11y";
import { WorkspaceFollowProvider } from "@/lib/hermes/workspaceFollowContext";
import type { HermesDeliveryState } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";

export type HermesWorkbenchShellProps = {
  locale: Locale;
  deliveryState?: HermesDeliveryState;
  chatWriteReady?: boolean;
  sessionReadReady?: boolean;
  children: React.ReactNode;
};

/**
 * Official Hermes desk. Today hosts the only composer in the right rail.
 * Other Hermes routes keep the page-bottom dock. Do not wrap today in
 * LocalChatBoundary: that extra box breaks the desk grid.
 */
export function HermesWorkbenchShell({
  locale,
  deliveryState,
  chatWriteReady = false,
  sessionReadReady = false,
  children,
}: HermesWorkbenchShellProps) {
  const flags = hermesFeatureFlags();
  const admission = hermesChatAdmission(flags, chatWriteReady);
  const chatOpen = admission.chatOpen;
  // Capability copy follows admission, not a stale parent deliveryState, so
  // “对话已就绪” cannot appear next to a disabled send control.
  const resolvedDelivery = chatOpen
    ? (deliveryState ?? admission.deliveryState)
    : "blocked_in_this_slice";

  return (
    <ActiveHermesSessionProvider>
      <WorkspaceFollowProvider enabled={chatOpen}>
        <HermesDeskProvider
          chatOpen={chatOpen}
          deliveryState={resolvedDelivery}
          locale={locale}
        >
          <div
            className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-[var(--color-hermes-canvas)]"
            data-hermes-workbench-a11y={WORKBENCH_A11Y_MARKER}
          >
            <div className="min-h-0 flex-1 overflow-hidden">
              <HermesDeskFrame>
                <div
                  aria-label={
                    locale === "zh" ? "Hermes 助手主区" : "Hermes Assistant main"
                  }
                  className="contents"
                  data-hermes-workbench-main
                  role="region"
                >
                  {children}
                </div>
              </HermesDeskFrame>
            </div>
            <HermesWorkbenchDock
              chatOpen={chatOpen}
              sessionReadReady={sessionReadReady}
              deliveryState={resolvedDelivery}
              locale={locale}
            />
          </div>
        </HermesDeskProvider>
      </WorkspaceFollowProvider>
    </ActiveHermesSessionProvider>
  );
}
