'use client';

import { useCallback, useMemo, useState } from "react";

import {
  COLLAPSE_TOGGLE_CLASS,
  displayId,
  LONG_ID_CLASS,
} from "@/lib/hermes/workbenchA11y";
import {
  confirmFormulaSource,
  preparePromotionReview,
  reviewCandidateCAS,
  type WorkspaceActionReceipt,
  type WorkspaceGateProjection,
  WorkspaceClientError,
} from "@/lib/hermes/workspaceClient";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import type { Locale } from "@/lib/locale";

export type WorkbenchGateSurfacesPanelProps = {
  locale: Locale;
};

const ACT_BTN_CLASS =
  "app-touch-target inline-flex items-center justify-center rounded border border-border-subtle bg-bg-elevated px-3 font-body-sm text-text-primary transition-colors hover:bg-bg-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-primary disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none";

function isPending(row: WorkspaceGateProjection): boolean {
  const status = (row.status || row.expected_status || "pending").toLowerCase();
  return status === "pending";
}

/** Gate 1/2 require a human-typed nonempty note; Gate 3 does not. */
export function gateRequiresHumanNote(row: WorkspaceGateProjection): boolean {
  const kind = (row.gate_kind || "").toLowerCase();
  return kind === "gate1" || kind === "gate2";
}

/** Gate controls require full typed CAS binding — never reuse approval canDecide. */
export function canActGate(row: WorkspaceGateProjection): boolean {
  if (!isPending(row)) return false;
  if (!row.gate_id) return false;
  const kind = (row.gate_kind || "").toLowerCase();
  if (kind === "gate1") {
    const sha = row.reviewed_source_sha256 || "";
    const task = row.task_id || row.task_ref || "";
    return Boolean(task) && /^[0-9a-f]{64}$/.test(sha);
  }
  if (kind === "gate2") {
    const dig = row.expected_digest || "";
    const cand = row.candidate_id || row.candidate_ref || "";
    return Boolean(cand) && /^[0-9a-f]{64}$/.test(dig);
  }
  if (kind === "gate3") {
    const dig = row.expected_digest || "";
    const cand = row.candidate_id || row.candidate_ref || "";
    const receipt =
      row.final_backtest_receipt_id || row.final_backtest_receipt_ref || "";
    const base = row.base_commit || "";
    return (
      Boolean(cand) &&
      Boolean(receipt) &&
      /^[0-9a-f]{64}$/.test(dig) &&
      /^[0-9a-f]{40}$/.test(base)
    );
  }
  return false;
}

/**
 * Optimistic hide only while still pending; terminal decided/prepared facts stay.
 */
export function filterGatesForPanel(
  rows: WorkspaceGateProjection[],
  consumedIds: Record<string, true>,
): WorkspaceGateProjection[] {
  return rows.filter((row) => {
    if (!consumedIds[row.gate_id]) return true;
    return !canActGate(row);
  });
}

function kindLabel(kind: string, isZh: boolean): string {
  switch (kind) {
    case "gate1":
      return isZh ? "Gate 1 · 公式源确认" : "Gate 1 · formula source";
    case "gate2":
      return isZh ? "Gate 2 · 候选 CAS 审阅" : "Gate 2 · candidate CAS";
    case "gate3":
      return isZh ? "Gate 3 · 晋升审阅准备" : "Gate 3 · promotion prepare";
    default:
      return kind || "gate";
  }
}

/**
 * V7e-Gate-Surfaces-M1: Domain Gate 1/2/3 observe + typed act.
 * Separate from command-approval. Empty is honest. No always-allow.
 * Gate 3 prepare only — web never Git-commits.
 * Markers: data-hermes-gate-*=v7e-m1 (never v7d approval markers).
 */
export function WorkbenchGateSurfacesPanel({
  locale,
}: WorkbenchGateSurfacesPanelProps) {
  const isZh = locale === "zh";
  const [open, setOpen] = useState(true);
  const { state: follow } = useWorkspaceFollow();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastReceipt, setLastReceipt] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState<Record<string, string>>({});
  const [consumedIds, setConsumedIds] = useState<Record<string, true>>({});

  const gates = useMemo(() => {
    const raw = Array.isArray(follow.gates) ? follow.gates : [];
    return filterGatesForPanel(raw, consumedIds);
  }, [follow.gates, consumedIds]);
  const health = follow.snapshotCursor != null || follow.transport !== "idle";
  const gate1Health = follow.authorityHealth?.gate_1 ?? "unavailable";
  const gate2Health = follow.authorityHealth?.gate_2 ?? "unavailable";
  const gate3Health = follow.authorityHealth?.gate_3 ?? "unavailable";
  const mutationOn = follow.mutationEnabled === true;
  const showEmpty = health && gates.length === 0;

  const onAct = useCallback(
    async (row: WorkspaceGateProjection) => {
      if (!canActGate(row) || !mutationOn || busyId) return;
      setBusyId(row.gate_id);
      setLastError(null);
      setLastReceipt(null);
      const kind = (row.gate_kind || "").toLowerCase();
      const note = (noteDraft[row.gate_id] || "").trim();
      if (gateRequiresHumanNote(row) && !note) {
        setLastError(
          isZh ? "确认备注必填" : "Confirmation note is required",
        );
        setBusyId(null);
        return;
      }
      try {
        let receipt: WorkspaceActionReceipt;
        if (kind === "gate1") {
          receipt = await confirmFormulaSource({
            taskId: row.task_id || row.task_ref || "",
            reviewedSourceSha256: row.reviewed_source_sha256 || "",
            confirmationNote: note,
          });
        } else if (kind === "gate2") {
          receipt = await reviewCandidateCAS({
            candidateId: row.candidate_id || row.candidate_ref || "",
            expectedDigest: row.expected_digest || "",
            note,
          });
        } else if (kind === "gate3") {
          receipt = await preparePromotionReview({
            candidateId: row.candidate_id || row.candidate_ref || "",
            expectedDigest: row.expected_digest || "",
            finalBacktestReceiptId:
              row.final_backtest_receipt_id ||
              row.final_backtest_receipt_ref ||
              "",
            baseCommit: row.base_commit || "",
          });
        } else {
          setLastError("unknown gate_kind");
          return;
        }
        if (receipt.status === "accepted" || receipt.status === "reconciling") {
          setConsumedIds((prev) => ({ ...prev, [row.gate_id]: true }));
          setLastReceipt(
            `${kind}:${receipt.status}:${receipt.client_action_id}`,
          );
        } else {
          setLastError(
            receipt.reason_code || `gate status=${receipt.status}`,
          );
        }
      } catch (err) {
        const msg =
          err instanceof WorkspaceClientError
            ? err.message
            : err instanceof Error
              ? err.message
              : "gate act failed";
        setLastError(msg);
      } finally {
        setBusyId(null);
      }
    },
    [busyId, isZh, mutationOn, noteDraft],
  );

  return (
    <section
      aria-label={isZh ? "领域门控" : "Domain gates"}
      className="space-y-2"
      data-hermes-gate-surfaces
      data-hermes-gate-observe="v7e-m1"
      data-hermes-gate-projector="v7e-m1"
      data-hermes-gate-act="v7e-m1"
      data-hermes-gate-1-health={gate1Health}
      data-hermes-gate-2-health={gate2Health}
      data-hermes-gate-3-health={gate3Health}
      data-hermes-gate-mutation={mutationOn ? "enabled" : "disabled"}
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <h2 className="font-headline-sm text-text-primary">
            {isZh ? "领域门控" : "Domain gates"}
          </h2>
          <p className="font-body-sm text-text-secondary" data-hermes-gates-count>
            {isZh
              ? `${gates.length} 条`
              : `${gates.length} item${gates.length === 1 ? "" : "s"}`}
            {mutationOn
              ? isZh
                ? " · 可提交"
                : " · actionable"
              : isZh
                ? " · 只读"
                : " · read-only"}
          </p>
        </div>
        <button
          aria-controls="hermes-gate-surfaces-body"
          aria-expanded={open}
          className={COLLAPSE_TOGGLE_CLASS}
          data-hermes-gates-toggle
          onClick={() => setOpen((v) => !v)}
          type="button"
        >
          {open ? (isZh ? "收起" : "Hide") : isZh ? "展开" : "Show"}
        </button>
      </header>

      {open ? (
        <div
          className="min-w-0 rounded-lg border border-border-subtle bg-bg-surface"
          data-hermes-gate-surfaces-body
          id="hermes-gate-surfaces-body"
        >
          <p className="border-b border-border-subtle px-3 py-2 font-body-sm text-text-secondary break-words">
            {isZh
              ? "Domain Gate 1/2/3：与 command-approval 分离。Gate 1 绑定 task+source SHA-256+note；Gate 2 绑定 candidate+digest+pending；Gate 3 仅 prepare（不 Git commit）。无 always-allow。空列表诚实。"
              : "Domain Gate 1/2/3: separate from command-approval. Gate 1 binds task+source SHA-256+note; Gate 2 binds candidate+digest+pending; Gate 3 prepare-only (no Git commit). No always-allow. Empty is honest."}
          </p>

          {lastError ? (
            <p
              className="border-b border-border-subtle px-3 py-2 font-body-sm text-danger"
              data-hermes-gates-error
              role="alert"
            >
              {lastError}
            </p>
          ) : null}
          {lastReceipt ? (
            <p
              className="border-b border-border-subtle px-3 py-2 font-data-mono text-[11px] text-text-secondary break-all"
              data-hermes-gates-receipt
            >
              {lastReceipt}
            </p>
          ) : null}

          {showEmpty ? (
            <p
              className="px-3 py-4 font-body-sm text-text-secondary break-words"
              data-hermes-gates-empty
            >
              {isZh
                ? "当前无待处理领域门控。空列表诚实——不会把 command-approval 或 Task 伪装成 Gate。"
                : "No pending domain gates. Empty is honest — command-approval and Tasks are never dressed as Gates."}
            </p>
          ) : (
            <ul className="divide-y divide-border-subtle" data-hermes-gates-list>
              {gates.map((row) => {
                const actionable = canActGate(row) && mutationOn;
                const kind = (row.gate_kind || "").toLowerCase();
                const needsNote = gateRequiresHumanNote(row);
                const noteReady = !needsNote || Boolean((noteDraft[row.gate_id] || "").trim());
                return (
                  <li
                    className="space-y-2 px-3 py-3"
                    data-hermes-gate-row
                    data-hermes-gate-id={row.gate_id}
                    data-hermes-gate-kind={kind}
                    data-hermes-gate-status={row.status || "pending"}
                    key={row.gate_id}
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <p className="font-body-sm text-text-primary">
                        {kindLabel(kind, isZh)}
                      </p>
                      <p
                        className="font-data-mono text-[11px] text-text-secondary"
                        data-hermes-gate-status-label
                      >
                        {row.status || "pending"}
                      </p>
                    </div>
                    <p className={`${LONG_ID_CLASS} break-all`} title={row.gate_id}>
                      {displayId(row.gate_id)}
                    </p>
                    {row.task_ref || row.task_id ? (
                      <p className="font-data-mono text-[11px] text-text-secondary break-all">
                        task: {row.task_ref || row.task_id}
                      </p>
                    ) : null}
                    {row.candidate_ref || row.candidate_id ? (
                      <p className="font-data-mono text-[11px] text-text-secondary break-all">
                        candidate: {row.candidate_ref || row.candidate_id}
                      </p>
                    ) : null}
                    {row.reviewed_source_sha256 ? (
                      <p className="font-data-mono text-[11px] text-text-secondary break-all">
                        source: {displayId(row.reviewed_source_sha256)}
                      </p>
                    ) : null}
                    {row.expected_digest ? (
                      <p className="font-data-mono text-[11px] text-text-secondary break-all">
                        digest: {displayId(row.expected_digest)}
                      </p>
                    ) : null}
                    {row.base_commit ? (
                      <p className="font-data-mono text-[11px] text-text-secondary break-all">
                        base: {row.base_commit}
                      </p>
                    ) : null}
                    {row.note ? (
                      <p className="font-body-sm text-text-secondary break-words">
                        {row.note}
                      </p>
                    ) : null}
                    {row.decided_at ? (
                      <p className="font-data-mono text-[11px] text-text-secondary">
                        decided: {row.decided_at}
                      </p>
                    ) : null}

                    {actionable ? (
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                        {needsNote ? (
                          <label className="flex min-w-0 flex-1 flex-col gap-1">
                            <span className="font-body-sm text-text-secondary">
                              {isZh ? "确认备注（必填）" : "Confirmation note (required)"}
                            </span>
                            <input
                              className="min-h-[2.5rem] w-full rounded border border-border-subtle bg-bg-elevated px-2 font-body-sm text-text-primary"
                              data-hermes-gate-note
                              onChange={(e) =>
                                setNoteDraft((prev) => ({
                                  ...prev,
                                  [row.gate_id]: e.target.value,
                                }))
                              }
                              type="text"
                              value={noteDraft[row.gate_id] || ""}
                            />
                          </label>
                        ) : null}
                        <button
                          className={ACT_BTN_CLASS}
                          data-hermes-gate-act-btn
                          disabled={busyId === row.gate_id || !noteReady}
                          onClick={() => void onAct(row)}
                          type="button"
                        >
                          {busyId === row.gate_id
                            ? isZh
                              ? "提交中…"
                              : "Submitting…"
                            : kind === "gate3"
                              ? isZh
                                ? "准备晋升审阅"
                                : "Prepare review"
                              : isZh
                                ? "确认"
                                : "Confirm"}
                        </button>
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}
