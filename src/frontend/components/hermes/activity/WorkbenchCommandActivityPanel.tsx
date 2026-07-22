'use client';

import { useEffect, useState } from "react";

import {
  commandStateLabel,
  isActiveCommandState,
  shortId,
  sortCommandsNewestFirst,
} from "@/lib/hermes/commandActivity";
import {
  fetchWorkspaceSnapshot,
  type WorkspaceCommandProjection,
} from "@/lib/hermes/workspaceClient";
import type { Locale } from "@/lib/locale";

export type WorkbenchCommandActivityPanelProps = {
  locale: Locale;
  /** Soft refresh interval while mounted (ms). 0 = snapshot once. */
  pollMs?: number;
};

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; commands: WorkspaceCommandProjection[]; observedAt?: string }
  | { kind: "error"; detail: string; prior?: WorkspaceCommandProjection[] };

const DEFAULT_POLL_MS = 8_000;
const MAX_ROWS = 12;

/**
 * L4a-Task-Drawer-M1: read-only command activity from workspace snapshot.
 * Task/Attempt authority rows are still empty in snapshot; this surfaces the
 * live ledger commands[] projection (conversation_turn lifecycle) without SSE
 * or mutation. Not the /hermes/tasks artifacts page.
 */
export function WorkbenchCommandActivityPanel({
  locale,
  pollMs = DEFAULT_POLL_MS,
}: WorkbenchCommandActivityPanelProps) {
  const isZh = locale === "zh";
  const [open, setOpen] = useState(true);
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    let tickAc: AbortController | null = null;
    let gen = 0;

    const run = async () => {
      tickAc?.abort();
      const ac = new AbortController();
      tickAc = ac;
      const myGen = ++gen;
      try {
        const snap = await fetchWorkspaceSnapshot(undefined, ac.signal);
        if (cancelled || ac.signal.aborted || myGen !== gen) return;
        const commands = sortCommandsNewestFirst(snap.commands).slice(0, MAX_ROWS);
        setState({
          kind: "ready",
          commands,
          observedAt: snap.observed_at,
        });
      } catch (error) {
        if (cancelled || ac.signal.aborted || myGen !== gen) return;
        setState((prev) => ({
          kind: "error",
          detail: error instanceof Error ? error.message : "snapshot failed",
          prior:
            prev.kind === "ready"
              ? prev.commands
              : prev.kind === "error"
                ? prev.prior
                : undefined,
        }));
      }
    };

    void run();
    if (!pollMs || pollMs <= 0) {
      return () => {
        cancelled = true;
        tickAc?.abort();
      };
    }
    const timer = window.setInterval(() => {
      void run();
    }, pollMs);
    return () => {
      cancelled = true;
      tickAc?.abort();
      window.clearInterval(timer);
    };
  }, [pollMs]);

  const commands =
    state.kind === "ready"
      ? state.commands
      : state.kind === "error" && state.prior
        ? state.prior
        : [];
  const activeCount = commands.filter((c) => isActiveCommandState(c.state)).length;

  return (
    <section
      aria-label={isZh ? "命令活动" : "Command activity"}
      className="space-y-2"
      data-hermes-command-activity
      data-hermes-task-drawer="l4a-m1"
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <h2 className="font-headline-sm text-text-primary">
            {isZh ? "活动" : "Activity"}
          </h2>
          <p className="font-body-sm text-text-secondary" data-hermes-activity-count>
            {state.kind === "loading" && !commands.length
              ? isZh
                ? "加载中…"
                : "Loading…"
              : isZh
                ? `${commands.length} 条命令${activeCount ? ` · ${activeCount} 进行中` : ""}`
                : `${commands.length} command${commands.length === 1 ? "" : "s"}${
                    activeCount ? ` · ${activeCount} active` : ""
                  }`}
          </p>
        </div>
        <button
          aria-controls="hermes-command-activity-body"
          aria-expanded={open}
          className="app-touch-target rounded border border-border-subtle px-2 py-0.5 font-body-sm text-text-primary hover:bg-bg-surface"
          data-hermes-activity-toggle
          onClick={() => setOpen((v) => !v)}
          type="button"
        >
          {open ? (isZh ? "收起" : "Hide") : isZh ? "展开" : "Show"}
        </button>
      </header>

      {open ? (
        <div
          className="rounded-lg border border-border-subtle bg-bg-surface"
          data-hermes-command-activity-body
          id="hermes-command-activity-body"
        >
          <p className="border-b border-border-subtle px-3 py-2 font-body-sm text-text-secondary">
            {isZh
              ? "只读：workspace snapshot 的 ledger commands（conversation_turn 生命周期）。Task/Attempt 权威投影仍空；≠ 研究任务写入，≠ SSE。"
              : "Read-only: ledger commands from workspace snapshot (conversation_turn lifecycle). Task/Attempt authority rows still empty; not research-task write, not SSE."}
          </p>

          {state.kind === "error" ? (
            <p
              className="px-3 py-2 font-body-sm text-warning"
              data-hermes-activity-error
            >
              {isZh
                ? `刷新失败${state.prior ? "，仍显示上一份" : ""}：${state.detail}`
                : `Refresh failed${state.prior ? "; showing last list" : ""}: ${state.detail}`}
            </p>
          ) : null}

          {!commands.length && state.kind !== "loading" ? (
            <p
              className="px-3 py-4 font-body-sm text-text-secondary"
              data-hermes-activity-empty
            >
              {isZh
                ? "暂无 workspace 命令。发送一条本地对话后会出现 queued → delivered。"
                : "No workspace commands yet. Send a local turn to see queued → delivered."}
            </p>
          ) : null}

          {commands.length ? (
            <ol className="divide-y divide-border-subtle" data-hermes-activity-list>
              {commands.map((row) => (
                <li
                  className="px-3 py-2"
                  data-hermes-activity-row
                  data-hermes-command-id={row.command_id}
                  data-hermes-command-state={row.state}
                  key={row.command_id}
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <p className="font-body-sm font-semibold text-text-primary">
                      <span data-hermes-activity-state>
                        {commandStateLabel(row.state, isZh)}
                      </span>
                      <span className="mx-1 text-text-secondary">·</span>
                      <span className="font-data-mono text-xs text-text-secondary">
                        {row.kind}
                      </span>
                    </p>
                    <p className="font-data-mono text-[11px] text-text-secondary">
                      {row.updated_at || row.created_at || ""}
                    </p>
                  </div>
                  <dl className="mt-1 grid gap-0.5 font-data-mono text-[11px] text-text-secondary sm:grid-cols-2">
                    <div>
                      <dt className="inline text-text-secondary">cmd </dt>
                      <dd className="inline" title={row.command_id}>
                        {shortId(row.command_id, 10)}
                      </dd>
                    </div>
                    {row.hermes_session_id ? (
                      <div>
                        <dt className="inline">session </dt>
                        <dd className="inline" title={row.hermes_session_id}>
                          {shortId(row.hermes_session_id, 12)}
                        </dd>
                      </div>
                    ) : null}
                    {row.hermes_run_id ? (
                      <div>
                        <dt className="inline">run </dt>
                        <dd className="inline" title={row.hermes_run_id}>
                          {shortId(row.hermes_run_id, 12)}
                        </dd>
                      </div>
                    ) : null}
                    {typeof row.attempt_count === "number" && row.attempt_count > 0 ? (
                      <div>
                        <dt className="inline">
                          {isZh ? "尝试 " : "attempts "}
                        </dt>
                        <dd className="inline">{row.attempt_count}</dd>
                      </div>
                    ) : null}
                    {row.last_error_code ? (
                      <div className="sm:col-span-2 text-warning">
                        <dt className="inline">err </dt>
                        <dd className="inline">{row.last_error_code}</dd>
                      </div>
                    ) : null}
                  </dl>
                </li>
              ))}
            </ol>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
