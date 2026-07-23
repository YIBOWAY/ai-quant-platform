'use client';

import { useCallback, useState } from "react";

import { copyTextToClipboard } from "@/lib/hermes/transcriptHelpers";
import {
  COLLAPSE_TOGGLE_CLASS,
  displayId,
} from "@/lib/hermes/workbenchA11y";
import type { HermesSessionMessage } from "@/lib/hermes/workspaceClient";
import type { AssistantPhase } from "@/lib/hermes/transcriptHelpers";

export type TranscriptCanvasProps = {
  messages: HermesSessionMessage[];
  /** zh labels when true. */
  isZh?: boolean;
  omittedCount?: number;
  emptyHint?: string;
  className?: string;
  /** Optional session id shown as copyable chip for operator clarity. */
  hermesSessionId?: string | null;
  /** Local optimistic user bubble id marker (styling only). */
  pendingMessageId?: string;
  /** Plan-V6-M1 honest phase (no fake tokens). */
  assistantPhase?: AssistantPhase;
  /** Always spine-refetch for M1 (not provider-token). */
  transport?: "spine-refetch" | string;
};

/**
 * Presentational user/assistant bubble list.
 * Shared by workbench Conversation and `/hermes/sessions/[id]` detail.
 */
export function TranscriptCanvas({
  messages,
  isZh = false,
  omittedCount = 0,
  emptyHint,
  className = "",
  hermesSessionId = null,
  pendingMessageId = "local-pending-user",
  assistantPhase = "idle",
  transport = "spine-refetch",

}: TranscriptCanvasProps) {
  const [copyState, setCopyState] = useState<"idle" | "ok" | "fail">("idle");

  const onCopySession = useCallback(async () => {
    if (!hermesSessionId) return;
    const ok = await copyTextToClipboard(hermesSessionId);
    setCopyState(ok ? "ok" : "fail");
    window.setTimeout(() => setCopyState("idle"), 1500);
  }, [hermesSessionId]);

  const resolvedEmpty =
    emptyHint ??
    (isZh
      ? "此会话还没有可展示的用户/助手消息。"
      : "No displayable user/assistant messages yet.");

  if (!messages.length) {
    return (
      <div
        className={`rounded-lg border border-border-subtle bg-bg-surface px-3 py-4 ${className}`}
        data-hermes-session-empty
        data-hermes-transcript-empty
        data-hermes-token-stream="v6-m1"
        data-hermes-assistant-phase={assistantPhase}
        data-hermes-transcript-transport={transport}
      >
        <p className="font-body-sm text-text-secondary">{resolvedEmpty}</p>
        {hermesSessionId ? (
          <SessionChip
            copyState={copyState}
            hermesSessionId={hermesSessionId}
            isZh={isZh}
            onCopy={onCopySession}
          />
        ) : null}
      </div>
    );
  }

  return (
    <div
      aria-live="polite"
      aria-relevant="additions"
      className={`space-y-3 ${className}`}
      data-hermes-transcript-canvas
      data-hermes-token-stream="v6-m1"
      data-hermes-assistant-phase={assistantPhase}
      data-hermes-transcript-transport={transport}
    >
      {hermesSessionId ? (
        <SessionChip
          copyState={copyState}
          hermesSessionId={hermesSessionId}
          isZh={isZh}
          onCopy={onCopySession}
        />
      ) : null}
      <ol className="space-y-3" data-hermes-session-messages>
        {messages.map((message, index) => {
          const isUser = message.role === "user";
          const isPending = message.id === pendingMessageId;
          return (
            <li
              className={`flex ${isUser ? "justify-end" : "justify-start"}`}
              data-hermes-message-pending={isPending ? "true" : undefined}
              key={`${message.id || "msg"}:${index}`}
            >
              <div
                className={`max-w-[88%] rounded-lg border px-3 py-2 shadow-sm ${
                  isUser
                    ? isPending
                      ? "border-info/20 bg-info/5 opacity-90"
                      : "border-info/30 bg-info/10"
                    : "border-border-subtle bg-bg-surface"
                }`}
              >
                <p className="font-label-caps text-text-secondary">
                  {isUser
                    ? isPending
                      ? isZh
                        ? "你 · 发送中"
                        : "You · sending"
                      : isZh
                        ? "你"
                        : "You"
                    : "Hermes"}
                </p>
                <p className="mt-2 whitespace-pre-wrap break-words font-body-sm text-text-primary">
                  {message.content}
                </p>
                {message.timestamp ? (
                  <p className="mt-2 font-data-mono text-[11px] text-text-secondary">
                    {message.timestamp}
                  </p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
      {(assistantPhase === "waiting" || assistantPhase === "partial") && (
        <p
          className="mt-2 font-body-sm text-text-secondary"
          data-hermes-assistant-streaming-note
          data-hermes-assistant-phase={assistantPhase}
        >
          {assistantPhase === "waiting"
            ? isZh
              ? "等待助手回复（spine 驱动刷新；非 provider token 直通）"
              : "Waiting for assistant (spine-refetch; not provider-token passthrough)"
            : isZh
              ? "助手正文增长中（messages BFF 权威；follow 无 body）"
              : "Assistant text growing (messages BFF authority; no body on follow)"}
        </p>
      )}

      {omittedCount > 0 ? (
        <p
          className="font-body-sm text-text-secondary"
          data-hermes-omitted-message-count
        >
          {isZh
            ? `为保护敏感工具内容和控制响应大小，省略了 ${omittedCount} 条系统、工具或较早消息。`
            : `${omittedCount} system, tool, or older messages were omitted for safety and response bounds.`}
        </p>
      ) : null}
    </div>
  );
}

function SessionChip({
  hermesSessionId,
  isZh,
  copyState,
  onCopy,
}: {
  hermesSessionId: string;
  isZh: boolean;
  copyState: "idle" | "ok" | "fail";
  onCopy: () => void;
}) {
  const label =
    copyState === "ok"
      ? isZh
        ? "已复制"
        : "Copied"
      : copyState === "fail"
        ? isZh
          ? "复制失败"
          : "Copy failed"
        : isZh
          ? "复制"
          : "Copy";
  return (
    <div
      className="flex min-w-0 flex-wrap items-center gap-2 font-data-mono text-[11px] text-text-secondary"
      data-hermes-transcript-session-chip
    >
      <span
        className="min-w-0 max-w-full break-all"
        data-hermes-transcript-session-id
        title={hermesSessionId}
      >
        {displayId(hermesSessionId, { head: 20, tail: 8, max: 36 })}
      </span>
      <button
        className={COLLAPSE_TOGGLE_CLASS}
        data-hermes-transcript-copy-session
        onClick={onCopy}
        type="button"
      >
        {label}
      </button>
    </div>
  );
}
