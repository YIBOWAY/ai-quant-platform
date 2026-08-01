'use client';

import { useCallback, useMemo, useState } from "react";

import { Panel } from "@/components/ui/Panel";
import {
  COLLAPSE_TOGGLE_CLASS,
  displayId,
  LONG_ID_CLASS,
} from "@/lib/hermes/workbenchA11y";
import {
  decideHermesCommandApproval,
  type WorkspaceActionReceipt,
  type WorkspaceApprovalProjection,
  WorkspaceClientError,
} from "@/lib/hermes/workspaceClient";
import {
  canDecideCommandApproval as canDecideCommandApprovalImpl,
  filterApprovalsForPanel as filterApprovalsForPanelImpl,
} from "@/lib/hermes/commandApprovalPredicates";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import type { Locale } from "@/lib/locale";

export type WorkbenchCommandApprovalsPanelProps = {
  locale: Locale;
};

const DECIDE_BTN_CLASS =
  "app-touch-target inline-flex items-center justify-center rounded border border-border-subtle bg-bg-elevated px-3 font-body-sm text-text-primary transition-colors hover:bg-bg-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-primary disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none";

/**
 * V7a decide gate + V7d projection filter now live in
 * lib/hermes/commandApprovalPredicates so the dock badge can share them.
 * Re-exported here: this module stays their public import path.
 */
export {
  canDecideCommandApproval,
  filterApprovalsForPanel,
} from "@/lib/hermes/commandApprovalPredicates";

const canDecide = canDecideCommandApprovalImpl;

/**
 * L5a observe + V7a decide: Hermes command-approval challenges from the shared
 * follow spine. Empty is honest. Controls appear only for real pending rows
 * with full CAS binding. allow_once|deny only — no always-allow.
 * ≠ Gate 1/2/3, ≠ /hermes/approvals candidate page.
 */
export function WorkbenchCommandApprovalsPanel({
  locale,
}: WorkbenchCommandApprovalsPanelProps) {
  const isZh = locale === "zh";
  const [open, setOpen] = useState(true);
  const { state: follow } = useWorkspaceFollow();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastReceipt, setLastReceipt] = useState<string | null>(null);
  // Optimistic hide of still-pending rows after accepted decide; V7d keeps terminal decided facts visible.
  const [consumedIds, setConsumedIds] = useState<Record<string, true>>({});

  const approvals = useMemo(() => {
    const raw = Array.isArray(follow.approvals) ? follow.approvals : [];
    return filterApprovalsForPanelImpl(raw, consumedIds);
  }, [follow.approvals, consumedIds]);
  const health = follow.snapshotCursor != null || follow.transport !== "idle";
  const commandApprovalHealth =
    follow.authorityHealth?.command_approval ?? "unavailable";
  const mutationOn = follow.mutationEnabled === true;
  const showEmptyApprovals = health && approvals.length === 0;

  const onDecide = useCallback(
    async (row: WorkspaceApprovalProjection, decision: "allow_once" | "deny") => {
      if (!canDecide(row) || !mutationOn) return;
      if (busyId) return;
      setBusyId(row.approval_id);
      setLastError(null);
      setLastReceipt(null);
      try {
        const receipt: WorkspaceActionReceipt = await decideHermesCommandApproval({
          approvalId: row.approval_id,
          runId: row.run_id || "",
          commandDigest: row.digest || "",
          expectedExpiresAt: row.expires_at || "",
          decision,
        });
        if (receipt.status === "accepted" || receipt.status === "reconciling") {
          setConsumedIds((prev) => ({ ...prev, [row.approval_id]: true }));
          setLastReceipt(
            `${decision}:${receipt.status}:${receipt.client_action_id}`,
          );
        } else {
          setLastError(
            receipt.reason_code ||
              `decision status=${receipt.status}`,
          );
        }
      } catch (err) {
        const msg =
          err instanceof WorkspaceClientError
            ? err.message
            : err instanceof Error
              ? err.message
              : "decision failed";
        setLastError(msg);
      } finally {
        setBusyId(null);
      }
    },
    [busyId, mutationOn],
  );

  return (
    <Panel
      count={approvals.length}
      data-hermes-command-approvals=""
      data-hermes-approval-observe="l5a-m1"
      data-hermes-approval-projector="v7d-m1"
      data-hermes-approval-decide="v7a-m1"
      data-hermes-command-approval-health={commandApprovalHealth}
      data-hermes-approval-mutation={mutationOn ? "enabled" : "disabled"}
      empty={
        isZh
          ? "当前无 command-approval 投影行（pending/decided）。不会伪造行。"
          : "No command-approval projection rows (pending/decided). None are invented."
      }
      error={lastError}
      headerExtra={
        <div className="flex items-center gap-2">
          <span
            className="font-body-sm text-text-secondary"
            data-hermes-approvals-count
          >
            {mutationOn ? "allow_once/deny" : isZh ? "只读" : "read-only"}
          </span>
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
        </div>
      }
      isEmpty={showEmptyApprovals}
      title={isZh ? "审批" : "Approvals"}
    >
      <div
        className="min-w-0"
        data-hermes-command-approvals-body
        id="hermes-command-approvals-body"
      >
        <p className="font-body-sm text-text-secondary break-words">
          {isZh
            ? "Hermes command-approval：exact CAS（approval_id + run_id + digest + expires_at）。仅 allow_once / deny；无 always-allow。≠ Gate 1/2/3、≠ 候选审批页。空列表诚实。"
            : "Hermes command-approval: exact CAS (approval_id + run_id + digest + expires_at). allow_once / deny only; no always-allow. Not Gate 1/2/3, not candidate approvals. Empty is honest."}
        </p>

        {lastReceipt ? (
          <p
            className="mt-2 font-data-mono text-[11px] text-text-secondary break-all"
            data-hermes-approvals-receipt
          >
            {lastReceipt}
          </p>
        ) : null}

        {!health ? (
          <p className="mt-2 font-body-sm text-text-secondary">
            {isZh ? "follow spine 尚未就绪…" : "Follow spine not ready yet…"}
          </p>
        ) : null}

        {open && approvals.length ? (
          <ol
            aria-live="polite"
            aria-relevant="additions text"
            className="mt-2 divide-y divide-border-subtle border-t border-border-subtle"
            data-hermes-approvals-list
          >
            {approvals.map((row) => {
              const decidable = mutationOn && canDecide(row);
              const busy = busyId === row.approval_id;
              return (
                <li
                  className="min-w-0 py-2"
                  data-hermes-approval-row
                  data-hermes-approval-id={row.approval_id}
                  data-hermes-approval-decidable={decidable ? "true" : "false"}
                  key={row.approval_id}
                >
                  <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
                    <p className="min-w-0 font-body-sm font-semibold text-text-primary">
                      <span data-hermes-approval-status>
                        {row.status || row.expected_status || "pending"}
                        {row.decision ? ` · ${row.decision}` : ""}
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
                  {decidable ? (
                    <div
                      className="mt-2 flex flex-wrap gap-2"
                      data-hermes-approval-actions
                    >
                      <button
                        aria-label={
                          isZh
                            ? `允许一次 ${row.approval_id}`
                            : `Allow once ${row.approval_id}`
                        }
                        className={DECIDE_BTN_CLASS}
                        data-hermes-approval-allow-once
                        disabled={busy || busyId != null}
                        onClick={() => void onDecide(row, "allow_once")}
                        type="button"
                      >
                        {busy
                          ? isZh
                            ? "提交中…"
                            : "Submitting…"
                          : isZh
                            ? "允许一次"
                            : "Allow once"}
                      </button>
                      <button
                        aria-label={
                          isZh
                            ? `拒绝 ${row.approval_id}`
                            : `Deny ${row.approval_id}`
                        }
                        className={DECIDE_BTN_CLASS}
                        data-hermes-approval-deny
                        disabled={busy || busyId != null}
                        onClick={() => void onDecide(row, "deny")}
                        type="button"
                      >
                        {isZh ? "拒绝" : "Deny"}
                      </button>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        ) : null}
      </div>
    </Panel>
  );
}
