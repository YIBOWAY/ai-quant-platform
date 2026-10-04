"use client";

import { useRef, useState } from "react";
import { WorkbenchRunStopPanel } from "../run-control/WorkbenchRunStopPanel";
import { WorkbenchCommandActivityPanel } from "../activity/WorkbenchCommandActivityPanel";
import { WorkbenchTypedResultsPanel } from "../results/WorkbenchTypedResultsPanel";
import { WorkbenchAuthorityProjectionPanel } from "../authority/WorkbenchAuthorityProjectionPanel";
import { decideHermesCommandApproval, type WorkspaceApprovalProjection } from "@/lib/hermes/workspaceClient";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import type { Locale } from "@/lib/locale";
import { useHermesDesk } from "./HermesDeskContext";

type Attempt = { row: WorkspaceApprovalProjection; decision: "allow_once" | "deny"; id: string };

function canDecideCommandApproval(row: WorkspaceApprovalProjection) {
  // The command-approval projection owns these rows; kind is optional and
  // provider-specific, not a candidate Gate discriminator.
  return (row.status || row.expected_status) === "pending" && Boolean(row.approval_id && row.run_id)
    && /^[0-9a-f]{64}$/.test(row.digest || "") && Number.isFinite(Date.parse(row.expires_at || ""))
    && Date.parse(row.expires_at!) > Date.now();
}

function PendingToolRequests({ locale }: { locale: Locale }) {
  const zh = locale === "zh";
  const { state, spine } = useWorkspaceFollow();
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [receipt, setReceipt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [submitted, setSubmitted] = useState<Record<string, true>>({});
  const rows = state.approvals ?? [];
  async function decide(next: Attempt) {
    if (inFlight.current || state.mutationEnabled !== true) return;
    inFlight.current = true; setBusy(true); setAttempt(next); setError(null); setUncertain(false);
    try {
      const result = await decideHermesCommandApproval({ approvalId: next.row.approval_id,
        runId: next.row.run_id!, commandDigest: next.row.digest!, expectedExpiresAt: next.row.expires_at!,
        decision: next.decision, clientActionId: next.id });
      if (result.client_action_id !== next.id) throw new Error("Decision receipt identity mismatch");
      if (result.status === "accepted" || result.status === "reconciling") {
        setSubmitted(old => ({ ...old, [next.row.approval_id]: true }));
        setReceipt(`${next.decision}:${result.status}:${result.client_action_id}`);
      } else {
        setError(zh ? "尚未确认操作结果，请重新读取记录。" : "The outcome is not confirmed. Re-read the records.");
        setUncertain(result.status === "outcome_unknown");
      }
    } catch {
      setError(zh ? "未能确认是否已收到决定。请勿发起不同的决定。" : "Delivery could not be confirmed. Do not submit a different decision.");
      setUncertain(true);
    } finally {
      try { await spine?.resyncNow(); } catch { /* Shared follow state exposes read failures. */ }
      inFlight.current = false; setBusy(false);
    }
  }
  return <div className="space-y-3" data-hermes-command-approvals>
    <p className="font-body-sm text-text-secondary">{zh ? "这里只确认某一次工具执行，不会批准策略上线或打开实盘交易。" : "Decisions apply to one tool execution, not strategy activation or live trading."}</p>
    {!rows.length ? <p className="font-body-sm text-text-secondary">{state.snapshotCursor == null ? (zh ? "尚未读到运行记录。" : "Run records have not loaded.") : (zh ? "暂无待确认事项。" : "No pending requests.")}</p> : null}
    {rows.map(row => {
      const decidable = state.mutationEnabled === true && !submitted[row.approval_id] && canDecideCommandApproval(row);
      return <section className="border-t border-border-subtle py-3" key={row.approval_id}
        data-hermes-approval-row data-hermes-approval-id={row.approval_id} data-hermes-approval-decidable={decidable ? "true" : "false"}>
        <p className="font-body-sm text-text-primary" data-hermes-approval-status>{row.status || row.expected_status}{row.decision ? ` · ${row.decision}` : ""}</p>
        <p className="break-all font-body-sm text-text-secondary">{zh ? "执行编号" : "Run"}: {row.run_id || "—"}</p>
        <p className="break-all font-body-sm text-text-secondary">{zh ? "请求编号" : "Request"}: {row.approval_id}</p>
        <p className="font-body-sm text-text-secondary">{zh ? "有效期至" : "Expires"}: {row.expires_at || "—"}</p>
        {decidable && !uncertain ? <div className="mt-3 flex flex-wrap gap-2">{(["allow_once", "deny"] as const).map(decision => <button
          className="app-touch-target rounded border border-border-subtle bg-bg-elevated px-3 font-body-sm text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-primary"
          key={decision} type="button" disabled={busy}
          data-hermes-approval-allow-once={decision === "allow_once" ? "" : undefined}
          data-hermes-approval-deny={decision === "deny" ? "" : undefined}
          onClick={() => void decide({ row: { ...row }, decision, id: crypto.randomUUID() })}>
          {decision === "allow_once" ? (zh ? "仅允许这一次" : "Allow this once") : (zh ? "拒绝这一次" : "Deny this request")}
        </button>)}</div> : null}
      </section>;
    })}
    {error ? <p className="font-body-sm text-warning" role="status">{error}</p> : null}
    {uncertain && attempt ? <button className="app-touch-target rounded border border-border-subtle px-3 text-text-primary" type="button" disabled={busy}
      onClick={() => void decide(attempt)}>{zh ? "重试同一次决定" : "Retry the same decision"}</button> : null}
    {receipt ? <p className="break-all font-data-mono text-xs text-text-secondary" data-hermes-approvals-receipt>{receipt}</p> : null}
  </div>;
}

export function HermesDeskRunControls({ locale }: { locale: Locale }) {
  const zh = locale === "zh";
  const { chatOpen } = useHermesDesk();
  const { state } = useWorkspaceFollow();
  const pending = (state.approvals ?? []).filter(row => canDecideCommandApproval(row)).length;
  const panels = [
    { key: "approvals", label: zh ? "待确认事项" : "Pending tool requests", body: <PendingToolRequests locale={locale} /> },
    { key: "runs", label: zh ? "正在运行与停止" : "Running work & stop", body: <WorkbenchRunStopPanel locale={locale} /> },
    { key: "activity", label: zh ? "消息处理记录" : "Message activity", body: <WorkbenchCommandActivityPanel locale={locale} /> },
    { key: "results", label: zh ? "研究结果" : "Research results", body: <WorkbenchTypedResultsPanel locale={locale} /> },
    { key: "authority", label: zh ? "关联记录" : "Linked records", body: <WorkbenchAuthorityProjectionPanel locale={locale} /> },
  ];
  return <section className="mt-6 border-t border-border-subtle pt-4" aria-label={zh ? "运行详情" : "Run details"} data-hermes-run-controls>
    <h3 className="font-headline-sm text-text-primary">{zh ? "运行详情" : "Run details"}</h3>
    {pending > 0 ? <p className="mt-2 font-body-sm text-warning" role="status">{zh ? `${pending} 项工具执行正在等待你确认。` : `${pending} tool request(s) need your decision.`}</p> : null}
    {panels.map(panel => <details className="dp-diagnostics" data-hermes-run-panel={panel.key} key={panel.key}>
      <summary className="app-touch-target">{panel.label}</summary>{chatOpen ? panel.body : <p className="py-3 font-body-sm text-text-secondary">{zh ? "当前只读，未连接执行控制，无法判断是否还有运行或待确认事项。已保存的研究结果仍可在下方查看。" : "Read-only mode does not connect execution controls. Active work and pending requests cannot be determined here; saved research results remain available below."}</p>}
    </details>)}
  </section>;
}
