'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ensureRunStopAttempt,
  selectStoppableHermesRuns,
  shouldRetainRunStopAttemptAfterError,
  type RunStopAttempt,
  type StoppableHermesRun,
} from "@/lib/hermes/runStopAttempt";
import {
  isTerminalCommandState,
  requestHermesRunStop,
  WorkspaceClientError,
} from "@/lib/hermes/workspaceClient";
import { Panel } from "@/components/ui/Panel";
import {
  displayId,
  LONG_ID_CLASS,
} from "@/lib/hermes/workbenchA11y";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import type { Locale } from "@/lib/locale";

export type WorkbenchRunStopPanelProps = {
  locale: Locale;
};

type StopPhase = "idle" | "pending" | "success" | "unknown" | "error";

type StopNotice = {
  phase: StopPhase;
  runId: string;
  clientActionId: string;
  message: string;
  retryable: boolean;
};

const STOP_BTN_CLASS =
  "app-touch-target inline-flex items-center justify-center rounded border border-danger/40 bg-bg-elevated px-3 font-body-sm font-semibold text-danger transition-colors hover:bg-danger/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none";

function errorMessage(error: unknown): string {
  if (error instanceof WorkspaceClientError) return error.message;
  if (error instanceof Error) return error.message;
  return "stop request failed";
}

/**
 * Web Run stop control. Eligibility comes only from exact active Hermes Run
 * command facts on the shared follow spine; no Task/Attempt refs are inferred.
 */
export function WorkbenchRunStopPanel({
  locale,
}: WorkbenchRunStopPanelProps) {
  const isZh = locale === "zh";
  const { state: follow, spine } = useWorkspaceFollow();
  const [attempt, setAttempt] = useState<RunStopAttempt | null>(null);
  const [notice, setNotice] = useState<StopNotice | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const stoppableRuns = useMemo(
    () =>
      selectStoppableHermesRuns(
        Array.isArray(follow.commands) ? follow.commands : [],
        follow.mutationEnabled === true,
      ),
    [follow.commands, follow.mutationEnabled],
  );

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, []);

  const observedTerminalState = useMemo(() => {
    if (!notice || notice.phase !== "pending") return null;
    return (
      follow.commands.find(
        (row) =>
          row.hermes_run_id === notice.runId &&
          isTerminalCommandState(row.state),
      )?.state ?? null
    );
  }, [follow.commands, notice]);

  const visibleNotice = useMemo<StopNotice | null>(() => {
    if (!notice || !observedTerminalState) return notice;
    return {
      ...notice,
      phase: "success",
      message: isZh
        ? `共享 follow spine 已观察到终态：${observedTerminalState}。`
        : `Shared follow spine observed terminal state: ${observedTerminalState}.`,
      retryable: false,
    };
  }, [isZh, notice, observedTerminalState]);
  const retryEligible =
    visibleNotice?.retryable === true &&
    stoppableRuns.some((run) => run.runId === visibleNotice.runId);

  const runAttempt = useCallback(
    async (nextAttempt: RunStopAttempt) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setNotice({
        phase: "pending",
        runId: nextAttempt.runId,
        clientActionId: nextAttempt.clientActionId,
        message: isZh ? "正在提交停止请求…" : "Submitting stop request…",
        retryable: false,
      });
      try {
        const receipt = await requestHermesRunStop({
          runId: nextAttempt.runId,
          clientActionId: nextAttempt.clientActionId,
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;

        if (receipt.status === "accepted") {
          setNotice({
            phase: "success",
            runId: nextAttempt.runId,
            clientActionId: nextAttempt.clientActionId,
            message: isZh
              ? "停止已确认；正在通过共享 follow spine 刷新终态。"
              : "Stop confirmed; refreshing terminal state through the shared follow spine.",
            retryable: false,
          });
        } else if (receipt.status === "reconciling") {
          setNotice({
            phase: "pending",
            runId: nextAttempt.runId,
            clientActionId: nextAttempt.clientActionId,
            message: isZh
              ? "停止请求已接受，正在对账；尚未宣称终态。"
              : "Stop request accepted and reconciling; no terminal state claimed yet.",
            retryable: false,
          });
        } else if (receipt.status === "outcome_unknown") {
          setNotice({
            phase: "unknown",
            runId: nextAttempt.runId,
            clientActionId: nextAttempt.clientActionId,
            message: isZh
              ? "停止结果未知。可使用同一操作 ID 重试。"
              : "Stop outcome unknown. Retry with the same action ID.",
            retryable: true,
          });
        } else {
          setNotice({
            phase: "error",
            runId: nextAttempt.runId,
            clientActionId: nextAttempt.clientActionId,
            message:
              receipt.reason_code ||
              (isZh
                ? `停止请求失败：${receipt.status}`
                : `Stop request failed: ${receipt.status}`),
            retryable: false,
          });
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        const retryable = shouldRetainRunStopAttemptAfterError(error);
        if (!retryable) {
          setAttempt(null);
        }
        setNotice({
          phase: "error",
          runId: nextAttempt.runId,
          clientActionId: nextAttempt.clientActionId,
          message: errorMessage(error),
          retryable,
        });
      } finally {
        if (!controller.signal.aborted && spine) {
          try {
            await spine.resyncNow();
          } catch {
            // The shared spine owns transport error display and poll fallback.
          }
        }
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      }
    },
    [isZh, spine],
  );

  const requestStop = useCallback(
    (run: StoppableHermesRun) => {
      if (visibleNotice?.phase === "pending") return;
      const nextAttempt = ensureRunStopAttempt(attempt, run.runId);
      setAttempt(nextAttempt);
      void runAttempt(nextAttempt);
    },
    [attempt, runAttempt, visibleNotice?.phase],
  );

  const retryStop = useCallback(() => {
    if (
      !attempt ||
      visibleNotice?.phase === "pending" ||
      !retryEligible
    ) {
      return;
    }
    void runAttempt(attempt);
  }, [attempt, retryEligible, runAttempt, visibleNotice?.phase]);

  const spineReady =
    follow.snapshotCursor != null || follow.transport !== "idle";
  const busy = visibleNotice?.phase === "pending";

  return (
    <Panel
      count={stoppableRuns.length}
      data-hermes-run-stop-control=""
      data-hermes-run-stop-mutation={
        follow.mutationEnabled === true ? "enabled" : "disabled"
      }
      title={isZh ? "运行控制" : "Run control"}
    >
      <div className="min-w-0 space-y-2" id="hermes-run-stop-body">
        <p className="font-body-sm text-text-secondary break-words">
          {isZh
            ? "仅对共享 follow spine 中 exact hermes_run_id 且状态为 delivered / outcome_unknown 的非终态运行显示停止按钮。只提交 run_ref；不会伪造 Task / Attempt / job 引用。"
            : "Stop appears only for a nonterminal delivered / outcome_unknown command with an exact hermes_run_id on the shared follow spine. Only run_ref is authoritative; Task, Attempt, and job refs are never invented."}
        </p>

        {visibleNotice ? (
          <div
            aria-live="polite"
            className={`font-body-sm break-words ${
              visibleNotice.phase === "error" ||
              visibleNotice.phase === "unknown"
                ? "text-warning"
                : visibleNotice.phase === "success"
                  ? "text-accent-success"
                  : "text-text-secondary"
            }`}
            data-hermes-run-stop-status={visibleNotice.phase}
            role={visibleNotice.phase === "error" ? "alert" : "status"}
          >
            <p>{visibleNotice.message}</p>
            <p className="mt-1 font-data-mono text-[11px]">
              run {displayId(visibleNotice.runId, { head: 16, tail: 6 })} ·
              action{" "}
              {displayId(visibleNotice.clientActionId, {
                head: 12,
                tail: 6,
              })}
            </p>
            {retryEligible ? (
              <button
                className={`${STOP_BTN_CLASS} mt-2`}
                data-hermes-run-stop-retry
                disabled={busy}
                onClick={retryStop}
                type="button"
              >
                {isZh ? "使用同一操作 ID 重试" : "Retry same stop request"}
              </button>
            ) : null}
          </div>
        ) : null}

        {!spineReady ? (
          <p className="font-body-sm text-text-secondary">
            {isZh ? "follow spine 尚未就绪…" : "Follow spine not ready yet…"}
          </p>
        ) : null}

        {spineReady && follow.mutationEnabled !== true ? (
          <p
            className="font-body-sm text-text-secondary"
            data-hermes-run-stop-disabled
          >
            {isZh
              ? "运行停止写权限当前关闭。"
              : "Run stop mutation is currently disabled."}
          </p>
        ) : null}

        {spineReady &&
        follow.mutationEnabled === true &&
        stoppableRuns.length === 0 ? (
          <p
            className="font-body-sm text-text-secondary"
            data-hermes-run-stop-empty
          >
            {isZh
              ? "当前没有可停止的非终态 Hermes 运行。"
              : "No eligible nonterminal Hermes Run is currently stoppable."}
          </p>
        ) : null}

        {stoppableRuns.length ? (
          <ul className="divide-y divide-border-subtle border-t border-border-subtle">
            {stoppableRuns.map((run) => (
              <li
                className="flex min-w-0 flex-wrap items-center justify-between gap-3 py-2"
                data-hermes-run-stop-row
                data-hermes-run-id={run.runId}
                key={run.runId}
              >
                <div className="min-w-0">
                  <p className="font-body-sm font-semibold text-text-primary">
                    {run.state}
                  </p>
                  <p className={LONG_ID_CLASS} title={run.runId}>
                    {displayId(run.runId, { head: 18, tail: 8 })}
                  </p>
                </div>
                <button
                  aria-label={
                    isZh
                      ? `停止 Hermes 运行 ${run.runId}`
                      : `Stop Hermes Run ${run.runId}`
                  }
                  className={STOP_BTN_CLASS}
                  data-hermes-run-stop-button
                  disabled={
                    busy ||
                    (visibleNotice?.phase === "success" &&
                      visibleNotice.runId === run.runId)
                  }
                  onClick={() => requestStop(run)}
                  type="button"
                >
                  {busy && visibleNotice?.runId === run.runId
                    ? isZh
                      ? "停止中…"
                      : "Stopping…"
                    : isZh
                      ? "停止"
                      : "Stop"}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Panel>
  );
}
