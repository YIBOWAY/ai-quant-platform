'use client';

import { useCallback, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";

import { copyTextToClipboard } from "@/lib/hermes/transcriptHelpers";
import {
  COLLAPSE_TOGGLE_CLASS,
  displayId,
} from "@/lib/hermes/workbenchA11y";
import type { HermesSessionMessage } from "@/lib/hermes/workspaceClient";
import type { AssistantPhase } from "@/lib/hermes/transcriptHelpers";

/**
 * Message meta row (timestamp / fork action): hidden until the row is hovered
 * or anything inside it takes keyboard focus. Always shown on touch devices
 * and under reduced-motion, where hover reveal is not a usable affordance.
 */
const META_REVEAL_CLASS =
  "opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 motion-reduce:opacity-100 motion-reduce:transition-none [@media(hover:none)]:opacity-100";

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
  /** Exact backend-issued message cursor selection; absent on read-only canvases. */
  onSelectForkPoint?: (forkPoint: string) => void;
  selectedForkPoint?: string | null;
  forkSelectionDisabled?: boolean;
  forkActionLabel?: string;
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
  onSelectForkPoint,
  selectedForkPoint = null,
  forkSelectionDisabled = false,
  forkActionLabel = isZh ? "从这里继续" : "Continue from here",
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
      <ol
        className="mx-auto w-full max-w-[var(--spacing-chat-max)] space-y-5"
        data-hermes-session-messages
      >
        {messages.map((message, index) => {
          const isUser = message.role === "user";
          const isPending = message.id === pendingMessageId;
          const forkPoint =
            typeof message.fork_point === "string" &&
            /^message:[1-9][0-9]*$/.test(message.fork_point)
              ? message.fork_point
              : null;
          const isForkSelected =
            forkPoint !== null && forkPoint === selectedForkPoint;
          return (
            <li
              className={`group flex gap-2 ${
                isUser ? "justify-end" : "justify-start"
              }`}
              data-hermes-message-fork-selected={
                isForkSelected ? "true" : undefined
              }
              data-hermes-message-pending={isPending ? "true" : undefined}
              key={`${message.id || "msg"}:${index}`}
            >
              {isUser ? null : (
                <span
                  aria-hidden="true"
                  className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-hermes)]/15 text-[var(--color-hermes)]"
                >
                  <Sparkles size={14} />
                </span>
              )}
              <div
                className={
                  isUser
                    ? `relative max-w-[72%] rounded-[var(--radius-bubble)] rounded-br-md border-none bg-info/12 px-4 py-3 ${
                        isForkSelected ? "ring-2 ring-info/40" : ""
                      } ${isPending ? "opacity-70" : ""}`
                    : `min-w-0 flex-1 ${
                        isForkSelected
                          ? "rounded-[var(--radius-bubble)] px-3 py-2 ring-2 ring-info/40"
                          : ""
                      }`
                }
              >
                <span className="sr-only">
                  {isUser ? (isZh ? "你" : "You") : "Hermes"}
                </span>
                <p className="whitespace-pre-wrap break-words font-body-md text-text-primary">
                  {message.content}
                </p>
                {isUser && isPending ? (
                  <span className="absolute bottom-1 right-2 text-text-secondary">
                    <Loader2
                      aria-hidden="true"
                      className="animate-spin motion-reduce:animate-none"
                      size={11}
                    />
                    <span className="sr-only">
                      {isZh ? "发送中" : "Sending"}
                    </span>
                  </span>
                ) : null}
                <div className={`flex items-center gap-2 ${META_REVEAL_CLASS}`}>
                  {message.timestamp ? (
                    <p className="mt-1 font-data-mono text-[11px] text-text-secondary">
                      {message.timestamp}
                    </p>
                  ) : null}
                  {forkPoint && onSelectForkPoint ? (
                    <button
                      aria-label={`${forkActionLabel}: ${message.role}${
                        message.timestamp ? ` · ${message.timestamp}` : ""
                      }`}
                      aria-pressed={isForkSelected}
                      className="app-touch-target mt-1 inline-flex min-h-11 items-center justify-center rounded-lg border border-info/40 bg-info/5 px-3 font-body-sm text-info transition-colors hover:bg-info/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
                      data-hermes-fork-point={forkPoint}
                      data-hermes-message-fork-select
                      disabled={forkSelectionDisabled}
                      onClick={() => onSelectForkPoint(forkPoint)}
                      type="button"
                    >
                      {forkActionLabel}
                    </button>
                  ) : null}
                </div>
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
      className="flex min-w-0 flex-wrap items-center justify-center gap-2 font-data-mono text-[11px] text-text-secondary opacity-70"
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
