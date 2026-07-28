'use client';

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import {
  AlertTriangle,
  CircleOff,
  Scale,
  ShieldAlert,
  WifiOff,
} from "lucide-react";
import {
  canDecideCommandApproval,
  filterApprovalsForPanel,
} from "@/components/hermes/approvals/WorkbenchCommandApprovalsPanel";
import {
  formatDateTime,
  humanizeReasonCode,
} from "@/components/hermes/artifacts/formatters";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { hermesRouteHref } from "@/lib/hermes/routes";
import type { HermesAttentionItem } from "@/lib/hermes/types";
import {
  decideHermesCommandApproval,
  type WorkspaceApprovalProjection,
  WorkspaceClientError,
} from "@/lib/hermes/workspaceClient";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import { localizePath, type Locale } from "@/lib/locale";

export type TodayAttentionProps = {
  items: HermesAttentionItem[];
  locale: Locale;
};

const TAG_BASE =
  "inline-flex items-center rounded border px-1.5 py-px font-body-sm text-[10.5px] leading-4";
const TAG_WARN = `${TAG_BASE} border-warning/40 bg-warning/10 text-warning`;
const TAG_INFO = `${TAG_BASE} border-info/30 bg-info/10 text-info`;

const ACTION_BTN =
  "app-touch-target inline-flex items-center justify-center rounded-lg border px-3 font-body-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:opacity-50";
const ACTION_PRIMARY = `${ACTION_BTN} border-info/40 bg-info/10 text-info hover:bg-info/20`;
const ACTION_GHOST = `${ACTION_BTN} border-border-subtle text-text-secondary hover:bg-bg-surface-muted hover:text-text-primary`;

function attentionIcon(kind: HermesAttentionItem["kind"]) {
  const cls = "shrink-0 text-text-secondary";
  if (kind === "approval") return <Scale aria-hidden className={cls} size={16} />;
  if (kind === "offline") return <WifiOff aria-hidden className={cls} size={16} />;
  if (kind === "degraded") return <CircleOff aria-hidden className={cls} size={16} />;
  return <AlertTriangle aria-hidden className={cls} size={16} />;
}

function isPendingApproval(row: WorkspaceApprovalProjection): boolean {
  return (row.status || row.expected_status || "pending").toLowerCase() === "pending";
}

/**
 * UI-1 Direction A unified action lane: candidate Gate 2 attention +
 * automation failure/stale + artifact offline/degraded, merged with pending
 * command approvals from the shared follow spine (chat on only). V7a decide
 * buttons appear only when mutation is enabled and the CAS binding is
 * complete. Renders nothing when there is no action item.
 */
export function TodayAttention({ items, locale }: TodayAttentionProps) {
  const isZh = locale === "zh";
  const workbench = hermesWorkbenchCopy(locale);
  const copy = workbench.today.attention;
  const { state: follow } = useWorkspaceFollow();
  const mutationOn = follow.mutationEnabled === true;
  const [consumedIds, setConsumedIds] = useState<Record<string, true>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errorById, setErrorById] = useState<Record<string, string>>({});

  const approvals = useMemo(() => {
    const raw = Array.isArray(follow.approvals) ? follow.approvals : [];
    return filterApprovalsForPanel(raw, consumedIds).filter(isPendingApproval);
  }, [follow.approvals, consumedIds]);

  const total = items.length + approvals.length;

  const onDecide = useCallback(
    async (row: WorkspaceApprovalProjection, decision: "allow_once" | "deny") => {
      if (!mutationOn || !canDecideCommandApproval(row) || busyId) return;
      setBusyId(row.approval_id);
      setErrorById((prev) => {
        const next = { ...prev };
        delete next[row.approval_id];
        return next;
      });
      try {
        const receipt = await decideHermesCommandApproval({
          approvalId: row.approval_id,
          runId: row.run_id || "",
          commandDigest: row.digest || "",
          expectedExpiresAt: row.expires_at || "",
          decision,
        });
        if (receipt.status === "accepted" || receipt.status === "reconciling") {
          setConsumedIds((prev) => ({ ...prev, [row.approval_id]: true }));
        } else {
          setErrorById((prev) => ({
            ...prev,
            [row.approval_id]: receipt.reason_code || `decision status=${receipt.status}`,
          }));
        }
      } catch (err) {
        const message =
          err instanceof WorkspaceClientError
            ? err.message
            : err instanceof Error
              ? err.message
              : "decision failed";
        setErrorById((prev) => ({ ...prev, [row.approval_id]: message }));
      } finally {
        setBusyId(null);
      }
    },
    [busyId, mutationOn],
  );

  if (total === 0) {
    return null;
  }

  return (
    <section aria-labelledby="hermes-attention-title" data-hermes-attention>
      <div className="flex items-baseline gap-2">
        <h2 className="font-body-sm font-semibold text-text-primary" id="hermes-attention-title">
          {copy.title}
        </h2>
        <span className="font-data-mono text-xs text-warning" data-hermes-attention-count>
          {total}
        </span>
      </div>
      <ul className="mt-2 flex flex-col gap-2.5">
        {approvals.map((row) => {
          const decidable = mutationOn && canDecideCommandApproval(row);
          const busy = busyId === row.approval_id;
          const error = errorById[row.approval_id];
          return (
            <li key={`approval:${row.approval_id}`}>
              <div
                className="flex flex-wrap items-center gap-3 rounded-lg border border-warning/30 bg-warning/5 px-4 py-3"
                data-hermes-approval-decidable={decidable ? "true" : "false"}
                data-hermes-approval-id={row.approval_id}
                data-hermes-attention-kind="command_approval"
                data-hermes-today-approval
              >
                <ShieldAlert aria-hidden className="shrink-0 text-warning" size={16} />
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 font-body-sm font-semibold text-text-primary">
                    {copy.approvalTitle}
                    <span className={TAG_WARN}>{copy.approvalOnceTag}</span>
                  </p>
                  <p className="mt-0.5 font-body-sm text-text-secondary">{copy.approvalDesc}</p>
                  {row.expires_at ? (
                    <p className="mt-1 font-data-mono text-[11px] text-text-secondary">
                      {copy.expiresPrefix} {formatDateTime(row.expires_at, locale)}
                    </p>
                  ) : null}
                  {error ? (
                    <p className="mt-1 font-body-sm text-danger" role="alert">
                      {error}
                    </p>
                  ) : null}
                </div>
                {decidable ? (
                  <div className="flex shrink-0 gap-2" data-hermes-approval-actions>
                    <button
                      aria-label={`${copy.allowOnce} ${row.approval_id}`}
                      className={ACTION_PRIMARY}
                      data-hermes-approval-allow-once
                      disabled={busy || busyId != null}
                      onClick={() => void onDecide(row, "allow_once")}
                      type="button"
                    >
                      {busy ? copy.submitting : copy.allowOnce}
                    </button>
                    <button
                      aria-label={`${copy.deny} ${row.approval_id}`}
                      className={ACTION_GHOST}
                      data-hermes-approval-deny
                      disabled={busy || busyId != null}
                      onClick={() => void onDecide(row, "deny")}
                      type="button"
                    >
                      {copy.deny}
                    </button>
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
        {items.map((item) => {
          const href = item.href ? localizePath(item.href, locale) : undefined;
          let title: string;
          let desc: React.ReactNode = item.summary;
          let tag: React.ReactNode = null;
          let action: React.ReactNode = null;

          if (item.kind === "approval") {
            title = workbench.labels.researchApproval;
            tag = <span className={TAG_INFO}>{copy.gate2Tag}</span>;
            action = (
              <Link
                className={ACTION_GHOST}
                href={href ?? hermesRouteHref("approvals", locale)}
                prefetch={false}
              >
                {copy.review}
              </Link>
            );
          } else if (item.kind === "stale" || item.kind === "failure") {
            title = item.kind === "stale"
              ? isZh ? "自动化任务已过期" : "Automation job stale"
              : isZh ? "自动化任务失败" : "Automation job failed";
            tag = <span className={TAG_WARN}>{item.kind}</span>;
            desc = humanizeReasonCode(item.summary, locale);
            action = (
              <a className={ACTION_GHOST} href="#hermes-today-automation">
                {copy.viewAutomation}
              </a>
            );
          } else if (item.kind === "offline") {
            title = workbench.states.offline;
            desc = <span className="font-data-mono text-xs">{item.summary}</span>;
          } else {
            title = item.id === "candidate-feed" ? copy.candidateFeedUnavailable : item.title;
            desc = <span className="font-data-mono text-xs">{item.summary}</span>;
            action = href ? (
              <Link className={ACTION_GHOST} href={href} prefetch={false}>
                {copy.openTasks}
              </Link>
            ) : null;
          }

          return (
            <li key={item.id}>
              <div
                className="flex flex-wrap items-center gap-3 rounded-lg border border-border-subtle bg-bg-surface px-4 py-3"
                data-hermes-attention-id={item.id}
                data-hermes-attention-kind={item.kind}
              >
                {attentionIcon(item.kind)}
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 font-body-sm font-semibold text-text-primary">
                    {title}
                    {tag}
                  </p>
                  <p className="mt-0.5 break-words font-body-sm text-text-secondary">{desc}</p>
                </div>
                {action ? <div className="flex shrink-0 gap-2">{action}</div> : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
