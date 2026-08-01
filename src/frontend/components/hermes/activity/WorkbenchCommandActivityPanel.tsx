'use client';

import { useMemo, useState } from "react";

import { Panel } from "@/components/ui/Panel";
import {
  commandStateLabel,
  isActiveCommandState,
  sortCommandsNewestFirst,
} from "@/lib/hermes/commandActivity";
import {
  COLLAPSE_TOGGLE_CLASS,
  displayId,
  LONG_ID_CLASS,
} from "@/lib/hermes/workbenchA11y";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import type { Locale } from "@/lib/locale";

export type WorkbenchCommandActivityPanelProps = {
  locale: Locale;
  /**
   * @deprecated L4b: refresh is driven by shared follow spine (SSE/poll).
   * Kept for call-site compatibility; ignored.
   */
  pollMs?: number;
};

const MAX_ROWS = 12;

/**
 * L4a Activity + L4b follow spine consumer.
 * Read-only command lifecycle from shared workspace follow (SSE preferred,
 * poll fallback). Task/Attempt authority rows still empty — not /hermes/tasks.
 */
export function WorkbenchCommandActivityPanel({
  locale,
}: WorkbenchCommandActivityPanelProps) {
  const isZh = locale === "zh";
  const [open, setOpen] = useState(true);
  const { state: follow } = useWorkspaceFollow();

  const commands = useMemo(
    () => sortCommandsNewestFirst(follow.commands).slice(0, MAX_ROWS),
    [follow.commands],
  );
  const activeCount = commands.filter((c) => isActiveCommandState(c.state)).length;
  const loading = follow.transport === "idle" && !commands.length && !follow.error;

  return (
    <Panel
      count={commands.length}
      data-hermes-command-activity=""
      data-hermes-task-drawer="l4a-m1"
      empty={
        isZh
          ? "暂无 workspace 命令。发送一条本地对话后会出现 queued → delivered。"
          : "No workspace commands yet. Send a local turn to see queued → delivered."
      }
      error={
        follow.error
          ? isZh
            ? `观察失败${commands.length ? "，仍显示上一份" : ""}：${follow.error}`
            : `Observe failed${commands.length ? "; showing last list" : ""}: ${follow.error}`
          : null
      }
      headerExtra={
        <div className="flex items-center gap-2">
          <span className="font-body-sm text-text-secondary" data-hermes-activity-count>
            {loading
              ? isZh
                ? "加载中…"
                : "Loading…"
              : activeCount
                ? isZh
                  ? `${activeCount} 进行中`
                  : `${activeCount} active`
                : ""}
          </span>
          <button
            aria-controls="hermes-command-activity-body"
            aria-expanded={open}
            className={COLLAPSE_TOGGLE_CLASS}
            data-hermes-activity-toggle
            onClick={() => setOpen((v) => !v)}
            type="button"
          >
            {open ? (isZh ? "收起" : "Hide") : isZh ? "展开" : "Show"}
          </button>
        </div>
      }
      isEmpty={!commands.length && !loading}
      title={isZh ? "活动" : "Activity"}
    >
      <div data-hermes-command-activity-body id="hermes-command-activity-body">
        <p className="font-body-sm text-text-secondary break-words">
          {isZh
            ? "只读：共享 follow spine（SSE 优先 / poll 回退）的 ledger commands。Task/Attempt 权威仍空；≠ 研究任务写入；无 assistant 正文。"
            : "Read-only: ledger commands via shared follow spine (SSE preferred, poll fallback). Task/Attempt authority still empty; not research-task write; no assistant bodies."}
        </p>

        {!open && commands.length ? (
          <p className="mt-2 font-body-sm text-text-secondary">
            {isZh ? `${commands.length} 项已折叠` : `${commands.length} hidden`}
          </p>
        ) : null}

        {open && commands.length ? (
          <ol
            aria-live="polite"
            aria-relevant="additions text"
            className="mt-2 divide-y divide-border-subtle border-t border-border-subtle"
            data-hermes-activity-list
          >
            {commands.map((row) => (
              <li
                className="min-w-0 py-2"
                data-hermes-activity-row
                data-hermes-command-id={row.command_id}
                data-hermes-command-state={row.state}
                key={row.command_id}
              >
                <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
                  <p className="min-w-0 font-body-sm font-semibold text-text-primary">
                    <span data-hermes-activity-state>
                      {commandStateLabel(row.state, isZh)}
                    </span>
                    <span className="mx-1 text-text-secondary">·</span>
                    <span className="break-all font-data-mono text-xs font-normal text-text-secondary">
                      {row.kind}
                    </span>
                  </p>
                  <p className="shrink-0 font-data-mono text-[11px] text-text-secondary">
                    {row.updated_at || row.created_at || ""}
                  </p>
                </div>
                <dl className="mt-1 grid min-w-0 gap-0.5 sm:grid-cols-2">
                  <div className="min-w-0 sm:col-span-2">
                    <dt className="inline text-text-secondary font-data-mono text-[11px]">
                      cmd{" "}
                    </dt>
                    <dd
                      className={`inline ${LONG_ID_CLASS}`}
                      title={row.command_id}
                    >
                      {displayId(row.command_id, { head: 14, tail: 10 })}
                    </dd>
                  </div>
                  {row.hermes_session_id ? (
                    <div className="min-w-0 sm:col-span-2">
                      <dt className="inline font-data-mono text-[11px] text-text-secondary">
                        session{" "}
                      </dt>
                      <dd
                        className={`inline ${LONG_ID_CLASS}`}
                        title={row.hermes_session_id}
                      >
                        {displayId(row.hermes_session_id, {
                          head: 14,
                          tail: 10,
                        })}
                      </dd>
                    </div>
                  ) : null}
                  {row.hermes_run_id ? (
                    <div className="min-w-0 sm:col-span-2">
                      <dt className="inline font-data-mono text-[11px] text-text-secondary">
                        run{" "}
                      </dt>
                      <dd
                        className={`inline ${LONG_ID_CLASS}`}
                        title={row.hermes_run_id}
                      >
                        {displayId(row.hermes_run_id, { head: 14, tail: 10 })}
                      </dd>
                    </div>
                  ) : null}
                  {typeof row.attempt_count === "number" &&
                  row.attempt_count > 0 ? (
                    <div>
                      <dt className="inline font-data-mono text-[11px] text-text-secondary">
                        {isZh ? "尝试 " : "attempts "}
                      </dt>
                      <dd className="inline font-data-mono text-[11px] text-text-secondary">
                        {row.attempt_count}
                      </dd>
                    </div>
                  ) : null}
                  {row.last_error_code ? (
                    <div className="min-w-0 sm:col-span-2 text-warning">
                      <dt className="inline font-data-mono text-[11px]">
                        err{" "}
                      </dt>
                      <dd
                        className={`inline break-all font-data-mono text-[11px]`}
                      >
                        {row.last_error_code}
                      </dd>
                    </div>
                  ) : null}
                </dl>
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </Panel>
  );
}
