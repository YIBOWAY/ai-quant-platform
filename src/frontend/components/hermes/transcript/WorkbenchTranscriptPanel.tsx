'use client';

import { useEffect, useState } from "react";

import { TranscriptCanvas } from "@/components/hermes/transcript/TranscriptCanvas";
import { useActiveHermesSession } from "@/lib/hermes/activeSession";
import {
  displayableTranscriptMessages,
  pickLatestHermesSessionId,
} from "@/lib/hermes/transcriptHelpers";
import {
  fetchHermesSessionMessages,
  fetchWorkspaceSnapshot,
  type HermesSessionMessage,
} from "@/lib/hermes/workspaceClient";
import type { Locale } from "@/lib/locale";

export type WorkbenchTranscriptPanelProps = {
  locale: Locale;
};

type LoadState =
  | { kind: "idle" }
  | { kind: "loading"; sessionId: string }
  | {
      kind: "ready";
      sessionId: string;
      messages: HermesSessionMessage[];
      omitted: number;
    }
  | { kind: "unavailable"; sessionId: string; detail?: string };

/**
 * L3a-Transcript-M1: workbench-local transcript bound by active hermes_session_id.
 * Loads via same-origin messages BFF; soft-fails without breaking composer.
 */
export function WorkbenchTranscriptPanel({
  locale,
}: WorkbenchTranscriptPanelProps) {
  const isZh = locale === "zh";
  const { hermesSessionId, setActiveHermesSession, transcriptEpoch } =
    useActiveHermesSession();
  const [state, setState] = useState<LoadState>({ kind: "idle" });

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
    setState({ kind: "loading", sessionId });
    (async () => {
      try {
        const envelope = await fetchHermesSessionMessages(sessionId, ac.signal);
        if (cancelled) return;
        if (envelope.read_status && envelope.read_status !== "available") {
          setState({
            kind: "unavailable",
            sessionId,
            detail: String(envelope.read_status),
          });
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
        setState({
          kind: "unavailable",
          sessionId,
          detail: error instanceof Error ? error.message : "fetch failed",
        });
      }
    })();
    return () => {
      cancelled = true;
      ac.abort();
    };
  }, [hermesSessionId, transcriptEpoch]);

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
        <p className="font-body-sm text-text-secondary">
          {state.kind === "loading"
            ? isZh
              ? "加载中…"
              : "Loading…"
            : state.kind === "idle"
              ? isZh
                ? "发送一条消息后显示完整回复"
                : "Send a message to load the transcript"
              : null}
        </p>
      </header>

      {state.kind === "idle" ? (
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

      {state.kind === "loading" ? (
        <div
          className="rounded-lg border border-border-subtle bg-bg-surface px-3 py-4 font-body-sm text-text-secondary"
          data-hermes-transcript-loading
        >
          {isZh ? "正在读取会话消息…" : "Fetching session messages…"}
        </div>
      ) : null}

      {state.kind === "unavailable" ? (
        <div
          className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-3 font-body-sm text-text-primary"
          data-hermes-transcript-unavailable
        >
          <p className="font-semibold">
            {isZh ? "暂时无法读取对话" : "Transcript temporarily unavailable"}
          </p>
          <p className="mt-1 font-data-mono text-xs text-text-secondary">
            {state.sessionId}
            {state.detail ? ` · ${state.detail}` : ""}
          </p>
        </div>
      ) : null}

      {state.kind === "ready" ? (
        <TranscriptCanvas
          hermesSessionId={state.sessionId}
          isZh={isZh}
          messages={state.messages}
          omittedCount={state.omitted}
        />
      ) : null}
    </section>
  );
}
