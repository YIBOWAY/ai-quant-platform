'use client';

import type { ReactNode } from "react";

import { WorkbenchCommandActivityPanel } from "@/components/hermes/activity/WorkbenchCommandActivityPanel";
import { WorkbenchCommandApprovalsPanel } from "@/components/hermes/approvals/WorkbenchCommandApprovalsPanel";
import { ComposerSubmitController } from "@/components/hermes/ComposerSubmitController";
import { HermesCapabilityNotice } from "@/components/hermes/shell/HermesCapabilityNotice";
import { WorkbenchTranscriptPanel } from "@/components/hermes/transcript/WorkbenchTranscriptPanel";
import { ActiveHermesSessionProvider } from "@/lib/hermes/activeSession";
import { WorkspaceFollowProvider } from "@/lib/hermes/workspaceFollowContext";
import type { HermesDeliveryState } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";

export type HermesLocalChatBoundaryProps = {
  locale: Locale;
  deliveryState: HermesDeliveryState;
  children: ReactNode;
  composer: {
    label: string;
    placeholder: string;
    placeholderOpen: string;
    sendEnabled: string;
    sendDisabled: string;
    unavailable: string;
  };
  /** When false, composer stays locked (should not use this boundary). */
  chatOpen: boolean;
};

/**
 * Client island: active Hermes session + shared L4b follow spine + transcript
 * + command activity + composer. Keeps server shell free of cookie/fetch.
 */
export function HermesLocalChatBoundary({
  locale,
  deliveryState,
  children,
  composer,
  chatOpen,
}: HermesLocalChatBoundaryProps) {
  return (
    <ActiveHermesSessionProvider>
      <WorkspaceFollowProvider enabled={chatOpen}>
        <div
          className="flex h-full min-h-0 w-full flex-1 flex-col overflow-hidden"
          data-hermes-workspace-follow="l4b-m1"
        >
          <div
            className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto [overflow-anchor:none]"
            data-page-scroll-region
          >
            <div className="mx-auto flex w-full max-w-[var(--spacing-hermes-content-max)] flex-col gap-4 p-4 lg:p-6">
              <HermesCapabilityNotice
                deliveryState={deliveryState}
                locale={locale}
              />
              {chatOpen ? <WorkbenchTranscriptPanel locale={locale} /> : null}
              {chatOpen ? (
                <WorkbenchCommandActivityPanel locale={locale} />
              ) : null}
              {chatOpen ? (
                <WorkbenchCommandApprovalsPanel locale={locale} />
              ) : null}
              {children}
            </div>
          </div>
          <div className="min-h-[var(--spacing-hermes-composer-min)] shrink-0">
            <ComposerSubmitController
              allowSubmit={chatOpen}
              disabled={!chatOpen}
              label={composer.label}
              networkSubmit={chatOpen}
              placeholder={
                chatOpen ? composer.placeholderOpen : composer.placeholder
              }
              sendLabel={chatOpen ? composer.sendEnabled : composer.sendDisabled}
              unavailableHint={composer.unavailable}
            />
          </div>
        </div>
      </WorkspaceFollowProvider>
    </ActiveHermesSessionProvider>
  );
}
