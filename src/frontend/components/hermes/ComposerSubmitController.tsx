'use client';

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ComposerDock } from "@/components/hermes/ComposerDock";
import type { ComposerDockProps } from "@/components/hermes/ComposerDock";
import { useOptionalActiveHermesSession } from "@/lib/hermes/activeSession";
import {
  canRetryComposerAttempt,
  createComposerAttempt,
  retryComposerAttempt,
  shouldRetainComposerAttemptAfterError,
  type ComposerAttempt,
  type SessionBoundComposerAttempt,
} from "@/lib/hermes/composerAttempt";
import {
  composerErrorMessage,
  composerLoadingReplyText,
  composerStillTrackingText,
  composerSubmittingText,
  formatComposerLifecycleStatus,
  formatComposerReceiptStatus,
} from "@/lib/hermes/composerPresentation";
import { freshManagedSessionErrorCopy } from "@/lib/hermes/managedSessionPresentation";
import { activateReadyManagedHermesSession } from "@/lib/hermes/sessionForkNavigation";
import {
  WorkspaceClientError,
  fetchLatestAssistantText,
  fetchWorkspaceSnapshot,
  isTerminalCommandState,
  managedSessionIsReadyForHermesSession,
  previewAssistantText,
  requireSameComposerHermesSession,
  resolveComposerHermesSessionId,
  sendComposerTurn,
  startFreshManagedSession,
} from "@/lib/hermes/workspaceClient";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import { waitForCommandTerminalOnSpine } from "@/lib/hermes/workspaceFollowSpine";
import type { Locale } from "@/lib/locale";

export type ComposerSubmitControllerProps = Omit<
  ComposerDockProps,
  | "onSubmitPrompt"
  | "onRetry"
  | "onStartNewSession"
  | "statusText"
  | "busy"
  | "locale"
  | "draftResetToken"
> & {
  /** When false, dock stays visual-only even if allowSubmit is true. */
  networkSubmit?: boolean;
  locale?: Locale;
  emptySessionText?: string;
  newSessionCreatingText?: string;
  newSessionReadyText?: string;
  readOnlySessionText?: string;
  sessionCheckingText?: string;
  sessionValidationUnavailableText?: string;
};

type SessionWriteAssessment = {
  sessionId: string | null;
  state: "checking" | "empty" | "writable" | "read_only" | "unavailable";
};

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
  locale: Locale;
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
    formatComposerLifecycleStatus(
      "succeeded",
      options.commandId,
      options.hermesRunId,
      options.locale,
    );
  options.setStatusText(
    `${lifecycle} · ${composerLoadingReplyText(options.locale)}`,
  );
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
  locale = "en",
  emptySessionText = "Start a new blank conversation before sending.",
  newSessionCreatingText = "Creating a new managed conversation…",
  newSessionReadyText = "New managed conversation ready.",
  readOnlySessionText = "This session is read-only. Fork a specific message to continue its context, or start a new blank conversation.",
  sessionCheckingText = "Checking whether this session can accept messages…",
  sessionValidationUnavailableText = "Session write access could not be verified. Sending remains locked; start a new blank conversation or check local backend health.",
  ...dockProps
}: ComposerSubmitControllerProps) {
  const [statusText, setStatusText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [retryAttempt, setRetryAttempt] =
    useState<SessionBoundComposerAttempt | null>(null);
  const [newSessionAttemptActive, setNewSessionAttemptActive] = useState(false);
  const [acceptedDraftToken, setAcceptedDraftToken] = useState(0);
  const [sessionAssessment, setSessionAssessment] =
    useState<SessionWriteAssessment>({
      sessionId: null,
      state: "checking",
    });
  const pollAbortRef = useRef<AbortController | null>(null);
  const newSessionActionIdRef = useRef<string | null>(null);
  const focusComposerWhenWritableRef = useRef<string | null>(null);
  const router = useRouter();
  const activeSession = useOptionalActiveHermesSession();
  const activeHermesSessionId = activeSession?.hermesSessionId;
  const bindSession = activeSession?.setActiveHermesSession;
  const setPendingUserText = activeSession?.setPendingUserText;
  const { state: followState, spine } = useWorkspaceFollow();

  useEffect(() => {
    return () => {
      pollAbortRef.current?.abort();
      pollAbortRef.current = null;
    };
  }, []);

  useEffect(() => {
    const sessionId = activeHermesSessionId?.trim() || null;
    if (!sessionId) {
      // Give a same-commit deep-link binder one frame to establish the exact
      // URL-selected session before enabling an empty-session composer.
      const frame = window.requestAnimationFrame(() => {
        setSessionAssessment({ sessionId: null, state: "empty" });
      });
      return () => window.cancelAnimationFrame(frame);
    }
    const controller = new AbortController();
    void fetchWorkspaceSnapshot(undefined, controller.signal)
      .then((snapshot) => {
        if (controller.signal.aborted) return;
        const writable = managedSessionIsReadyForHermesSession(
          snapshot,
          sessionId,
        );
        setSessionAssessment({
          sessionId,
          state: writable ? "writable" : "read_only",
        });
        if (
          writable &&
          focusComposerWhenWritableRef.current === sessionId
        ) {
          focusComposerWhenWritableRef.current = null;
          window.requestAnimationFrame(() => {
            document.getElementById("hermes-composer-draft")?.focus();
          });
        }
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setSessionAssessment({ sessionId, state: "unavailable" });
      });
    return () => controller.abort();
  }, [activeHermesSessionId]);

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
      setStatusText(composerSubmittingText(locale));
      let selectedHermesSessionId: string | null = null;
      try {
        selectedHermesSessionId = resolveComposerHermesSessionId(
          activeHermesSessionId,
        );
        const receipt = await sendComposerTurn({
          prompt,
          clientActionId,
          activeHermesSessionId,
          signal: pollAbort.signal,
        });
        setStatusText(
          formatComposerReceiptStatus(
            receipt.status,
            receipt.command_id,
            receipt.reason_code,
            locale,
          ),
        );
        const submittedHermesSessionId = requireSameComposerHermesSession(
          receipt.hermes_session_id,
        );
        if (selectedHermesSessionId) {
          requireSameComposerHermesSession(
            selectedHermesSessionId,
            submittedHermesSessionId,
          );
        }
        if (receipt.status === "outcome_unknown") {
          setRetryAttempt({
            attempt,
            hermesSessionId: submittedHermesSessionId,
          });
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
          setAcceptedDraftToken((value) => value + 1);
        }

        if (
          receipt.status === "conflict" ||
          receipt.status === "unavailable"
        ) {
          throw new WorkspaceClientError(
            formatComposerReceiptStatus(
              receipt.status,
              receipt.command_id,
              receipt.reason_code,
              locale,
            ),
            receipt.status === "conflict" ? 409 : 503,
            receipt.status,
          );
        }

        // L5a: after accept (or outcome_unknown with a command id), wait on spine.
        if (receipt.command_id && !pollAbort.signal.aborted) {
          // Immediate match from shared spine snapshot (no private GET).
          const existing = followState.commands.find(
            (c) => c.command_id === receipt.command_id,
          );
          if (existing?.state) {
            setStatusText(
              formatComposerLifecycleStatus(
                existing.state,
                receipt.command_id,
                existing.hermes_run_id,
                locale,
              ),
            );
            const observedHermesSessionId = requireSameComposerHermesSession(
              submittedHermesSessionId,
              existing.hermes_session_id,
            );
            if (isTerminalCommandState(existing.state)) {
              setRetryAttempt(null);
              if (existing.state === "succeeded") {
                await surfaceAssistantPreview({
                  hermesSessionId: observedHermesSessionId,
                  commandId: receipt.command_id,
                  hermesRunId: existing.hermes_run_id ?? null,
                  signal: pollAbort.signal,
                  setStatusText,
                  locale,
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
            formatComposerLifecycleStatus(
              "queued",
              receipt.command_id,
              null,
              locale,
            ),
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
          const followedHermesSessionId = requireSameComposerHermesSession(
            submittedHermesSessionId,
            observed?.hermes_session_id,
          );
          const terminalState = observed?.state ?? null;
          const lifecycle = formatComposerLifecycleStatus(
            terminalState ?? "queued",
            receipt.command_id,
            observed?.hermes_run_id ?? null,
            locale,
          );
          setStatusText(
            terminalState
              ? lifecycle
              : `${lifecycle} · ${composerStillTrackingText(locale)}`,
          );

          if (terminalState === "outcome_unknown") {
            setRetryAttempt({
              attempt,
              hermesSessionId: followedHermesSessionId,
            });
          }

          if (terminalState === "succeeded") {
            setRetryAttempt(null);
            await surfaceAssistantPreview({
              hermesSessionId: followedHermesSessionId,
              commandId: receipt.command_id,
              hermesRunId: observed?.hermes_run_id ?? null,
              signal: pollAbort.signal,
              setStatusText,
              lifecyclePrefix: lifecycle,
              locale,
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
        if (
          shouldRetainComposerAttemptAfterError(error) &&
          selectedHermesSessionId
        ) {
          setRetryAttempt({
            attempt,
            hermesSessionId: selectedHermesSessionId,
          });
        } else {
          setRetryAttempt(null);
        }
        setStatusText(composerErrorMessage(error, locale));
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
      activeHermesSessionId,
      bindSession,
      setPendingUserText,
      spine,
      followState.commands,
      locale,
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

  const onStartNewSession = useCallback(async () => {
    if (!networkSubmit) {
      throw new WorkspaceClientError(
        "network submit is not enabled on this shell",
        403,
        "forbidden",
      );
    }
    pollAbortRef.current?.abort();
    pollAbortRef.current = null;
    const clientActionId =
      newSessionActionIdRef.current ?? crypto.randomUUID();
    newSessionActionIdRef.current = clientActionId;
    setNewSessionAttemptActive(true);
    setBusy(true);
    setStatusText(newSessionCreatingText);
    try {
      const { managedSession } = await startFreshManagedSession({
        clientActionId,
      });
      const hermesSessionId = requireSameComposerHermesSession(
        managedSession.hermes_session_id,
      );
      focusComposerWhenWritableRef.current = hermesSessionId;
      activateReadyManagedHermesSession({
        hermesSessionId,
        locale,
        bindHermesSession: (readySessionId) => {
          bindSession?.({ hermesSessionId: readySessionId });
        },
        navigate: (href) => router.push(href),
      });
      setPendingUserText?.(null);
      setRetryAttempt(null);
      newSessionActionIdRef.current = null;
      setNewSessionAttemptActive(false);
      setStatusText(newSessionReadyText);
    } catch (error) {
      const localized = freshManagedSessionErrorCopy(error, locale);
      setStatusText(localized);
      throw new Error(localized);
    } finally {
      setBusy(false);
    }
  }, [
    bindSession,
    locale,
    networkSubmit,
    newSessionCreatingText,
    newSessionReadyText,
    router,
    setPendingUserText,
  ]);

  const selectedSessionId = activeHermesSessionId?.trim() || null;
  const assessedState =
    sessionAssessment.sessionId === selectedSessionId
      ? sessionAssessment.state
      : "checking";
  // An empty workbench must establish one explicit, durable Session first.
  // Otherwise a first-turn durable accept followed by response loss has no
  // exact Session identity on which to offer a safe same-action retry.
  const sessionCanSubmit = assessedState === "writable";
  const baseControlsEnabled = networkSubmit && allowSubmit && !disabled;
  const retryEligible = canRetryComposerAttempt(
    retryAttempt,
    selectedSessionId,
    sessionCanSubmit,
  );
  const onRetry = useCallback(() => {
    if (
      !canRetryComposerAttempt(
        retryAttempt,
        selectedSessionId,
        sessionCanSubmit,
      )
    ) {
      setRetryAttempt(null);
      return Promise.resolve();
    }
    return submitAttempt(retryComposerAttempt(retryAttempt.attempt));
  }, [
    retryAttempt,
    selectedSessionId,
    sessionCanSubmit,
    submitAttempt,
  ]);
  const sessionStatusText =
    assessedState === "checking"
      ? sessionCheckingText
      : assessedState === "empty"
        ? emptySessionText
      : assessedState === "read_only"
        ? readOnlySessionText
        : assessedState === "unavailable"
          ? sessionValidationUnavailableText
          : null;
  const effectiveStatusText =
    newSessionAttemptActive && statusText
      ? statusText
      : sessionStatusText ?? statusText;

  return (
    <ComposerDock
      {...dockProps}
      allowSubmit={allowSubmit}
      busy={busy}
      disabled={disabled || !sessionCanSubmit}
      draftResetToken={acceptedDraftToken}
      locale={locale}
      onStartNewSession={
        baseControlsEnabled ? onStartNewSession : undefined
      }
      onSubmitPrompt={
        baseControlsEnabled && sessionCanSubmit ? onSubmitPrompt : undefined
      }
      onRetry={
        retryEligible && baseControlsEnabled ? onRetry : undefined
      }
      statusText={effectiveStatusText}
    />
  );
}
