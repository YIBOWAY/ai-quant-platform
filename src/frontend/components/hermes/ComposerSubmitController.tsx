'use client';

import { useCallback, useEffect, useRef, useState } from "react";

import { ComposerDock } from "@/components/hermes/ComposerDock";
import type { ComposerDockProps } from "@/components/hermes/ComposerDock";
import { useOptionalActiveHermesSession } from "@/lib/hermes/activeSession";
import {
  WorkspaceClientError,
  fetchLatestAssistantText,
  fetchWorkspaceSnapshot,
  isTerminalCommandState,
  pollCommandUntilTerminal,
  previewAssistantText,
  sendComposerTurn,
} from "@/lib/hermes/workspaceClient";

export type ComposerSubmitControllerProps = Omit<
  ComposerDockProps,
  "onSubmitPrompt" | "statusText" | "busy"
> & {
  /** When false, dock stays visual-only even if allowSubmit is true. */
  networkSubmit?: boolean;
};

function shortCommandId(commandId?: string | null): string {
  if (!commandId) return "";
  return commandId.length > 8 ? `${commandId.slice(0, 8)}…` : commandId;
}

function formatReceiptStatus(status: string, commandId?: string, reason?: string): string {
  const cmd = commandId ? ` · command ${shortCommandId(commandId)}` : "";
  const why = reason ? ` (${reason})` : "";
  switch (status) {
    case "accepted":
      return `Accepted${cmd}`;
    case "outcome_unknown":
      return `Outcome unknown — retry same send or follow workspace${why}`;
    case "conflict":
      return `Conflict${why}`;
    case "unavailable":
      return `Unavailable${why}`;
    case "reconciling":
      return `Reconciling${cmd}`;
    default:
      return `${status}${why}`;
  }
}

function formatLifecycleStatus(
  state: string | null,
  commandId?: string | null,
  hermesRunId?: string | null,
): string {
  const cmd = commandId ? ` · ${shortCommandId(commandId)}` : "";
  const run =
    hermesRunId && hermesRunId.length > 12
      ? ` · run ${hermesRunId.slice(0, 12)}…`
      : hermesRunId
        ? ` · run ${hermesRunId}`
        : "";
  switch (state) {
    case "queued":
      return `Queued${cmd}`;
    case "leased":
      return `Leased${cmd}`;
    case "delivered":
      return `Delivered${cmd}${run}`;
    case "failed":
      return `Failed${cmd}`;
    case "rejected":
      return `Rejected${cmd}`;
    case "cancelled":
      return `Cancelled${cmd}`;
    case "timed_out":
      return `Timed out${cmd}`;
    case "outcome_unknown":
      return `Outcome unknown${cmd}`;
    default:
      return state ? `${state}${cmd}` : `Tracking${cmd}`;
  }
}

/**
 * L2b-M2: best-effort assistant preview after deliver.
 * Failures leave lifecycle status intact (messages path is interim, not ledger).
 */
async function surfaceAssistantPreview(options: {
  hermesSessionId: string | null | undefined;
  commandId?: string | null;
  hermesRunId?: string | null;
  signal: AbortSignal;
  setStatusText: (text: string | null) => void;
  lifecyclePrefix?: string;
  /** L3a: publish session id so workbench transcript can load full messages. */
  onBindSession?: (next: {
    hermesSessionId: string;
    commandId?: string | null;
  }) => void;
}): Promise<void> {
  const sessionId = options.hermesSessionId?.trim();
  if (!sessionId || options.signal.aborted) {
    return;
  }
  options.onBindSession?.({
    hermesSessionId: sessionId,
    commandId: options.commandId,
  });
  const lifecycle =
    options.lifecyclePrefix ??
    formatLifecycleStatus("delivered", options.commandId, options.hermesRunId);
  options.setStatusText(`${lifecycle} · loading reply…`);
  const text = await fetchLatestAssistantText({
    hermesSessionId: sessionId,
    signal: options.signal,
  });
  if (options.signal.aborted) {
    return;
  }
  if (!text) {
    options.setStatusText(lifecycle);
    return;
  }
  options.setStatusText(`${lifecycle} · ${previewAssistantText(text)}`);
}

/**
 * Client boundary that wires L2a-Send composite submit into ComposerDock.
 * L2b-M1: after accept, poll workspace follow for command lifecycle.
 * L2b-M2: after delivered, fetch Hermes messages and surface assistant preview.
 * Parent shell stays a server component; only this island touches cookies/fetch.
 */
export function ComposerSubmitController({
  networkSubmit = false,
  allowSubmit = false,
  disabled = true,
  ...dockProps
}: ComposerSubmitControllerProps) {
  const [statusText, setStatusText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pollAbortRef = useRef<AbortController | null>(null);
  const activeSession = useOptionalActiveHermesSession();
  const bindSession = activeSession?.setActiveHermesSession;
  const setPendingUserText = activeSession?.setPendingUserText;

  useEffect(() => {
    return () => {
      pollAbortRef.current?.abort();
      pollAbortRef.current = null;
    };
  }, []);

  const onSubmitPrompt = useCallback(
    async (prompt: string) => {
      if (!networkSubmit) {
        throw new WorkspaceClientError(
          "network submit is not enabled on this shell",
          403,
          "forbidden",
        );
      }
      // Abort any in-flight poll from a prior send.
      pollAbortRef.current?.abort();
      const pollAbort = new AbortController();
      pollAbortRef.current = pollAbort;

      setBusy(true);
      setStatusText("Submitting…");
      // One UUID per gesture; outcome_unknown retries should reuse — user can resend.
      const clientActionId = crypto.randomUUID();
      try {
        const receipt = await sendComposerTurn({
          prompt,
          clientActionId,
          signal: pollAbort.signal,
        });
        setStatusText(
          formatReceiptStatus(
            receipt.status,
            receipt.command_id,
            receipt.reason_code,
          ),
        );

        // L3b: optimistic user bubble on accept (or outcome_unknown with command).
        // Bind still only happens on deliver via surfaceAssistantPreview.
        if (
          receipt.status === "accepted" ||
          (receipt.status === "outcome_unknown" && receipt.command_id)
        ) {
          setPendingUserText?.(prompt);
        }

        if (
          receipt.status === "conflict" ||
          receipt.status === "unavailable"
        ) {
          throw new WorkspaceClientError(
            formatReceiptStatus(
              receipt.status,
              receipt.command_id,
              receipt.reason_code,
            ),
            receipt.status === "conflict" ? 409 : 503,
            receipt.status,
          );
        }

        // L2b-M1: after accept (or outcome_unknown with a command id), poll follow.
        if (receipt.command_id && !pollAbort.signal.aborted) {
          let afterCursor: number | null = 0;
          let earlyHermesSessionId: string | null =
            receipt.hermes_session_id ?? null;
          try {
            const snap = await fetchWorkspaceSnapshot(
              undefined,
              pollAbort.signal,
            );
            afterCursor = snap.snapshot_workspace_cursor ?? 0;
            const match = (snap.commands ?? []).find(
              (c) => c.command_id === receipt.command_id,
            );
            if (match?.state) {
              setStatusText(
                formatLifecycleStatus(
                  match.state,
                  receipt.command_id,
                  match.hermes_run_id,
                ),
              );
              if (match.hermes_session_id) {
                earlyHermesSessionId = match.hermes_session_id;
              }
              if (isTerminalCommandState(match.state)) {
                if (match.state === "delivered") {
                  await surfaceAssistantPreview({
                    hermesSessionId: earlyHermesSessionId,
                    commandId: receipt.command_id,
                    hermesRunId: match.hermes_run_id ?? null,
                    signal: pollAbort.signal,
                    setStatusText,
                    onBindSession: bindSession,
                  });
                } else {
                  // L3b: drop optimistic "sending" bubble on terminal non-deliver.
                  setPendingUserText?.(null);
                }
                return;
              }
            }
          } catch {
            // Snapshot blip is non-fatal; poll from cursor 0.
            afterCursor = 0;
          }

          if (pollAbort.signal.aborted) {
            return;
          }

          setStatusText(
            formatLifecycleStatus("queued", receipt.command_id, null),
          );
          const result = await pollCommandUntilTerminal({
            commandId: receipt.command_id,
            afterCursor,
            signal: pollAbort.signal,
          });
          if (pollAbort.signal.aborted) {
            return;
          }
          const lifecycle = formatLifecycleStatus(
            result.state ?? "queued",
            receipt.command_id,
            result.hermesRunId,
          );
          setStatusText(lifecycle);

          // L2b-M2: after delivered, pull assistant body via Hermes messages path.
          // L3a: also bind workbench transcript to hermes_session_id.
          if (result.state === "delivered") {
            await surfaceAssistantPreview({
              hermesSessionId:
                result.hermesSessionId ?? earlyHermesSessionId,
              commandId: receipt.command_id,
              hermesRunId: result.hermesRunId,
              signal: pollAbort.signal,
              setStatusText,
              lifecyclePrefix: lifecycle,
              onBindSession: bindSession,
            });
          } else if (result.state && isTerminalCommandState(result.state)) {
            // L3b: failed/cancelled/etc. must not leave a stuck "sending" bubble.
            setPendingUserText?.(null);
          }
        }
      } catch (error) {
        if (pollAbort.signal.aborted) {
          return;
        }
        if (error instanceof WorkspaceClientError) {
          setStatusText(error.message);
        } else if (error instanceof Error) {
          setStatusText(error.message);
        } else {
          setStatusText("Submit failed");
        }
        throw error;
      } finally {
        if (pollAbortRef.current === pollAbort) {
          pollAbortRef.current = null;
        }
        if (!pollAbort.signal.aborted) {
          setBusy(false);
        }
      }
    },
    [networkSubmit, bindSession, setPendingUserText],
  );

  return (
    <ComposerDock
      {...dockProps}
      allowSubmit={allowSubmit}
      busy={busy}
      disabled={disabled}
      onSubmitPrompt={networkSubmit && allowSubmit && !disabled ? onSubmitPrompt : undefined}
      statusText={statusText}
    />
  );
}
