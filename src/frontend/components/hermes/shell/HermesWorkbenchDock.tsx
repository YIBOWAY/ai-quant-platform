"use client";

import { usePathname } from "next/navigation";
import { ComposerDock } from "@/components/hermes/ComposerDock";
import { ComposerSubmitController } from "@/components/hermes/ComposerSubmitController";
import { HermesCapabilityNotice } from "@/components/hermes/shell/HermesCapabilityNotice";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { workbenchContentPadClass } from "@/lib/hermes/workbenchA11y";
import type { HermesDeliveryState } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";
import { splitLocalePath } from "@/lib/locale";

function WorkbenchComposer({
  chatOpen,
  locale,
  sessionReadReady,
}: {
  chatOpen: boolean;
  locale: Locale;
  sessionReadReady: boolean;
}) {
  const copy = hermesWorkbenchCopy(locale);
  const isZh = locale === "zh";
  if (!chatOpen) {
    return (
      <ComposerDock
        allowSubmit={false}
        disabled
        label={copy.composer.label}
        locale={locale}
        placeholder={sessionReadReady ? (isZh ? "当前只读，暂不能发送新消息" : "Read-only; new messages cannot be sent") : copy.composer.placeholder}
        sendLabel={copy.composer.sendDisabled}
        unavailableHint={copy.composer.unavailable}
      />
    );
  }
  return (
    <ComposerSubmitController
      allowSubmit
      disabled={false}
      emptySessionText={
        isZh
          ? "直接发送即可。第一条消息会自动开对话。"
          : "Just send. The first message opens the conversation."
      }
      label={copy.composer.label}
      locale={locale}
      networkSubmit
      newSessionCreatingText={
        isZh
          ? "正在创建新的受管 Web 对话…"
          : "Creating a new managed Web conversation…"
      }
      newSessionLabel={isZh ? "新建空白对话" : "New blank conversation"}
      newSessionReadyText={
        isZh ? "新的受管 Web 对话已就绪。" : "New managed Web conversation ready."
      }
      placeholder={copy.composer.placeholderOpen}
      readOnlySessionText={
        isZh
          ? "当前会话仅供阅读。请查看会话详情中可用的继续方式，或点击“新建空白对话”开始独立讨论。"
          : "This session is read-only. Check its details for supported continuation options, or select “New blank conversation” to start independently."
      }
      retryLabel={copy.composer.retrySame}
      sendLabel={copy.composer.sendEnabled}
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
      unavailableHint={copy.composer.unavailable}
    />
  );
}

/**
 * Page-bottom composer for inner Hermes routes.
 * /hermes today already owns the only input in the right rail.
 */
export function HermesWorkbenchDock({
  chatOpen,
  locale,
  deliveryState,
  sessionReadReady = false,
}: {
  chatOpen: boolean;
  locale: Locale;
  deliveryState: HermesDeliveryState;
  sessionReadReady?: boolean;
}) {
  const onToday = splitLocalePath(usePathname()).pathname === "/hermes";
  if (onToday) return null;
  return (
    <>
      <div className={`shrink-0 ${workbenchContentPadClass(false)}`}>
        <HermesCapabilityNotice deliveryState={deliveryState} locale={locale} readState={sessionReadReady ? "available" : "unavailable"} />
      </div>
      <div className="min-h-[var(--spacing-hermes-composer-min)] shrink-0">
        <WorkbenchComposer chatOpen={chatOpen} locale={locale} sessionReadReady={sessionReadReady} />
      </div>
    </>
  );
}
