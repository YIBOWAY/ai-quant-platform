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
                  emptySessionText={
                    isZh
                      ? "发送前请先点击“新建空白对话”，建立一个可恢复的受管 Web 会话。"
                      : "Select “New blank conversation” before sending so the Web session has a recoverable identity."
                  }
                  label={composer.label}
                  locale={locale}
                  networkSubmit
                  newSessionCreatingText={
                    isZh
                      ? "正在创建新的受管 Web 对话…"
                      : "Creating a new managed Web conversation…"
                  }
                  newSessionLabel={
                    isZh ? "新建空白对话" : "New blank conversation"
                  }
                  newSessionReadyText={
                    isZh
                      ? "新的受管 Web 对话已就绪。"
                      : "New managed Web conversation ready."
                  }
                  placeholder={composer.placeholderOpen}
                  readOnlySessionText={
                    isZh
                      ? "当前会话仅供阅读。要继承上下文，请在“会话记录”中从具体消息创建分支；要开始独立会话，请点击“新建空白对话”。"
                      : "This session is read-only. To preserve its context, fork from a specific message in Sessions; to start independently, select “New blank conversation”."
                  }
                  sendLabel={composer.sendEnabled}
                  sessionCheckingText={
                    isZh
                      ? "正在核验当前会话是否允许发送…"
                      : "Checking whether this session can accept messages…"
                  }
                  sessionValidationUnavailableText={
                    isZh
                      ? "无法核验当前会话的写入权限，发送保持锁定。你可以新建空白对话，或检查本机后端健康状态。"
                      : "Session write access could not be verified, so sending remains locked. Start a blank conversation or check local backend health."
                  }
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
