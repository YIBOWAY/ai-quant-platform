'use client';

import { useMemo, useState } from "react";

import {
  COLLAPSE_TOGGLE_CLASS,
  displayId,
  LONG_ID_CLASS,
} from "@/lib/hermes/workbenchA11y";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import type { Locale } from "@/lib/locale";

export type WorkbenchCommandApprovalsPanelProps = {
  locale: Locale;
};

/**
 * L5a-Hermes-Approval-Observe-M1: read-only Hermes command-approval challenges
 * from the shared follow spine snapshot. Empty is honest — no Gate 1/2/3, no
 * candidate approval write, no inventing rows. ≠ /hermes/approvals candidate page.
 */
export function WorkbenchCommandApprovalsPanel({
  locale,
}: WorkbenchCommandApprovalsPanelProps) {
  const isZh = locale === "zh";
  const [open, setOpen] = useState(true);
  const { state: follow } = useWorkspaceFollow();

  const approvals = useMemo(
    () => (Array.isArray(follow.approvals) ? follow.approvals : []),
    [follow.approvals],
  );
  const health = follow.snapshotCursor != null || follow.transport !== "idle";
  const commandApprovalHealth =
    follow.authorityHealth?.command_approval ?? "unavailable";
  // Empty list is honest; health is surfaced on data-hermes-command-approval-health.
  const showEmptyApprovals = health && approvals.length === 0;

  return (
    <section
      aria-label={isZh ? "命令审批观察" : "Command approval observe"}
      className="space-y-2"
      data-hermes-command-approvals
      data-hermes-approval-observe="l5a-m1"
      data-hermes-command-approval-health={commandApprovalHealth}
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <h2 className="font-headline-sm text-text-primary">
            {isZh ? "审批" : "Approvals"}
          </h2>
          <p
            className="font-body-sm text-text-secondary"
            data-hermes-approvals-count
          >
            {isZh
              ? `${approvals.length} 条挑战 · 只读`
              : `${approvals.length} challenge${
                  approvals.length === 1 ? "" : "s"
                } · read-only`}
          </p>
        </div>
        <button
          aria-controls="hermes-command-approvals-body"
          aria-expanded={open}
          className={COLLAPSE_TOGGLE_CLASS}
          data-hermes-approvals-toggle
          onClick={() => setOpen((v) => !v)}
          type="button"
        >
          {open ? (isZh ? "收起" : "Hide") : isZh ? "展开" : "Show"}
        </button>
      </header>

      {open ? (
        <div
          className="min-w-0 rounded-lg border border-border-subtle bg-bg-surface"
          data-hermes-command-approvals-body
          id="hermes-command-approvals-body"
        >
          <p className="border-b border-border-subtle px-3 py-2 font-body-sm text-text-secondary break-words">
            {isZh
              ? "只读：Hermes command-approval 挑战（approval_id + run_id + digest + expires_at）。≠ Gate 1/2/3、≠ 候选审批页；无 allow/deny 写端。投影未接时列表诚实为空。"
              : "Read-only: Hermes command-approval challenges (approval_id + run_id + digest + expires_at). Not Gate 1/2/3, not candidate approvals page; no allow/deny write. Empty is honest until durable projector lands."}
          </p>

          {showEmptyApprovals ? (
            <p
              className="px-3 py-4 font-body-sm text-text-secondary break-words"
              data-hermes-approvals-empty
            >
              {isZh
                ? "当前无 pending command-approval 挑战。durable projector 接上后会出现；不会伪造行。"
                : "No pending command-approval challenges. Rows appear when the durable projector lands; none are invented."}
            </p>
          ) : null}

          {!health ? (
            <p className="px-3 py-4 font-body-sm text-text-secondary">
              {isZh ? "follow spine 尚未就绪…" : "Follow spine not ready yet…"}
            </p>
          ) : null}

          {approvals.length ? (
            <ol
              aria-live="polite"
              aria-relevant="additions text"
              className="divide-y divide-border-subtle"
              data-hermes-approvals-list
            >
              {approvals.map((row) => (
                <li
                  className="min-w-0 px-3 py-2"
                  data-hermes-approval-row
                  data-hermes-approval-id={row.approval_id}
                  key={row.approval_id}
                >
                  <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
                    <p className="min-w-0 font-body-sm font-semibold text-text-primary">
                      <span data-hermes-approval-status>
                        {row.status || row.expected_status || "pending"}
                      </span>
                      {row.kind ? (
                        <>
                          <span className="mx-1 text-text-secondary">·</span>
                          <span className="break-all font-data-mono text-xs text-text-secondary">
                            {row.kind}
                          </span>
                        </>
                      ) : null}
                    </p>
                    <p className="shrink-0 font-data-mono text-[11px] text-text-secondary">
                      {row.expires_at || ""}
                    </p>
                  </div>
                  <dl className="mt-1 grid min-w-0 gap-0.5 sm:grid-cols-2">
                    <div className="min-w-0">
                      <dt className="inline font-data-mono text-[11px] text-text-secondary">
                        approval{" "}
                      </dt>
                      <dd
                        className={`inline ${LONG_ID_CLASS}`}
                        title={row.approval_id}
                      >
                        {displayId(row.approval_id, { head: 12, tail: 6 })}
                      </dd>
                    </div>
                    {row.run_id ? (
                      <div className="min-w-0">
                        <dt className="inline font-data-mono text-[11px] text-text-secondary">
                          run{" "}
                        </dt>
                        <dd
                          className={`inline ${LONG_ID_CLASS}`}
                          title={row.run_id}
                        >
                          {displayId(row.run_id, { head: 12, tail: 6 })}
                        </dd>
                      </div>
                    ) : null}
                    {row.command_id ? (
                      <div className="min-w-0">
                        <dt className="inline font-data-mono text-[11px] text-text-secondary">
                          cmd{" "}
                        </dt>
                        <dd
                          className={`inline ${LONG_ID_CLASS}`}
                          title={row.command_id}
                        >
                          {displayId(row.command_id, { head: 10, tail: 6 })}
                        </dd>
                      </div>
                    ) : null}
                    {row.digest ? (
                      <div className="min-w-0 sm:col-span-2">
                        <dt className="inline font-data-mono text-[11px] text-text-secondary">
                          digest{" "}
                        </dt>
                        <dd
                          className={`inline ${LONG_ID_CLASS}`}
                          title={row.digest}
                        >
                          {displayId(row.digest, { head: 16, tail: 6 })}
                        </dd>
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
