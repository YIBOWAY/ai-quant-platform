"use client";

import { useState } from "react";
import Link from "next/link";

import type { Locale } from "@/lib/locale";
import { localizePath } from "@/lib/locale";

const SOURCE_DIGEST = /^[0-9a-f]{64}$/i;
const OUTCOMES = new Set([
  "pending",
  "queued",
  "running",
  "verified_candidate",
  "failed",
  "outcome_unknown",
]);

type PlatformResearchProvenance = {
  operation_id: string;
  material_digest: string;
  job_id: string;
  job_key: string;
  candidate_id?: string;
  source_digest?: string;
  evidence_manifest_digest?: string;
  evidence_href?: string;
};

type PlatformResearchEvidence = {
  manifest_digest: string;
  href: string;
  candidate_code_digest?: string | null;
  candidate_code?: string | null;
  candidate_code_href?: string | null;
  qlib_receipt_digest?: string | null;
  qlib_receipt_href?: string | null;
  platform_receipt_digest?: string | null;
  platform_receipt_href?: string | null;
  comparison_digest?: string | null;
  comparison_href?: string | null;
  comparison?: Record<string, unknown> | null;
  cost_model?: Record<string, unknown> | null;
  dsr?: Record<string, unknown> | null;
  verification_gates?: Record<string, unknown> | null;
  performance?: {
    total_return?: number | null;
    sharpe_annual?: number | null;
    max_drawdown?: number | null;
    turnover_period?: number | null;
    n_periods?: number | null;
    window_start?: string | null;
    window_end?: string | null;
  } | null;
  failed_phase?: string | null;
  failure_code?: string | null;
};

export type PlatformResearchResult = {
  status: string;
  code: string;
  message: string;
  outcome: string;
  terminal: boolean;
  provenance: PlatformResearchProvenance;
  candidate_id?: string;
  source_digest?: string;
  display_name_zh?: string;
  summary_zh?: string;
  evidence?: PlatformResearchEvidence;
};

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function validOutcomeState(
  outcome: string,
  status: string,
  terminal: boolean,
): boolean {
  if (outcome === "queued" || outcome === "pending" || outcome === "running") {
    return status === outcome && terminal === false;
  }
  if (outcome === "verified_candidate") {
    return status === "candidate_ready" && terminal === true;
  }
  if (outcome === "failed") {
    return status === "failed" && terminal === true;
  }
  return (
    outcome === "outcome_unknown" &&
    status === "outcome_unknown" &&
    terminal === true
  );
}

function parseRequest(
  value: unknown,
  sessionId: string,
): PlatformResearchResult | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const request = value as Record<string, unknown>;
  if (
    request.hermes_session_id !== sessionId ||
    !nonEmptyString(request.status) ||
    typeof request.terminal !== "boolean" ||
    !nonEmptyString(request.outcome) ||
    !OUTCOMES.has(request.outcome) ||
    request.result_reply === null ||
    typeof request.result_reply !== "object" ||
    Array.isArray(request.result_reply)
  ) {
    return null;
  }
  const reply = request.result_reply as Record<string, unknown>;
  if (
    !nonEmptyString(reply.status) ||
    reply.status !== request.status ||
    !nonEmptyString(reply.code) ||
    !nonEmptyString(reply.message) ||
    reply.provenance === null ||
    typeof reply.provenance !== "object" ||
    Array.isArray(reply.provenance)
  ) {
    return null;
  }
  if (!validOutcomeState(request.outcome, request.status, request.terminal)) {
    return null;
  }
  const displayNameZh =
    nonEmptyString(reply.display_name_zh) && reply.display_name_zh.trim().length <= 120
      ? reply.display_name_zh.trim()
      : undefined;
  const summaryZh =
    nonEmptyString(reply.summary_zh) && reply.summary_zh.trim().length <= 1_000
      ? reply.summary_zh.trim()
      : undefined;

  const provenance = reply.provenance as Record<string, unknown>;
  if (
    !nonEmptyString(request.operation_id) ||
    !SOURCE_DIGEST.test(request.operation_id) ||
    !nonEmptyString(request.material_digest) ||
    !SOURCE_DIGEST.test(request.material_digest) ||
    !nonEmptyString(request.job_id) ||
    !nonEmptyString(request.job_key) ||
    provenance.operation_id !== request.operation_id ||
    provenance.material_digest !== request.material_digest ||
    provenance.job_id !== request.job_id ||
    provenance.job_key !== request.job_key
  ) {
    return null;
  }

  const candidateId = request.candidate_id;
  const sourceDigest = request.source_digest;
  const replyCandidateId = provenance.candidate_id;
  const replySourceDigest = provenance.source_digest;
  const requestHasCandidate =
    candidateId !== undefined || sourceDigest !== undefined;
  const replyHasCandidate =
    replyCandidateId !== undefined || replySourceDigest !== undefined;
  const validCandidate =
    nonEmptyString(candidateId) &&
    nonEmptyString(sourceDigest) &&
    SOURCE_DIGEST.test(sourceDigest) &&
    replyCandidateId === candidateId &&
    replySourceDigest === sourceDigest;
  if (request.outcome === "verified_candidate") {
    if (!validCandidate) {
      return null;
    }
  } else if (requestHasCandidate || replyHasCandidate) {
    return null;
  }

  const evidenceValue = request.evidence;
  let evidence: PlatformResearchEvidence | undefined;
  if (request.terminal) {
    if (
      evidenceValue === null ||
      typeof evidenceValue !== "object" ||
      Array.isArray(evidenceValue)
    ) {
      return null;
    }
    const rawEvidence = evidenceValue as Record<string, unknown>;
    const manifestDigest = rawEvidence.manifest_digest;
    const href = rawEvidence.href;
    if (
      !nonEmptyString(manifestDigest) ||
      !SOURCE_DIGEST.test(manifestDigest) ||
      !nonEmptyString(href) ||
      href !==
        `/api/assistant/remote/evidence/${request.operation_id}/${manifestDigest}` ||
      provenance.evidence_manifest_digest !== manifestDigest ||
      provenance.evidence_href !== href
    ) {
      return null;
    }
    if (
      request.outcome === "verified_candidate" &&
      (!nonEmptyString(rawEvidence.candidate_code_digest) ||
        rawEvidence.candidate_code_digest !== sourceDigest ||
        !nonEmptyString(rawEvidence.candidate_code) ||
        rawEvidence.candidate_code_href !== `${href}#candidate-code` ||
        !nonEmptyString(rawEvidence.qlib_receipt_digest) ||
        !SOURCE_DIGEST.test(rawEvidence.qlib_receipt_digest) ||
        rawEvidence.qlib_receipt_href !== `${href}#qlib-receipt` ||
        !nonEmptyString(rawEvidence.platform_receipt_digest) ||
        !SOURCE_DIGEST.test(rawEvidence.platform_receipt_digest) ||
        rawEvidence.platform_receipt_href !== `${href}#platform-receipt` ||
        !nonEmptyString(rawEvidence.comparison_digest) ||
        !SOURCE_DIGEST.test(rawEvidence.comparison_digest) ||
        rawEvidence.comparison_href !== `${href}#comparison` ||
        rawEvidence.dsr === null ||
        typeof rawEvidence.dsr !== "object" ||
        (rawEvidence.dsr as Record<string, unknown>).passed !== true ||
        rawEvidence.verification_gates === null ||
        typeof rawEvidence.verification_gates !== "object" ||
        rawEvidence.performance === null ||
        typeof rawEvidence.performance !== "object" ||
        typeof (rawEvidence.performance as Record<string, unknown>).n_periods !== "number" ||
        !nonEmptyString((rawEvidence.performance as Record<string, unknown>).window_start) ||
        !nonEmptyString((rawEvidence.performance as Record<string, unknown>).window_end))
    ) {
      return null;
    }
    evidence = rawEvidence as PlatformResearchEvidence;
  } else if (
    evidenceValue !== null ||
    provenance.evidence_manifest_digest !== undefined ||
    provenance.evidence_href !== undefined
  ) {
    return null;
  }

  return {
    status: reply.status,
    code: reply.code,
    message: reply.message,
    outcome: request.outcome,
    terminal: request.terminal,
    ...(displayNameZh ? { display_name_zh: displayNameZh } : {}),
    ...(summaryZh ? { summary_zh: summaryZh } : {}),
    provenance: {
      operation_id: request.operation_id,
      material_digest: request.material_digest,
      job_id: request.job_id,
      job_key: request.job_key,
      ...(validCandidate
        ? { candidate_id: candidateId, source_digest: sourceDigest }
        : {}),
      ...(evidence
        ? {
            evidence_manifest_digest: evidence.manifest_digest,
            evidence_href: evidence.href,
          }
        : {}),
    },
    ...(validCandidate
      ? { candidate_id: candidateId, source_digest: sourceDigest }
      : {}),
    ...(evidence ? { evidence } : {}),
  };
}

export function selectPlatformResearchResult(
  requests: unknown[],
  activeHermesSessionId: string | null | undefined,
): PlatformResearchResult | null {
  const sessionId = activeHermesSessionId?.trim();
  if (!sessionId) {
    return null;
  }
  for (const request of requests) {
    if (
      request !== null &&
      typeof request === "object" &&
      !Array.isArray(request) &&
      (request as Record<string, unknown>).hermes_session_id === sessionId
    ) {
      return parseRequest(request, sessionId);
    }
  }
  return null;
}

function EvidencePanel({
  evidence,
  isZh,
}: {
  evidence: PlatformResearchEvidence;
  isZh: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const panelId = `research-evidence-${evidence.manifest_digest.slice(0, 12)}`;
  const comparison = evidence.comparison ?? {};
  const costs = evidence.cost_model ?? {};
  const dsr = evidence.dsr ?? {};
  const gates = evidence.verification_gates ?? {};
  const costGate =
    gates.cost_sensitivity && typeof gates.cost_sensitivity === "object"
      ? (gates.cost_sensitivity as Record<string, unknown>)
      : {};
  const performance = evidence.performance ?? {};
  return (
    <div className="mt-3 min-w-0 border-t border-border-subtle pt-3">
      <div className="flex flex-wrap items-center gap-3">
        <a
          className="app-touch-target inline-flex items-center font-body-sm text-info underline underline-offset-4"
          href={evidence.href}
        >
          {isZh ? "证据收据" : "Evidence receipt"}
        </a>
        <button
          aria-controls={panelId}
          aria-expanded={expanded}
          className="app-touch-target rounded-md border border-border-subtle px-3 font-body-sm text-text-primary"
          onClick={() => setExpanded((value) => !value)}
          type="button"
        >
          {expanded
            ? isZh
              ? "收起证据"
              : "Hide evidence"
            : isZh
              ? "展开证据"
              : "Show evidence"}
        </button>
      </div>
      {expanded ? (
        <dl
          className="mt-3 grid min-w-0 gap-2 font-data-mono text-[10px] text-text-secondary sm:grid-cols-2"
          id={panelId}
        >
          <div className="min-w-0">
            <dt>{isZh ? "代码 digest" : "Code digest"}</dt>
            <dd className="break-all">
              {evidence.candidate_code_href ? (
                <a href={evidence.candidate_code_href}>{evidence.candidate_code_digest}</a>
              ) : (
                evidence.candidate_code_digest ?? "—"
              )}
            </dd>
          </div>
          <div className="min-w-0">
            <dt>Qlib</dt>
            <dd className="break-all">
              {evidence.qlib_receipt_href ? (
                <a href={evidence.qlib_receipt_href}>{evidence.qlib_receipt_digest}</a>
              ) : (
                evidence.qlib_receipt_digest ?? "—"
              )}
            </dd>
          </div>
          <div className="min-w-0">
            <dt>Platform replay</dt>
            <dd className="break-all">
              {evidence.platform_receipt_href ? (
                <a href={evidence.platform_receipt_href}>
                  {evidence.platform_receipt_digest}
                </a>
              ) : (
                evidence.platform_receipt_digest ?? "—"
              )}
            </dd>
          </div>
          <div className="min-w-0">
            <dt>Comparison</dt>
            <dd className="break-all">
              {evidence.comparison_href ? (
                <a href={evidence.comparison_href}>{evidence.comparison_digest}</a>
              ) : (
                evidence.comparison_digest ?? "—"
              )}
            </dd>
          </div>
          <div>
            <dt>{isZh ? "双引擎核心指标" : "Dual-engine metrics"}</dt>
            <dd>
              corr {String(comparison.daily_return_correlation ?? "—")} · NAV bps{" "}
              {String(comparison.terminal_nav_difference_bps ?? "—")} · weight bps{" "}
              {String(comparison.max_symbol_weight_difference_bps ?? "—")}
            </dd>
          </div>
          <div>
            <dt>DSR</dt>
            <dd>
              {String(dsr.value ?? "—")} · {String(dsr.passed ?? "—")}
            </dd>
          </div>
          <div>
            <dt>{isZh ? "成本门" : "Cost gate"}</dt>
            <dd>
              {String(costs.commission_bps ?? "—")}bp +{" "}
              {String(costs.slippage_bps ?? "—")}bp · {String(costGate.passed ?? "—")}
            </dd>
          </div>
          <div>
            <dt>{isZh ? "可复算绩效" : "Recomputable performance"}</dt>
            <dd>
              return {String(performance.total_return ?? "—")} · Sharpe{" "}
              {String(performance.sharpe_annual ?? "—")} · max DD{" "}
              {String(performance.max_drawdown ?? "—")} · turnover{" "}
              {String(performance.turnover_period ?? "—")}
            </dd>
          </div>
          <div>
            <dt>{isZh ? "样本窗口" : "Sample window"}</dt>
            <dd>
              {String(performance.window_start ?? "—")} →{" "}
              {String(performance.window_end ?? "—")} · n={String(performance.n_periods ?? "—")}
            </dd>
          </div>
          <div>
            <dt>{isZh ? "失败阶段" : "Failure phase"}</dt>
            <dd>{evidence.failed_phase ?? evidence.failure_code ?? "—"}</dd>
          </div>
          {evidence.candidate_code ? (
            <div className="min-w-0 sm:col-span-2">
              <dt>{isZh ? "因子代码" : "Factor source"}</dt>
              <dd>
                <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded bg-bg-surface p-2 text-[11px] text-text-primary">
                  {evidence.candidate_code}
                </pre>
              </dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </div>
  );
}

function researchStatusLabel(result: PlatformResearchResult, isZh: boolean) {
  if (result.code === "paper_running") return isZh ? "模拟运行已启用" : "Paper simulation enabled";
  if (result.code.startsWith("paper_activation_failed:")) return isZh ? "研究通过 · 模拟未启用" : "Verified · Simulation not enabled";
  const labels = isZh
    ? {
        pending: "等待处理",
        queued: "排队中",
        running: "运行中",
        verified_candidate: "已验证",
        failed: "研究失败",
        outcome_unknown: "结果待确认",
      }
    : {
        pending: "Pending",
        queued: "Queued",
        running: "Running",
        verified_candidate: "Verified",
        failed: "Research failed",
        outcome_unknown: "Outcome unknown",
      };
  return labels[result.outcome as keyof typeof labels] ?? (isZh ? "状态待确认" : "Unknown");
}

function researchTitle(result: PlatformResearchResult, isZh: boolean) {
  if (!isZh) return "Platform research result";
  if (result.outcome === "verified_candidate") {
    return result.display_name_zh ?? "已验证因子候选";
  }
  return "平台研究进度";
}

function researchMessage(result: PlatformResearchResult, isZh: boolean) {
  if (result.code === "paper_running") return isZh ? "双引擎验证与准入检查通过，已分配 10,000 美元模拟资金。策略会在每日计划时段生成信号和执行，成交与表现可在模拟账户查看。" : result.message;
  if (result.code.startsWith("paper_activation_failed:")) return isZh ? `研究已通过验证，但模拟运行未能启用。候选已保留；原因：${result.code.slice("paper_activation_failed:".length)}。` : result.message;
  if (!isZh) return result.message;
  if (result.outcome === "verified_candidate") {
    return result.summary_zh ?? "研究已完成验证，当前尚未启用模拟运行。";
  }
  const messages = {
    pending: "研究请求已记录，正在等待处理。",
    queued: "研究任务已排队。",
    running: "正在运行研究，完成后会回到本对话。",
    failed: "研究未完成，请展开技术信息查看失败原因。",
    outcome_unknown: "暂时无法确认研究结果，请稍后刷新。",
  } as const;
  return messages[result.outcome as keyof typeof messages] ?? "研究状态待确认。";
}

export function PlatformResearchResultCard({
  locale,
  result,
}: {
  locale: Locale;
  result: PlatformResearchResult;
}) {
  const isZh = locale === "zh";
  const statusLabel = researchStatusLabel(result, isZh);
  const title = researchTitle(result, isZh);
  const message = researchMessage(result, isZh);
  const verifiedCandidate =
    result.outcome === "verified_candidate" &&
    result.status === "candidate_ready" &&
    result.terminal &&
    result.candidate_id &&
    result.source_digest;
  return (
    <section
      aria-label={title}
      className="m-3 rounded-lg border border-info/40 bg-info/5 p-3"
      data-platform-research-result
    >
      <p aria-atomic="true" aria-live="polite" className="sr-only" role="status">
        {`${statusLabel}: ${message}`}
      </p>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-label-caps text-info">{title}</h2>
        <span className="font-data-mono text-[10px] uppercase text-text-secondary">
          {statusLabel}
        </span>
      </div>
      <p className="mt-2 font-body-sm text-text-primary">{message}</p>
      {verifiedCandidate ? (
        <div className="mt-3 border-t border-border-subtle pt-3">
          <Link
            className="app-touch-target inline-flex items-center font-body-sm text-info underline underline-offset-4"
            href={localizePath(result.code === "paper_running" ? "/paper-trading" : "/library", locale)}
          >
            {result.code === "paper_running" ? (isZh ? "查看模拟运行" : "View paper simulation") : (isZh ? "去候选库" : "Open candidate library")}
          </Link>
        </div>
      ) : null}
      <details className="mt-3 border-t border-border-subtle pt-3 font-data-mono text-[10px] text-text-secondary">
        <summary className="cursor-pointer select-none font-body-sm">
          {isZh ? "技术信息" : "Technical details"}
        </summary>
        <dl className="mt-2 grid min-w-0 gap-2 sm:grid-cols-2">
          <div>
            <dt>{isZh ? "原始状态" : "Raw status"}</dt>
            <dd className="break-all">{result.status}</dd>
          </div>
          <div>
            <dt>{isZh ? "结果代码" : "Result code"}</dt>
            <dd className="break-all">{result.code}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt>{isZh ? "原始消息" : "Raw message"}</dt>
            <dd className="break-all">{result.message}</dd>
          </div>
          {verifiedCandidate && result.candidate_id ? (
            <div>
              <dt>{isZh ? "候选编号" : "Candidate ID"}</dt>
              <dd className="break-all">{result.candidate_id}</dd>
            </div>
          ) : null}
          {verifiedCandidate && result.source_digest ? (
            <div>
              <dt>{isZh ? "来源校验指纹" : "Source fingerprint"}</dt>
              <dd className="break-all">{result.source_digest}</dd>
            </div>
          ) : null}
        </dl>
      </details>
      {result.evidence ? <EvidencePanel evidence={result.evidence} isZh={isZh} /> : null}
    </section>
  );
}
