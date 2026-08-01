'use client';

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";

import { Panel } from "@/components/ui/Panel";
import {
  COLLAPSE_TOGGLE_CLASS,
  displayId,
  LONG_ID_CLASS,
} from "@/lib/hermes/workbenchA11y";
import {
  confirmFormulaSource,
  fetchGate1SourceEvidence,
  preparePromotionReview,
  reviewCandidateCAS,
  type Gate1SourceEvidence,
  type WorkspaceActionReceipt,
  type WorkspaceGateProjection,
  WorkspaceClientError,
} from "@/lib/hermes/workspaceClient";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import { hermesRouteHref } from "@/lib/hermes/routes";
import type { Locale } from "@/lib/locale";

export type WorkbenchGateSurfacesPanelProps = {
  locale: Locale;
};

type Gate1ReviewState = {
  loading: boolean;
  acknowledged: boolean;
  evidence?: Gate1SourceEvidence;
  error?: string;
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
    const confirmation = row.gate1_confirmation_id || "";
    return (
      Boolean(cand) &&
      /^[0-9a-f]{64}$/.test(dig) &&
      /^gate1-[0-9a-f]{32}$/.test(confirmation)
    );
  }
  if (kind === "gate3") {
    const dig = row.expected_digest || "";
    const cand = row.candidate_id || row.candidate_ref || "";
    const receipt =
      row.final_backtest_receipt_id || row.final_backtest_receipt_ref || "";
    const base = row.base_commit || "";
    const confirmation = row.gate1_confirmation_id || "";
    return (
      Boolean(cand) &&
      Boolean(receipt) &&
      /^[0-9a-f]{64}$/.test(dig) &&
      /^[0-9a-f]{40}$/.test(base) &&
      /^gate1-[0-9a-f]{32}$/.test(confirmation)
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
  const [gate1Reviews, setGate1Reviews] = useState<
    Record<string, Gate1ReviewState>
  >({});

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

  const onLoadGate1Source = useCallback(
    async (row: WorkspaceGateProjection) => {
      const digest = row.reviewed_source_sha256 || "";
      if (
        (row.gate_kind || "").toLowerCase() !== "gate1" ||
        !/^[0-9a-f]{64}$/.test(digest)
      ) {
        return;
      }
      setGate1Reviews((previous) => ({
        ...previous,
        [row.gate_id]: { loading: true, acknowledged: false },
      }));
      try {
        const evidence = await fetchGate1SourceEvidence({
          gateId: row.gate_id,
          reviewedSourceSha256: digest,
        });
        setGate1Reviews((previous) => ({
          ...previous,
          [row.gate_id]: {
            loading: false,
            acknowledged: false,
            evidence,
          },
        }));
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Gate 1 source review failed";
        setGate1Reviews((previous) => ({
          ...previous,
          [row.gate_id]: {
            loading: false,
            acknowledged: false,
            error: message,
          },
        }));
      }
    },
    [],
  );

  const onAct = useCallback(
    async (row: WorkspaceGateProjection) => {
      if (!canActGate(row) || !mutationOn || busyId) return;
      setBusyId(row.gate_id);
      setLastError(null);
      setLastReceipt(null);
      const kind = (row.gate_kind || "").toLowerCase();
      const note = (noteDraft[row.gate_id] || "").trim();
      const gate1Review = gate1Reviews[row.gate_id];
      if (
        kind === "gate1" &&
        (!gate1Review?.acknowledged ||
          gate1Review.evidence?.client_verified_sha256 !==
            row.reviewed_source_sha256)
      ) {
        setLastError(
          isZh
            ? "请先在网页中加载、核对并确认精确源码字节"
            : "Load, verify, and acknowledge the exact source bytes first",
        );
        setBusyId(null);
        return;
      }
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
            expectedGateId: row.gate_id,
          });
        } else if (kind === "gate2") {
          receipt = await reviewCandidateCAS({
            candidateId: row.candidate_id || row.candidate_ref || "",
            expectedDigest: row.expected_digest || "",
            note,
            expectedGateId: row.gate_id,
            expectedGate1ConfirmationId: row.gate1_confirmation_id || "",
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
            expectedGateId: row.gate_id,
            expectedGate1ConfirmationId: row.gate1_confirmation_id || "",
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
    [busyId, gate1Reviews, isZh, mutationOn, noteDraft],
  );

  return (
    <Panel
      count={gates.length}
      data-hermes-gate-surfaces=""
      data-hermes-gate-observe="v7e-m1"
      data-hermes-gate-projector="v7e-m1"
      data-hermes-gate-act="v7e-m1"
      data-hermes-gate-1-health={gate1Health}
      data-hermes-gate-2-health={gate2Health}
      data-hermes-gate-3-health={gate3Health}
      data-hermes-gate-mutation={mutationOn ? "enabled" : "disabled"}
      headerExtra={
        <div className="flex items-center gap-2">
          <span
            className="font-body-sm text-text-secondary"
            data-hermes-gates-count
          >
            {mutationOn
              ? isZh
                ? "可提交"
                : "actionable"
              : isZh
                ? "只读"
                : "read-only"}
          </span>
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
        </div>
      }
      title={isZh ? "领域门控" : "Domain gates"}
    >
      <div
        className="min-w-0"
        data-hermes-gate-surfaces-body
        id="hermes-gate-surfaces-body"
      >
        <p className="font-body-sm text-text-secondary break-words">
          {isZh
            ? "Domain Gate 1/2/3：与 command-approval 分离。Gate 1/2 保持同一计划 Attempt；Gate 3 必须进入 ContinueResearch 的新 Attempt/Run，且仅 prepare（不 Git commit）。无 always-allow。"
            : "Domain Gate 1/2/3: separate from command-approval. Gates 1/2 stay on the plan Attempt; Gate 3 must use a new ContinueResearch Attempt/Run and is prepare-only (no Git commit). No always-allow."}
        </p>

        {lastError ? (
          <p
            className="mt-2 font-body-sm text-danger"
            data-hermes-gates-error
            role="alert"
          >
            {lastError}
          </p>
        ) : null}
        {lastReceipt ? (
          <p
            className="mt-2 font-data-mono text-[11px] text-text-secondary break-all"
            data-hermes-gates-receipt
          >
            {lastReceipt}
          </p>
        ) : null}

        {showEmpty ? (
          <p
            className="mt-2 font-body-sm text-text-secondary break-words"
            data-hermes-gates-empty
          >
            {isZh
              ? "当前无待处理领域门控。空列表诚实——不会把 command-approval 或 Task 伪装成 Gate。"
              : "No pending domain gates. Empty is honest — command-approval and Tasks are never dressed as Gates."}
          </p>
        ) : open ? (
          <ul
            className="mt-2 divide-y divide-border-subtle border-t border-border-subtle"
            data-hermes-gates-list
          >
            {gates.map((row) => {
                const kind = (row.gate_kind || "").toLowerCase();
                const actionable = canActGate(row) && mutationOn;
                const needsNote = gateRequiresHumanNote(row);
                const noteReady =
                  !needsNote ||
                  Boolean((noteDraft[row.gate_id] || "").trim());
                const gate1Review = gate1Reviews[row.gate_id];
                const gate1ReviewReady =
                  kind !== "gate1" ||
                  Boolean(
                    gate1Review?.acknowledged &&
                      gate1Review.evidence?.client_verified_sha256 ===
                        row.reviewed_source_sha256,
                  );
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
                    {row.task_version ? (
                      <p
                        className="font-data-mono text-[11px] text-text-secondary break-all"
                        data-hermes-gate-task-version
                      >
                        {isZh
                          ? "此 Gate 绑定的 Task version"
                          : "Gate-bound task version"}
                        : {row.task_version}
                      </p>
                    ) : null}
                    {row.attempt_ref ? (
                      <p className="font-data-mono text-[11px] text-text-secondary break-all">
                        attempt: {row.attempt_ref}
                      </p>
                    ) : null}
                    {row.hqa_run_ref ? (
                      <p className="font-data-mono text-[11px] text-text-secondary break-all">
                        HQA run: {row.hqa_run_ref}
                      </p>
                    ) : null}
                    {row.hermes_session_id ? (
                      <p className="font-data-mono text-[11px] text-text-secondary break-all">
                        Hermes session: {row.hermes_session_id}
                      </p>
                    ) : null}
                    {row.hermes_run_id ? (
                      <p className="font-data-mono text-[11px] text-text-secondary break-all">
                        Hermes run: {row.hermes_run_id}
                      </p>
                    ) : null}
                    {row.command_ref || row.command_id ? (
                      <p className="font-data-mono text-[11px] text-text-secondary break-all">
                        command: {row.command_ref || row.command_id}
                      </p>
                    ) : null}
                    {row.candidate_ref || row.candidate_id ? (
                      <p className="font-data-mono text-[11px] text-text-secondary break-all">
                        candidate: {row.candidate_ref || row.candidate_id}
                      </p>
                    ) : null}
                    {kind === "gate1" && row.source_file_ref ? (
                      <p className="font-data-mono text-[11px] text-text-secondary break-all">
                        source file: {row.source_file_ref}
                      </p>
                    ) : null}
                    {kind === "gate1" && row.universe ? (
                      <p className="font-data-mono text-[11px] text-text-secondary break-all">
                        universe: {row.universe}
                      </p>
                    ) : null}
                    {row.reviewed_source_sha256 ? (
                      <p
                        className="font-data-mono text-[11px] text-text-secondary break-all"
                        data-hermes-gate-source-sha256
                      >
                        source SHA-256: {row.reviewed_source_sha256}
                      </p>
                    ) : null}
                    {row.gate1_confirmation_id ? (
                      <p
                        className="font-data-mono text-[11px] text-text-secondary break-all"
                        data-hermes-gate1-confirmation-id
                      >
                        Gate 1 confirmation: {row.gate1_confirmation_id}
                      </p>
                    ) : null}
                    {row.expected_digest ? (
                      <p
                        className="font-data-mono text-[11px] text-text-secondary break-all"
                        data-hermes-gate-candidate-digest
                      >
                        candidate digest: {row.expected_digest}
                      </p>
                    ) : null}
                    {kind === "gate1" && isPending(row) ? (
                      <div
                        className="space-y-2 rounded border border-warning/40 bg-warning/5 p-2"
                        data-hermes-gate-review-guidance="gate1"
                      >
                        <p className="font-body-sm text-text-secondary">
                          {isZh
                            ? "确认前必须在此处加载精确源码。浏览器会独立重算完整 SHA-256；只填写备注不构成审阅证据。"
                            : "Load the exact source here before confirming. The browser independently recomputes the full SHA-256; a note alone is not review evidence."}
                        </p>
                        <button
                          className={ACT_BTN_CLASS}
                          data-hermes-gate-source-load
                          disabled={gate1Review?.loading === true}
                          onClick={() => void onLoadGate1Source(row)}
                          type="button"
                        >
                          {gate1Review?.loading
                            ? isZh
                              ? "加载并校验中…"
                              : "Loading and verifying…"
                            : gate1Review?.evidence
                              ? isZh
                                ? "重新加载精确源码"
                                : "Reload exact source"
                              : isZh
                                ? "加载精确源码"
                                : "Load exact source"}
                        </button>
                        {gate1Review?.error ? (
                          <p
                            className="font-body-sm text-danger"
                            data-hermes-gate-source-error
                            role="alert"
                          >
                            {gate1Review.error}
                          </p>
                        ) : null}
                        {gate1Review?.evidence ? (
                          <div
                            className="space-y-2"
                            data-hermes-gate-source-evidence
                          >
                            <p
                              className="font-data-mono text-[11px] text-success break-all"
                              data-hermes-gate-source-client-sha256
                            >
                              browser verified SHA-256:{" "}
                              {gate1Review.evidence.client_verified_sha256}
                            </p>
                            <pre
                              aria-label={
                                isZh
                                  ? "Gate 1 精确源码"
                                  : "Gate 1 exact source"
                              }
                              className="max-h-96 overflow-auto rounded border border-border-subtle bg-bg-elevated p-3 text-left font-data-mono text-xs text-text-primary whitespace-pre"
                              data-hermes-gate-source-bytes
                              tabIndex={0}
                            >
                              {gate1Review.evidence.source_utf8}
                            </pre>
                            <label className="flex items-start gap-2 font-body-sm text-text-primary">
                              <input
                                checked={gate1Review.acknowledged}
                                data-hermes-gate-source-acknowledge
                                onChange={(event) =>
                                  setGate1Reviews((previous) => ({
                                    ...previous,
                                    [row.gate_id]: {
                                      ...gate1Review,
                                      acknowledged: event.target.checked,
                                    },
                                  }))
                                }
                                type="checkbox"
                              />
                              <span>
                                {isZh
                                  ? "我已阅读上方精确源码，并核对浏览器计算的完整 SHA-256。"
                                  : "I reviewed the exact source above and checked the browser-computed full SHA-256."}
                              </span>
                            </label>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                    {kind === "gate2" &&
                    isPending(row) &&
                    (row.candidate_id || row.candidate_ref) ? (
                      <p
                        className="rounded border border-warning/40 bg-warning/5 p-2 font-body-sm text-text-secondary"
                        data-hermes-gate-review-guidance="gate2"
                      >
                        {isZh
                          ? "批准前请在只读证据页检查候选源码、审计记录和完整 digest；证据页不会自动提交 Gate 2。"
                          : "Before approving, inspect candidate source, audit records, and the full digest in the read-only evidence page; that page never submits Gate 2 automatically."}{" "}
                        <Link
                          className="app-touch-target inline-flex items-center font-semibold text-info underline underline-offset-2"
                          href={hermesRouteHref("approvals", locale, {
                            candidate:
                              row.candidate_id ||
                              row.candidate_ref?.replace(/^candidate:/, ""),
                          })}
                          prefetch={false}
                          rel="noreferrer"
                          target="_blank"
                        >
                          {isZh ? "打开候选证据" : "Open candidate evidence"}
                        </Link>
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
                    {kind === "gate3" &&
                    (row.promotion_id ||
                      row.worktree ||
                      row.patch ||
                      row.manifest) ? (
                      <div
                        className="space-y-1 rounded border border-warning/40 bg-warning/5 p-2"
                        data-hermes-gate-review-materials
                      >
                        <p className="font-body-sm text-text-primary">
                          {row.status === "completed"
                            ? isZh
                              ? "论文流程已完成：人工 commit、Task/Attempt terminal 与 Gate 3 passed 均已绑定"
                              : "Paper flow completed: human commit, terminal Task/Attempt, and passed Gate 3 are bound"
                            : row.human_git_commit_required
                            ? isZh
                              ? "晋升材料已准备；仍需人工审阅 diff 并 Git commit"
                              : "Promotion materials are ready; human diff review and Git commit are still required"
                            : isZh
                              ? "晋升审阅材料"
                              : "Promotion review materials"}
                        </p>
                        {row.promotion_id ? (
                          <p className="font-data-mono text-[11px] text-text-secondary break-all">
                            promotion: {row.promotion_id}
                          </p>
                        ) : null}
                        {row.worktree ? (
                          <p className="font-data-mono text-[11px] text-text-secondary break-all">
                            worktree: {row.worktree}
                          </p>
                        ) : null}
                        {row.patch ? (
                          <p className="font-data-mono text-[11px] text-text-secondary break-all">
                            patch: {row.patch}
                          </p>
                        ) : null}
                        {row.manifest ? (
                          <p className="font-data-mono text-[11px] text-text-secondary break-all">
                            manifest: {row.manifest}
                          </p>
                        ) : null}
                        <p className="font-body-sm text-text-secondary">
                          {row.reviewed_commit
                            ? isZh
                              ? `已审阅 commit：${row.reviewed_commit}`
                              : `Reviewed commit: ${row.reviewed_commit}`
                            : isZh
                              ? "尚无 reviewed_commit；prepared 不等于 Gate 3 完成。"
                              : "No reviewed_commit yet; prepared is not Gate 3 completion."}
                        </p>
                        {row.provider_evidence_ref ? (
                          <p className="font-data-mono text-[11px] text-text-secondary break-all">
                            provider evidence: {row.provider_evidence_ref}
                          </p>
                        ) : null}
                        {row.workflow_audit_ref ? (
                          <p className="font-data-mono text-[11px] text-text-secondary break-all">
                            workflow audit: {row.workflow_audit_ref}
                          </p>
                        ) : null}
                        {row.hqa_completion_receipt_ref ? (
                          <p className="font-data-mono text-[11px] text-text-secondary break-all">
                            completion receipt: {row.hqa_completion_receipt_ref}
                          </p>
                        ) : null}
                      </div>
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
                          disabled={
                            busyId === row.gate_id ||
                            !noteReady ||
                            !gate1ReviewReady
                          }
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
        ) : null}
      </div>
    </Panel>
  );
}
