'use client';

import { useEffect, useMemo, useRef, useState } from "react";

import { TranscriptCanvas } from "@/components/hermes/transcript/TranscriptCanvas";
import { useActiveHermesSession } from "@/lib/hermes/activeSession";
import {
  displayableTranscriptMessages,
  isNearBottom,
  mergePendingUserMessage,
  pickLatestHermesSessionId,
} from "@/lib/hermes/transcriptHelpers";
import { LONG_ID_CLASS, displayId } from "@/lib/hermes/workbenchA11y";
import {
  fetchHermesSessionMessages,
  fetchWorkspaceSnapshot,
  type HermesSessionMessage,
} from "@/lib/hermes/workspaceClient";
import type { Locale } from "@/lib/locale";

export type WorkbenchTranscriptPanelProps = {
  locale: Locale;
};

type PriorBundle = {
  sessionId: string;
  messages: HermesSessionMessage[];
  omitted: number;
};

type LoadState =
  | { kind: "idle" }
  | {
      kind: "loading";
      sessionId: string;
      /** Keep prior ready bubbles visible while refreshing (L3b no-flicker). */
      prior?: PriorBundle;
    }
  | {
      kind: "ready";
      sessionId: string;
      messages: HermesSessionMessage[];
      omitted: number;
    }
  | {
      kind: "unavailable";
      sessionId: string;
      detail?: string;
      prior?: PriorBundle;
    };

function priorFromState(state: LoadState): PriorBundle | undefined {
  if (state.kind === "ready") {
    return {
      sessionId: state.sessionId,
      messages: state.messages,
      omitted: state.omitted,
    };
  }
  if (
    (state.kind === "loading" || state.kind === "unavailable") &&
    state.prior
  ) {
    return state.prior;
  }
  return undefined;
}

/**
 * L3a + L3b: workbench-local transcript bound by active hermes_session_id.
 * Loads via same-origin messages BFF; soft-fails without breaking composer.
 * L3b: keep last ready canvas while refreshing; soft-stick scroll; optimistic user.
 */
export function WorkbenchTranscriptPanel({
  locale,
}: WorkbenchTranscriptPanelProps) {
  const isZh = locale === "zh";
  const {
    hermesSessionId,
    setActiveHermesSession,
    transcriptEpoch,
    pendingUserText,
    setPendingUserText,
  } = useActiveHermesSession();
  const [state, setState] = useState<LoadState>({ kind: "idle" });
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);
  const lastMessageKeyRef = useRef<string>("");

  // Bootstrap: if composer has not bound a session yet, pick latest command's
  // hermes_session_id from workspace snapshot (local dark observe).
  useEffect(() => {
    if (hermesSessionId) return;
    let cancelled = false;
    const ac = new AbortController();
    (async () => {
      try {
        const snap = await fetchWorkspaceSnapshot(undefined, ac.signal);
        if (cancelled) return;
        const picked = pickLatestHermesSessionId(snap.commands);
        if (!picked) return;
        // onlyIfEmpty: late snapshot must not clobber a deliver-time bind.
        setActiveHermesSession({
          hermesSessionId: picked.hermesSessionId,
          commandId: picked.commandId,
          onlyIfEmpty: true,
        });
      } catch {
        // Snapshot optional for empty workbench.
      }
    })();
    return () => {
      cancelled = true;
      ac.abort();
    };
  }, [hermesSessionId, setActiveHermesSession]);

  useEffect(() => {
    const sessionId = hermesSessionId?.trim();
    if (!sessionId) {
      setState({ kind: "idle" });
      return;
    }
    let cancelled = false;
    const ac = new AbortController();
    setState((prev) => {
      const prior = priorFromState(prev);
      // Only keep prior bubbles when same session (avoid flash of wrong thread).
      const keep =
        prior && prior.sessionId === sessionId ? prior : undefined;
      return { kind: "loading", sessionId, prior: keep };
    });
    (async () => {
      try {
        const envelope = await fetchHermesSessionMessages(sessionId, ac.signal);
        if (cancelled) return;
        if (envelope.read_status && envelope.read_status !== "available") {
          setState((prev) => ({
            kind: "unavailable",
            sessionId,
            detail: String(envelope.read_status),
            prior:
              priorFromState(prev)?.sessionId === sessionId
                ? priorFromState(prev)
                : undefined,
          }));
          return;
        }
        const messages = displayableTranscriptMessages(envelope.messages);
        setState({
          kind: "ready",
          sessionId,
          messages,
          omitted: Number(envelope.omitted_message_count ?? 0) || 0,
        });
      } catch (error) {
        if (cancelled || ac.signal.aborted) return;
        setState((prev) => ({
          kind: "unavailable",
          sessionId,
          detail: error instanceof Error ? error.message : "fetch failed",
          prior:
            priorFromState(prev)?.sessionId === sessionId
              ? priorFromState(prev)
              : undefined,
        }));
      }
    })();
    return () => {
      cancelled = true;
      ac.abort();
    };
  }, [hermesSessionId, transcriptEpoch]);

  // Drop optimistic bubble once server transcript already has that user text.
  useEffect(() => {
    if (!pendingUserText || state.kind !== "ready") return;
    const hit = state.messages.some(
      (m) => m.role === "user" && m.content.trim() === pendingUserText.trim(),
    );
    if (hit) setPendingUserText(null);
  }, [pendingUserText, setPendingUserText, state]);

  const readyView =
    state.kind === "ready"
      ? state
      : state.kind === "loading" && state.prior
        ? {
            sessionId: state.prior.sessionId,
            messages: state.prior.messages,
            omitted: state.prior.omitted,
          }
        : state.kind === "unavailable" && state.prior
          ? {
              sessionId: state.prior.sessionId,
              messages: state.prior.messages,
              omitted: state.prior.omitted,
            }
          : null;

  const canvasMessages = useMemo(() => {
    if (state.kind === "idle") {
      return mergePendingUserMessage([], pendingUserText);
    }
    if (readyView) {
      return mergePendingUserMessage(readyView.messages, pendingUserText);
    }
    return mergePendingUserMessage([], pendingUserText);
  }, [state.kind, readyView, pendingUserText]);

  // Soft stick-to-bottom: only auto-scroll when user is already near bottom
  // and a new message arrives (L3b; does not steal upward reading).
  useEffect(() => {
    const last = canvasMessages[canvasMessages.length - 1];
    const key = last
      ? `${last.id}:${last.role}:${last.content.length}:${last.timestamp ?? ""}`
      : "empty";
    const changed = key !== lastMessageKeyRef.current;
    lastMessageKeyRef.current = key;
    if (!changed || !stickToBottomRef.current) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [canvasMessages]);

  const onScroll = () => {
    stickToBottomRef.current = isNearBottom(scrollRef.current);
  };

  const headerStatus =
    state.kind === "loading"
      ? isZh
        ? state.prior
          ? "刷新中…"
          : "加载中…"
        : state.prior
          ? "Refreshing…"
          : "Loading…"
      : state.kind === "idle" && !pendingUserText
        ? isZh
          ? "发送一条消息后显示完整回复"
          : "Send a message to load the transcript"
        : state.kind === "unavailable" && !state.prior
          ? isZh
            ? "暂时不可用"
            : "Unavailable"
          : null;

  const showEmptyIdle = state.kind === "idle" && canvasMessages.length === 0;
  const showFirstLoad = state.kind === "loading" && !state.prior && !pendingUserText;
  const showHardUnavailable =
    state.kind === "unavailable" && !state.prior && canvasMessages.length === 0;

  return (
    <section
      aria-label={isZh ? "对话记录" : "Conversation transcript"}
      className="space-y-2"
      data-hermes-workbench-transcript
    >
      <header className="flex items-baseline justify-between gap-2">
        <h2 className="font-headline-sm text-text-primary">
          {isZh ? "对话" : "Conversation"}
        </h2>
        <p
          aria-live="polite"
          className="font-body-sm text-text-secondary"
          data-hermes-transcript-status
        >
          {headerStatus}
        </p>
      </header>

      {showEmptyIdle ? (
        <TranscriptCanvas
          emptyHint={
            isZh
              ? "本地 dark：提交并 delivered 后，这里会显示 Hermes 用户/助手消息。"
              : "Local dark: after deliver, user/assistant messages appear here."
          }
          isZh={isZh}
          messages={[]}
        />
      ) : null}

      {showFirstLoad ? (
        <div
          className="rounded-lg border border-border-subtle bg-bg-surface px-3 py-4 font-body-sm text-text-secondary"
          data-hermes-transcript-loading
        >
          {isZh ? "正在读取会话消息…" : "Fetching session messages…"}
        </div>
      ) : null}

      {showHardUnavailable ? (
        <div
          className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-3 font-body-sm text-text-primary"
          data-hermes-transcript-unavailable
        >
          <p className="font-semibold">
            {isZh ? "暂时无法读取对话" : "Transcript temporarily unavailable"}
          </p>
          <p
            className={`mt-1 ${LONG_ID_CLASS}`}
            title={state.kind === "unavailable" ? state.sessionId : undefined}
          >
            {state.kind === "unavailable"
              ? displayId(state.sessionId, { head: 16, tail: 8, max: 36 })
              : ""}
            {state.kind === "unavailable" && state.detail
              ? ` · ${state.detail}`
              : ""}
          </p>
        </div>
      ) : null}

      {state.kind === "unavailable" && state.prior ? (
        <p
          className="font-body-sm text-warning"
          data-hermes-transcript-stale-warning
        >
          {isZh
            ? `刷新失败，仍显示上一份对话${state.detail ? `（${state.detail}）` : ""}`
            : `Refresh failed; showing last transcript${state.detail ? ` (${state.detail})` : ""}`}
        </p>
      ) : null}

      {!showEmptyIdle && !showFirstLoad && !showHardUnavailable ? (
        <div
          className="max-h-[min(48vh,28rem)] overflow-y-auto rounded-lg"
          data-hermes-transcript-scroll
          onScroll={onScroll}
          ref={scrollRef}
        >
          <TranscriptCanvas
            hermesSessionId={
              readyView?.sessionId ?? hermesSessionId ?? undefined
            }
            isZh={isZh}
            messages={canvasMessages}
            omittedCount={readyView?.omitted ?? 0}
          />
        </div>
      ) : null}
    </section>
  );
}
