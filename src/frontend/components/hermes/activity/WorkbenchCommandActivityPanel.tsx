'use client';

import { useMemo, useState } from "react";

import {
  commandStateLabel,
  isActiveCommandState,
  shortId,
  sortCommandsNewestFirst,
} from "@/lib/hermes/commandActivity";
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
  const transportLabel =
    follow.transport === "sse"
      ? isZh
        ? "SSE"
        : "SSE"
      : follow.transport === "poll"
        ? isZh
          ? "轮询"
          : "poll"
        : isZh
          ? "空闲"
          : "idle";

  return (
    <section
      aria-label={isZh ? "命令活动" : "Command activity"}
      className="space-y-2"
      data-hermes-command-activity
      data-hermes-task-drawer="l4a-m1"
      data-hermes-follow-transport={follow.transport}
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <h2 className="font-headline-sm text-text-primary">
            {isZh ? "活动" : "Activity"}
          </h2>
          <p className="font-body-sm text-text-secondary" data-hermes-activity-count>
            {loading
              ? isZh
                ? "加载中…"
                : "Loading…"
              : isZh
                ? `${commands.length} 条命令${activeCount ? ` · ${activeCount} 进行中` : ""} · ${transportLabel}`
                : `${commands.length} command${commands.length === 1 ? "" : "s"}${
                    activeCount ? ` · ${activeCount} active` : ""
                  } · ${transportLabel}`}
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
              ? "只读：共享 follow spine（SSE 优先 / poll 回退）的 ledger commands。Task/Attempt 权威仍空；≠ 研究任务写入；无 assistant 正文。"
              : "Read-only: ledger commands via shared follow spine (SSE preferred, poll fallback). Task/Attempt authority still empty; not research-task write; no assistant bodies."}
          </p>

          {follow.error ? (
            <p
              className="px-3 py-2 font-body-sm text-warning"
              data-hermes-activity-error
            >
              {isZh
                ? `观察失败${commands.length ? "，仍显示上一份" : ""}：${follow.error}`
                : `Observe failed${commands.length ? "; showing last list" : ""}: ${follow.error}`}
            </p>
          ) : null}

          {!commands.length && !loading ? (
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
