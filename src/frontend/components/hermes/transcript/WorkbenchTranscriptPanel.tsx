'use client';

import { useEffect, useMemo, useRef, useState } from "react";

import { TranscriptCanvas } from "@/components/hermes/transcript/TranscriptCanvas";
import { useActiveHermesSession } from "@/lib/hermes/activeSession";
import {
  assistantContentLength,
  createQuietRefetchScheduler,
  deriveAssistantPhase,
  displayableTranscriptMessages,
  isNearBottom,
  isUsableHermesApiSessionId,
  mergePendingUserMessage,
  type AssistantPhase,
  type QuietRefetchScheduler,
} from "@/lib/hermes/transcriptHelpers";
import { LONG_ID_CLASS, displayId } from "@/lib/hermes/workbenchA11y";
import {
  fetchHermesSessionMessages,
  isTerminalCommandState,
  type HermesSessionMessage,
} from "@/lib/hermes/workspaceClient";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
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

function pageScrollRegion(): HTMLElement | null {
  if (typeof document === "undefined") return null;
  return document.querySelector<HTMLElement>("[data-page-scroll-region]");
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
    transcriptEpoch,
    pendingUserText,
    setPendingUserText,
  } = useActiveHermesSession();
  const { state: followState } = useWorkspaceFollow();
  const [state, setState] = useState<LoadState>({ kind: "idle" });
  const [phase, setPhase] = useState<AssistantPhase>("idle");
  const scrollRef = useRef<HTMLElement | null>(null);
  const stickToBottomRef = useRef(true);
  const lastMessageKeyRef = useRef<string>("");
  const lastDirtySeqRef = useRef<number>(-1);
  const inFlightRef = useRef(false); // bootstrap / non-quiet load only
  const quietSchedulerRef = useRef<QuietRefetchScheduler | null>(null);
  const hermesSessionIdRef = useRef<string | null>(hermesSessionId);
  hermesSessionIdRef.current = hermesSessionId;

  // No snapshot bootstrap: a managed row from an earlier browser visit is
  // stale history, and auto-resuming it would replace the Today landing
  // dashboard with a fullscreen transcript on every reload. Sessions are
  // entered explicitly — deep link, sessions-page fork, or "New blank
  // conversation" — all of which bind the active session directly.

  // Plan-V6-Token-Stream-M1: load/refetch messages BFF (text authority).
  // Triggered by session bind, transcriptEpoch, and spine transcriptDirtySeq.
  useEffect(() => {
    const sessionId = hermesSessionId?.trim();
    if (!sessionId || !isUsableHermesApiSessionId(sessionId)) {
      setState({ kind: "idle" });
      setPhase("idle");
      return;
    }
    let cancelled = false;
    const ac = new AbortController();

    const runFetch = async (opts?: { quiet?: boolean }) => {
      if (inFlightRef.current && opts?.quiet) return;
      inFlightRef.current = true;
      if (!opts?.quiet) {
        setState((prev) => {
          const prior = priorFromState(prev);
          const keep =
            prior && prior.sessionId === sessionId ? prior : undefined;
          return { kind: "loading", sessionId, prior: keep };
        });
      }
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
          setPhase("unavailable");
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
        setPhase("unavailable");
      } finally {
        inFlightRef.current = false;
      }
    };

    void runFetch({ quiet: false });

    return () => {
      cancelled = true;
      ac.abort();
    };
  }, [hermesSessionId, transcriptEpoch]);

  // Single owner for quiet messages refetch (V8-M2 GAP-09).
  // Spine dirty + waiting/partial interval both schedule through one scheduler
  // with pending-bit (no recursive re-arm chain while hung).
  useEffect(() => {
    const scheduler = createQuietRefetchScheduler({
      coalesceMs: 200,
      fetch: async (sessionId: string) => {
        // Drop stale writes if session drifted mid-flight.
        if (hermesSessionIdRef.current?.trim() !== sessionId) return;
        try {
          const envelope = await fetchHermesSessionMessages(sessionId);
          if (hermesSessionIdRef.current?.trim() !== sessionId) return;
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
            setPhase("unavailable");
            return;
          }
          const messages = displayableTranscriptMessages(envelope.messages);
          setState({
            kind: "ready",
            sessionId,
            messages,
            omitted: Number(envelope.omitted_message_count ?? 0) || 0,
          });
        } catch {
          // Soft-fail quiet refetch; keep prior canvas.
        }
      },
    });
    quietSchedulerRef.current = scheduler;
    return () => {
      scheduler.dispose();
      if (quietSchedulerRef.current === scheduler) {
        quietSchedulerRef.current = null;
      }
    };
  }, []);

  const scheduleQuietRefetch = (sessionId: string) => {
    quietSchedulerRef.current?.schedule(sessionId);
  };

  // Spine-driven dirty: coalesced refetch while waiting/partial or on hint.
  useEffect(() => {
    const sessionId = hermesSessionId?.trim();
    if (!sessionId || !isUsableHermesApiSessionId(sessionId)) return;
    const dirty = followState.transcriptDirtySeq ?? 0;
    if (dirty === lastDirtySeqRef.current) return;
    lastDirtySeqRef.current = dirty;
    scheduleQuietRefetch(sessionId);
  }, [followState.transcriptDirtySeq, hermesSessionId]);

  // Bounded backoff poll while phase is waiting/partial — same owner as dirty path.
  useEffect(() => {
    if (phase !== "waiting" && phase !== "partial") return;
    const sessionId = hermesSessionId?.trim();
    if (!sessionId || !isUsableHermesApiSessionId(sessionId)) return;
    const id = setInterval(() => {
      // Nudge sole owner; do not open a second fetch pipeline.
      scheduleQuietRefetch(sessionId);
    }, 1500);
    return () => clearInterval(id);
  }, [phase, hermesSessionId]);

  // Session change: drop pending quiet work for prior session.
  useEffect(() => {
    return () => {
      // On session id change React re-runs; dispose is owned by mount effect.
      // Pending bit is session-scoped via hermesSessionIdRef guard in fetch.
    };
  }, [hermesSessionId]);

  // Derive honest phase from command + messages (never invent tokens).
  useEffect(() => {
    const sessionId = hermesSessionId?.trim() ?? null;
    const cmd = sessionId
      ? followState.commands.find((c) => c.hermes_session_id === sessionId)
      : undefined;
    // Prefer explicit transcript hint phase when present.
    const hint = sessionId
      ? followState.transcriptHints.find((h) => h.hermes_session_id === sessionId)
      : undefined;
    const msgs =
      state.kind === "ready"
        ? state.messages
        : state.kind === "loading" && state.prior
          ? state.prior.messages
          : state.kind === "unavailable" && state.prior
            ? state.prior.messages
            : [];
    const readStatus =
      state.kind === "unavailable" ? state.detail ?? "unavailable" : "available";
    let next = deriveAssistantPhase({
      hasActiveSession: Boolean(sessionId),
      commandState: cmd?.state ?? null,
      assistantContentLength: assistantContentLength(msgs),
      messagesReadStatus: state.kind === "unavailable" ? readStatus : null,
      submitAccepted: Boolean(pendingUserText) && !isTerminalCommandState(cmd?.state),
      priorPhase: phase,
    });
    // Hint can promote waiting→partial only when we already have assistant text;
    // never invent partial without messages growth.
    if (hint?.phase === "waiting" && next === "idle") {
      next = "waiting";
    }
    if (hint?.phase === "final" && isTerminalCommandState(cmd?.state)) {
      next = assistantContentLength(msgs) > 0 || isTerminalCommandState(cmd?.state)
        ? "final"
        : next;
    }
    if (next !== phase) setPhase(next);
  }, [
    hermesSessionId,
    followState.commands,
    followState.transcriptHints,
    state,
    pendingUserText,
    phase,
  ]);

  // Drop optimistic bubble once server transcript already has that user text.
  useEffect(() => {
    if (!pendingUserText || state.kind !== "ready") return;
    const hit = state.messages.some(
      (m) => m.role === "user" && m.content.trim() === pendingUserText.trim(),
    );
    if (hit) setPendingUserText(null);
  }, [pendingUserText, setPendingUserText, state]);

  const readyView = useMemo<PriorBundle | null>(() => {
    if (state.kind === "ready") return state;
    if (
      (state.kind === "loading" || state.kind === "unavailable") &&
      state.prior
    ) {
      return {
        sessionId: state.prior.sessionId,
        messages: state.prior.messages,
        omitted: state.prior.omitted,
      };
    }
    return null;
  }, [state]);

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

  // Scrolling belongs to the page-level region now, so stick-to-bottom binds to
  // the nearest [data-page-scroll-region] ancestor instead of an inner box.
  useEffect(() => {
    const el = pageScrollRegion();
    scrollRef.current = el;
    if (!el) return;
    const onScroll = () => {
      stickToBottomRef.current = isNearBottom(el);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
      if (scrollRef.current === el) scrollRef.current = null;
    };
  }, []);

  const phaseLabel =
    phase === "waiting"
      ? isZh
        ? "等待回复…"
        : "Waiting…"
      : phase === "partial"
        ? isZh
          ? "更新中…"
          : "Updating…"
        : phase === "final"
          ? isZh
            ? "已完成"
            : "Final"
          : phase === "unavailable"
            ? isZh
              ? "不可用"
              : "Unavailable"
            : null;

  const headerStatus =
    phaseLabel && (phase === "waiting" || phase === "partial")
      ? phaseLabel
      : state.kind === "loading"
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
            : phaseLabel;

  const showEmptyIdle = state.kind === "idle" && canvasMessages.length === 0;
  const showFirstLoad = state.kind === "loading" && !state.prior && !pendingUserText;
  const showHardUnavailable =
    state.kind === "unavailable" && !state.prior && canvasMessages.length === 0;

  return (
    <section
      aria-label={isZh ? "对话记录" : "Conversation transcript"}
      className="space-y-2"
      data-hermes-workbench-transcript
      data-hermes-token-stream="v6-m1"
      data-hermes-assistant-phase={phase}
      data-hermes-transcript-transport="spine-refetch"
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
          assistantPhase={phase}
          emptyHint={
            isZh
              ? "本地 dark：提交并 delivered 后，这里会显示 Hermes 用户/助手消息。"
              : "Local dark: after deliver, user/assistant messages appear here."
          }
          isZh={isZh}
          messages={[]}
          transport="spine-refetch"
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
        <div className="rounded-lg">
          <TranscriptCanvas
            assistantPhase={phase}
            hermesSessionId={
              readyView?.sessionId ?? hermesSessionId ?? undefined
            }
            isZh={isZh}
            messages={canvasMessages}
            omittedCount={readyView?.omitted ?? 0}
            transport="spine-refetch"
          />
        </div>
      ) : null}
    </section>
  );
}
