'use client';

import { useEffect, useState, type ReactNode } from "react";

import { WorkbenchCommandActivityPanel } from "@/components/hermes/activity/WorkbenchCommandActivityPanel";
import { WorkbenchCommandApprovalsPanel } from "@/components/hermes/approvals/WorkbenchCommandApprovalsPanel";
import { WorkbenchAuthorityProjectionPanel } from "@/components/hermes/authority/WorkbenchAuthorityProjectionPanel";
import { WorkbenchGateSurfacesPanel } from "@/components/hermes/gates/WorkbenchGateSurfacesPanel";
import { WorkbenchTypedResultsPanel } from "@/components/hermes/results/WorkbenchTypedResultsPanel";
import { WorkbenchRunStopPanel } from "@/components/hermes/run-control/WorkbenchRunStopPanel";
import { ComposerSubmitController } from "@/components/hermes/ComposerSubmitController";
import { OwnerSessionBootstrapPanel } from "@/components/hermes/OwnerSessionBootstrapPanel";
import { HermesCapabilityNotice } from "@/components/hermes/shell/HermesCapabilityNotice";
import { WorkbenchTranscriptPanel } from "@/components/hermes/transcript/WorkbenchTranscriptPanel";
import { ActiveHermesSessionProvider } from "@/lib/hermes/activeSession";
import {
  WORKBENCH_A11Y_MARKER,
  WORKBENCH_CONTENT_PAD_CLASS,
} from "@/lib/hermes/workbenchA11y";
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
    retrySame: string;
    unavailable: string;
  };
  /** When false, composer stays locked (should not use this boundary). */
  chatOpen: boolean;
};

/**
 * Client island: active Hermes session + shared L4b follow spine + transcript
 * + command activity + composer. Keeps server shell free of cookie/fetch.
 * L5c: main landmark + responsive content pad + workbench a11y marker.
 */
export function HermesLocalChatBoundary({
  locale,
  deliveryState,
  children,
  composer,
  chatOpen,
}: HermesLocalChatBoundaryProps) {
  const isZh = locale === "zh";
  const [ownerReady, setOwnerReady] = useState(false);
  const [bootstrapCompleted, setBootstrapCompleted] = useState(false);
  const authorizedChatOpen = chatOpen && ownerReady;

  useEffect(() => {
    if (!authorizedChatOpen || !bootstrapCompleted) return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById("hermes-composer-draft")?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [authorizedChatOpen, bootstrapCompleted]);

  return (
    <ActiveHermesSessionProvider>
      <WorkspaceFollowProvider enabled={authorizedChatOpen}>
        <div
          className="flex h-full min-h-0 w-full flex-1 flex-col overflow-hidden"
          data-hermes-workspace-follow="l4b-m1"
          data-hermes-workbench-a11y={WORKBENCH_A11Y_MARKER}
        >
          {/* role=region (not nested main element): root layout already owns document main. */}
          <div
            aria-label={isZh ? "Hermes 工作台主区" : "Hermes workbench main"}
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
                  deliveryState={deliveryState}
                  locale={locale}
                />
                {chatOpen ? (
                  <OwnerSessionBootstrapPanel
                    locale={locale}
                    onBootstrapSuccess={() => setBootstrapCompleted(true)}
                    onReadinessChange={setOwnerReady}
                  />
                ) : null}
                <p aria-live="polite" className="sr-only" role="status">
                  {bootstrapCompleted && authorizedChatOpen
                    ? isZh
                      ? "授权完成，可以开始和 Hermes 对话。"
                      : "Authorization complete. You can now chat with Hermes."
                    : ""}
                </p>
                {authorizedChatOpen ? (
                  <WorkbenchTranscriptPanel locale={locale} />
                ) : null}
                {authorizedChatOpen ? (
                  <WorkbenchCommandActivityPanel locale={locale} />
                ) : null}
                {authorizedChatOpen ? (
                  <WorkbenchRunStopPanel locale={locale} />
                ) : null}
                {authorizedChatOpen ? (
                  <WorkbenchCommandApprovalsPanel locale={locale} />
                ) : null}
                {authorizedChatOpen ? (
                  <WorkbenchGateSurfacesPanel locale={locale} />
                ) : null}
                {authorizedChatOpen ? (
                  <WorkbenchTypedResultsPanel locale={locale} />
                ) : null}
                {authorizedChatOpen ? (
                  <WorkbenchAuthorityProjectionPanel locale={locale} />
                ) : null}
                {children}
              </div>
            </div>
            {authorizedChatOpen ? (
              <div className="min-h-[var(--spacing-hermes-composer-min)] shrink-0">
                <ComposerSubmitController
                  allowSubmit
                  disabled={false}
                  label={composer.label}
                  networkSubmit
                  placeholder={composer.placeholderOpen}
                  sendLabel={composer.sendEnabled}
                  retryLabel={composer.retrySame}
                  unavailableHint={composer.unavailable}
                />
              </div>
            ) : null}
          </div>
        </div>
      </WorkspaceFollowProvider>
    </ActiveHermesSessionProvider>
  );
}
