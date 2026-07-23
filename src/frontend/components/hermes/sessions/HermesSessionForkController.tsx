'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { TranscriptCanvas } from "@/components/hermes/transcript/TranscriptCanvas";
import { Card } from "@/components/ui/primitives";
import { useOptionalActiveHermesSession } from "@/lib/hermes/activeSession";
import {
  ensureSessionForkAttempt,
  type SessionForkAttempt,
} from "@/lib/hermes/sessionForkAttempt";
import { activateReadyHermesFork } from "@/lib/hermes/sessionForkNavigation";
import {
  forkHermesSessionToManaged,
  WorkspaceClientError,
  type HermesSessionMessage,
  type WorkspaceActionReceipt,
} from "@/lib/hermes/workspaceClient";
import type { Locale } from "@/lib/locale";

export type HermesSessionForkControllerProps = {
  hermesSessionId: string;
  messages: HermesSessionMessage[];
  forkEligible: boolean;
  forkReasonCode?: string | null;
  locale?: Locale;
  isZh?: boolean;
  omittedCount?: number;
  emptyHint?: string;
};

type ForkPhase =
  | "idle"
  | "confirming"
  | "authorizing"
  | "accepted"
  | "reconciling"
  | "error";

const ACTION_CLASS =
  "app-touch-target inline-flex min-h-11 items-center justify-center rounded-lg border px-3 font-body-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none";

function forkErrorCopy(error: unknown, isZh: boolean): string {
  const code =
    error instanceof WorkspaceClientError ? error.code ?? "" : "";
  const known: Record<string, [string, string]> = {
    owner_bootstrap_required: [
      "需要本机所有者授权。请生成一次性 bootstrap token 后重试同一次操作。",
      "Local owner authorization is required. Generate a one-time bootstrap token, then retry this same attempt.",
    ],
    auth: [
      "所有者会话或 CSRF 凭证不可用。请重新完成本机所有者授权后重试同一次操作。",
      "The owner session or CSRF credential is unavailable. Re-authorize the local owner, then retry this same attempt.",
    ],
    agent_v02_release_not_ready: [
      "Agent v0.2 写入发布门仍关闭。此源会话未被修改。",
      "The Agent v0.2 write release gate is still closed. The source session was not changed.",
    ],
    fork_point_not_authoritative: [
      "该消息游标已不再是 Hermes 权威记录。请重新加载并重新选择，系统不会替换为其他消息。",
      "This cursor is no longer authoritative in Hermes. Reload and reselect; no other message will be substituted.",
    ],
    source_session_not_external: [
      "此会话不是可创建分支的外部只读会话。",
      "This is not an eligible external read-only session.",
    ],
    source_session_registry_unavailable: [
      "源会话注册表暂时不可用。源会话未被修改，可重试同一次操作。",
      "The source-session registry is unavailable. The source session was not changed; retry the same attempt.",
    ],
    managed_session_provision_retryable: [
      "新会话暂时未就绪。可使用完全相同的操作重试。",
      "The new session is temporarily not ready. Retry the exact same attempt.",
    ],
    managed_session_provision_timeout: [
      "等待新会话就绪超时。可使用完全相同的操作继续恢复。",
      "Waiting for the new session timed out. Retry the exact same attempt to recover it.",
    ],
    managed_session_not_observed: [
      "尚未观察到新会话。可使用完全相同的操作继续恢复。",
      "The new session has not been observed yet. Retry the exact same attempt to recover it.",
    ],
    conflict: [
      "该操作与既有幂等记录冲突。源会话未被修改，请重新选择后创建新操作。",
      "This attempt conflicts with an existing idempotency record. The source session was not changed; reselect to create a new attempt.",
    ],
  };
  const translated = known[code];
  if (translated) return isZh ? translated[0] : translated[1];
  if (isZh) {
    return `无法创建新会话${code ? `（${code}）` : ""}。源会话未被修改，可重试同一次操作。`;
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return "Unable to create the new session. The source session was not changed; you may retry the same attempt.";
}

function statusCopy(
  phase: ForkPhase,
  isZh: boolean,
  receipt?: WorkspaceActionReceipt | null,
): string | null {
  if (phase === "authorizing") {
    return isZh
      ? "正在验证所有者权限并提交不可变分支…"
      : "Authorizing owner and submitting the immutable fork…";
  }
  if (phase === "accepted") {
    return isZh
      ? "分支已接受，正在等待新 Web 会话就绪…"
      : "Fork accepted; waiting for the new Web session to become ready…";
  }
  if (phase === "reconciling") {
    return isZh
      ? "分支正在对账，继续等待同一个新会话…"
      : "Fork is reconciling; continuing to wait for the same new session…";
  }
  if (receipt?.status) return receipt.status;
  return null;
}

export function HermesSessionForkController({
  hermesSessionId,
  messages,
  forkEligible,
  forkReasonCode = null,
  locale = "en",
  isZh = locale === "zh",
  omittedCount = 0,
  emptyHint,
}: HermesSessionForkControllerProps) {
  const router = useRouter();
  const activeSession = useOptionalActiveHermesSession();
  const [selectedForkPoint, setSelectedForkPoint] = useState<string | null>(
    null,
  );
  const [attempt, setAttempt] = useState<SessionForkAttempt | null>(null);
  const [phase, setPhase] = useState<ForkPhase>("idle");
  const [lastReceipt, setLastReceipt] =
    useState<WorkspaceActionReceipt | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const busy =
    phase === "authorizing" ||
    phase === "accepted" ||
    phase === "reconciling";

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, []);

  const selectedMessage = useMemo(
    () =>
      selectedForkPoint
        ? messages.find(
            (message) => message.fork_point === selectedForkPoint,
          ) ?? null
        : null,
    [messages, selectedForkPoint],
  );
  const forkableCount = messages.filter(
    (message) =>
      typeof message.fork_point === "string" &&
      /^message:[1-9][0-9]*$/.test(message.fork_point),
  ).length;

  const selectForkPoint = useCallback(
    (forkPoint: string) => {
      if (busy || !forkEligible) return;
      setSelectedForkPoint((prior) => {
        if (prior !== forkPoint) {
          setAttempt(null);
        }
        return forkPoint;
      });
      setLastReceipt(null);
      setErrorText(null);
      setPhase("confirming");
    },
    [busy, forkEligible],
  );

  const runAttempt = useCallback(
    async (nextAttempt: SessionForkAttempt) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setErrorText(null);
      setPhase("authorizing");
      try {
        const result = await forkHermesSessionToManaged({
          hermesSessionId: nextAttempt.hermesSessionId,
          clientActionId: nextAttempt.clientActionId,
          forkPoint: nextAttempt.forkPoint,
          signal: controller.signal,
          onReceipt: (receipt) => {
            setLastReceipt(receipt);
            setPhase(
              receipt.status === "reconciling" ? "reconciling" : "accepted",
            );
          },
        });
        if (controller.signal.aborted) return;
        activateReadyHermesFork({
          hermesSessionId: result.managedSession.hermes_session_id,
          locale,
          bindHermesSession: (childId) => {
            activeSession?.setActiveHermesSession({
              hermesSessionId: childId,
            });
          },
          navigate: (href) => router.push(href),
        });
      } catch (error) {
        if (controller.signal.aborted) return;
        setErrorText(forkErrorCopy(error, isZh));
        setPhase("error");
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      }
    },
    [activeSession, isZh, locale, router],
  );

  const confirm = useCallback(() => {
    if (!selectedForkPoint || busy) return;
    const nextAttempt = ensureSessionForkAttempt(
      attempt,
      { hermesSessionId, forkPoint: selectedForkPoint },
    );
    setAttempt(nextAttempt);
    void runAttempt(nextAttempt);
  }, [
    attempt,
    busy,
    hermesSessionId,
    runAttempt,
    selectedForkPoint,
  ]);

  const retry = useCallback(() => {
    if (!attempt || busy) return;
    void runAttempt(attempt);
  }, [attempt, busy, runAttempt]);

  const cancelSelection = useCallback(() => {
    if (busy) return;
    setSelectedForkPoint(null);
    setAttempt(null);
    setLastReceipt(null);
    setErrorText(null);
    setPhase("idle");
  }, [busy]);

  const status = statusCopy(phase, isZh, lastReceipt);

  return (
    <section
      aria-label={isZh ? "从消息创建 Web 会话" : "Create Web session from message"}
      className="space-y-3"
      data-hermes-session-fork-controller
      data-hermes-session-fork-eligible={forkEligible ? "true" : "false"}
    >
      <TranscriptCanvas
        emptyHint={emptyHint}
        forkActionLabel={isZh ? "从这里继续" : "Continue from here"}
        forkSelectionDisabled={busy}
        hermesSessionId={hermesSessionId}
        isZh={isZh}
        messages={messages}
        omittedCount={omittedCount}
        onSelectForkPoint={forkEligible ? selectForkPoint : undefined}
        selectedForkPoint={selectedForkPoint}
      />

      {!forkEligible ? (
        <Card data-hermes-session-fork-ineligible tone="neutral">
          <p className="font-body-sm font-semibold text-text-primary">
            {isZh
              ? "此会话不能创建分支"
              : "This session cannot be forked"}
          </p>
          <p className="mt-1 font-body-sm text-text-secondary">
            {isZh
              ? "只有后端明确标记为 eligible 的外部只读会话才可继续到新的 Web 会话。"
              : "Only external read-only sessions explicitly marked eligible by the server can continue into a new Web session."}
          </p>
          {forkReasonCode ? (
            <p className="mt-2 font-data-mono text-xs text-text-secondary">
              {forkReasonCode}
            </p>
          ) : null}
        </Card>
      ) : forkableCount === 0 ? (
        <Card data-hermes-session-fork-no-cursor tone="neutral">
          <p className="font-body-sm text-text-secondary">
            {isZh
              ? "此会话没有带权威正整数游标的可选消息。系统不会猜测或替换分支点。"
              : "No message has an authoritative positive-integer cursor. The fork point will not be guessed or substituted."}
          </p>
        </Card>
      ) : null}

      {selectedMessage ? (
        <Card
          aria-labelledby="hermes-session-fork-confirm-title"
          data-hermes-session-fork-confirm
          tone="info"
        >
          <h2
            className="font-body-sm font-semibold text-text-primary"
            id="hermes-session-fork-confirm-title"
          >
            {isZh ? "确认从这条消息继续？" : "Continue from this exact message?"}
          </h2>
          <dl className="mt-3 grid gap-2 font-data-mono text-xs sm:grid-cols-3">
            <div>
              <dt className="text-text-secondary">{isZh ? "角色" : "Role"}</dt>
              <dd className="mt-1 text-text-primary">
                {selectedMessage.role === "user"
                  ? isZh
                    ? "你"
                    : "You"
                  : "Hermes"}
              </dd>
            </div>
            <div>
              <dt className="text-text-secondary">
                {isZh ? "消息游标" : "Message cursor"}
              </dt>
              <dd className="mt-1 break-all text-text-primary">
                {selectedForkPoint}
              </dd>
            </div>
            <div>
              <dt className="text-text-secondary">{isZh ? "时间" : "Time"}</dt>
              <dd className="mt-1 break-all text-text-primary">
                {selectedMessage.timestamp || "—"}
              </dd>
            </div>
          </dl>
          <p className="mt-3 line-clamp-3 whitespace-pre-wrap break-words font-body-sm text-text-secondary">
            {selectedMessage.content}
          </p>
          <p className="mt-3 font-body-sm text-text-secondary">
            {isZh
              ? "将创建一个新的、由服务器管理的 Web 会话；此源会话与所选分支点保持不变。"
              : "A new server-managed Web session will be created. This source session and the selected fork point remain unchanged."}
          </p>

          <div className="mt-4 flex flex-wrap gap-2">
            {phase === "error" && attempt ? (
              <button
                className={`${ACTION_CLASS} border-info/40 bg-info/10 text-info hover:bg-info/15`}
                data-hermes-session-fork-retry
                disabled={busy}
                onClick={retry}
                type="button"
              >
                {isZh ? "重试同一次操作" : "Retry same attempt"}
              </button>
            ) : (
              <button
                className={`${ACTION_CLASS} border-info/40 bg-info/10 text-info hover:bg-info/15`}
                data-hermes-session-fork-confirm-action
                disabled={busy}
                onClick={confirm}
                type="button"
              >
                {busy
                  ? isZh
                    ? "正在创建…"
                    : "Creating…"
                  : isZh
                    ? "确认并创建新会话"
                    : "Confirm and create new session"}
              </button>
            )}
            <button
              className={`${ACTION_CLASS} border-border-subtle bg-bg-surface text-text-secondary hover:bg-bg-surface-muted`}
              disabled={busy}
              onClick={cancelSelection}
              type="button"
            >
              {isZh ? "取消" : "Cancel"}
            </button>
          </div>

          {status ? (
            <p
              className="mt-3 font-body-sm text-text-secondary"
              data-hermes-session-fork-status
              role="status"
            >
              {status}
            </p>
          ) : null}
          {errorText ? (
            <p
              className="mt-3 font-body-sm text-danger"
              data-hermes-session-fork-error
              role="alert"
            >
              {errorText}
            </p>
          ) : null}
          {attempt ? (
            <p className="mt-2 break-all font-data-mono text-[11px] text-text-secondary">
              {isZh ? "操作 ID" : "Attempt ID"}: {attempt.clientActionId}
            </p>
          ) : null}
        </Card>
      ) : null}
    </section>
  );
}
