'use client';

import { useCallback, useEffect, useRef, useState } from "react";

import { ComposerDock } from "@/components/hermes/ComposerDock";
import type { ComposerDockProps } from "@/components/hermes/ComposerDock";
import { useOptionalActiveHermesSession } from "@/lib/hermes/activeSession";
import {
  createComposerAttempt,
  retryComposerAttempt,
  shouldRetainComposerAttemptAfterError,
  type ComposerAttempt,
} from "@/lib/hermes/composerAttempt";
import {
  WorkspaceClientError,
  fetchLatestAssistantText,
  isTerminalCommandState,
  previewAssistantText,
  sendComposerTurn,
} from "@/lib/hermes/workspaceClient";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import { waitForCommandTerminalOnSpine } from "@/lib/hermes/workspaceFollowSpine";

export type ComposerSubmitControllerProps = Omit<
  ComposerDockProps,
  "onSubmitPrompt" | "onRetry" | "statusText" | "busy"
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
    case "succeeded":
      return `Succeeded${cmd}${run}`;
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
 * Best-effort assistant preview only after replay-backed terminal success.
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
    formatLifecycleStatus("succeeded", options.commandId, options.hermesRunId);
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
 * L5a: after accept, wait on shared L4b follow spine (no private follow poll).
 * After succeeded, fetch Hermes messages and surface assistant preview.
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
  const [retryAttempt, setRetryAttempt] = useState<ComposerAttempt | null>(null);
  const pollAbortRef = useRef<AbortController | null>(null);
  const activeSession = useOptionalActiveHermesSession();
  const bindSession = activeSession?.setActiveHermesSession;
  const setPendingUserText = activeSession?.setPendingUserText;
  const { state: followState, spine } = useWorkspaceFollow();

  useEffect(() => {
    return () => {
      pollAbortRef.current?.abort();
      pollAbortRef.current = null;
    };
  }, []);

  const submitAttempt = useCallback(
    async (attempt: ComposerAttempt) => {
      const { prompt, clientActionId } = attempt;
      if (!networkSubmit) {
        throw new WorkspaceClientError(
          "network submit is not enabled on this shell",
          403,
          "forbidden",
        );
      }
      // Abort any in-flight wait from a prior send.
      pollAbortRef.current?.abort();
      const pollAbort = new AbortController();
      pollAbortRef.current = pollAbort;

      setBusy(true);
      setStatusText("Submitting…");
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
        if (receipt.status === "outcome_unknown") {
          setRetryAttempt(attempt);
        } else {
          setRetryAttempt(null);
        }

        // L3b: optimistic user bubble on accept (or outcome_unknown with command).
        // Bind still only happens on terminal success via surfaceAssistantPreview.
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

        // L5a: after accept (or outcome_unknown with a command id), wait on spine.
        if (receipt.command_id && !pollAbort.signal.aborted) {
          let earlyHermesSessionId: string | null =
            receipt.hermes_session_id ?? null;

          // Immediate match from shared spine snapshot (no private GET).
          const existing = followState.commands.find(
            (c) => c.command_id === receipt.command_id,
          );
          if (existing?.state) {
            setStatusText(
              formatLifecycleStatus(
                existing.state,
                receipt.command_id,
                existing.hermes_run_id,
              ),
            );
            if (existing.hermes_session_id) {
              earlyHermesSessionId = existing.hermes_session_id;
            }
            if (isTerminalCommandState(existing.state)) {
              setRetryAttempt(null);
              if (existing.state === "succeeded") {
                await surfaceAssistantPreview({
                  hermesSessionId: earlyHermesSessionId,
                  commandId: receipt.command_id,
                  hermesRunId: existing.hermes_run_id ?? null,
                  signal: pollAbort.signal,
                  setStatusText,
                  onBindSession: bindSession,
                });
              } else {
                setPendingUserText?.(null);
              }
              return;
            }
          }

          if (pollAbort.signal.aborted) {
            return;
          }

          setStatusText(
            formatLifecycleStatus("queued", receipt.command_id, null),
          );

          // Nudge spine after submit so we do not wait solely on the next tick.
          if (spine) {
            void spine.resyncNow().catch(() => {
              /* soft */
            });
          }

          const match = spine
            ? await waitForCommandTerminalOnSpine(spine, {
                commandId: receipt.command_id,
                signal: pollAbort.signal,
                timeoutMs: 45_000,
              })
            : null;

          if (pollAbort.signal.aborted) {
            return;
          }

          const observed =
            match ??
            spine?.getState().commands.find(
              (command) => command.command_id === receipt.command_id,
            ) ??
            null;
          const terminalState = observed?.state ?? null;
          const lifecycle = formatLifecycleStatus(
            terminalState ?? "queued",
            receipt.command_id,
            observed?.hermes_run_id ?? null,
          );
          setStatusText(
            terminalState
              ? lifecycle
              : `${lifecycle} · still tracking via follow spine`,
          );

          if (terminalState === "outcome_unknown") {
            setRetryAttempt(attempt);
          }

          if (terminalState === "succeeded") {
            setRetryAttempt(null);
            await surfaceAssistantPreview({
              hermesSessionId:
                observed?.hermes_session_id ?? earlyHermesSessionId,
              commandId: receipt.command_id,
              hermesRunId: observed?.hermes_run_id ?? null,
              signal: pollAbort.signal,
              setStatusText,
              lifecyclePrefix: lifecycle,
              onBindSession: bindSession,
            });
          } else if (terminalState && isTerminalCommandState(terminalState)) {
            setRetryAttempt(null);
            setPendingUserText?.(null);
          }
        }
      } catch (error) {
        if (pollAbort.signal.aborted) {
          return;
        }
        if (shouldRetainComposerAttemptAfterError(error)) {
          setRetryAttempt(attempt);
        } else {
          setRetryAttempt(null);
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
    [
      networkSubmit,
      bindSession,
      setPendingUserText,
      spine,
      followState.commands,
    ],
  );

  const onSubmitPrompt = useCallback(
    (prompt: string) => {
      const attempt = createComposerAttempt(prompt);
      setRetryAttempt(null);
      return submitAttempt(attempt);
    },
    [submitAttempt],
  );

  const onRetry = useCallback(() => {
    if (!retryAttempt) return Promise.resolve();
    return submitAttempt(retryComposerAttempt(retryAttempt));
  }, [retryAttempt, submitAttempt]);

  return (
    <ComposerDock
      {...dockProps}
      allowSubmit={allowSubmit}
      busy={busy}
      disabled={disabled}
      onSubmitPrompt={networkSubmit && allowSubmit && !disabled ? onSubmitPrompt : undefined}
      onRetry={
        retryAttempt && networkSubmit && allowSubmit && !disabled
          ? onRetry
          : undefined
      }
      statusText={statusText}
    />
  );
}
