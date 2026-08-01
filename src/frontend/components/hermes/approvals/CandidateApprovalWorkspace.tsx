import {
  AlertTriangle,
  Braces,
  CheckCircle2,
  FileCode2,
  Fingerprint,
  History,
  ShieldX,
} from "lucide-react";
import Link from "next/link";

import { Card, SectionTitle, StatusPill } from "@/components/ui/primitives";
import type {
  AgentCandidatesResponse,
  CandidateSummary,
} from "@/lib/api";
import {
  asCandidateApprovalBinding,
  candidateBindingTone,
  candidateDigestPresentation,
} from "@/lib/hermes/candidatePresentation";
import { hermesRouteHref } from "@/lib/hermes/routes";
import type { Locale } from "@/lib/locale";
import type {
  CandidateReadWarning,
  NormalizedCandidateDetailResponse,
  NormalizedCandidateListResponse,
} from "@/lib/hermes/candidateReadModel";
import type { PromotedRegistryContext } from "@/lib/hermes/promotedRegistry";

import { CandidateApprovalListState } from "./CandidateApprovalListState";

export type CandidateApprovalWorkspaceProps = {
  candidates: NormalizedCandidateListResponse;
  selectedCandidateId: string | null;
  detail: NormalizedCandidateDetailResponse | null;
  locale: Locale;
  registry?: PromotedRegistryContext;
};

type Tone = "neutral" | "success" | "warning" | "danger" | "info";

const copy = {
  en: {
    candidateIndex: "Candidate index",
    candidateIndexHint: "Choose any persisted candidate to inspect its immutable evidence.",
    selectedEvidence: "Selected evidence",
    selectCandidate: "Select a candidate",
    selectCandidateBody: "Choose a candidate from the index to load its read-only detail.",
    directSelection: "Opened from a direct link; this candidate is not present in the current index.",
    detailUnavailable: "Candidate detail unavailable",
    detailUnavailableBody:
      "The selected candidate could not be read. This is not an empty source or audit trail.",
    idMismatch: "Candidate detail mismatch",
    idMismatchBody: "The detail response did not match the selected candidate and was withheld.",
    goal: "Research goal",
    universe: "Universe",
    type: "type",
    status: "status",
    binding: "binding",
    integrity: "integrity",
    platformReview: "platform review primitive",
    platformReviewAvailable: "available · not HQA Gate 2 proof",
    platformReviewUnavailable: "unavailable",
    evidenceTruncated: "Some evidence was safely truncated",
    evidenceTruncatedBody:
      "The response exceeded the read-only display bounds. Inspect the authoritative repository for the complete bytes.",
    listDegraded: "Some candidate rows were invalid and were withheld.",
    listTruncated: "The candidate index was truncated to its safe display limit.",
    authoritativeDigest: "Authoritative manifest digest",
    migrationEvidence: "Migration evidence only — cannot approve",
    corruptTitle: "Integrity verification failed",
    sourcePreview: "Source preview",
    sourcePreviewHint: "Plain-text evidence only. Nothing here is imported or executed.",
    sourceUnavailable: "Source preview unavailable",
    sourceUnavailableBody: "The candidate detail contains no source preview.",
    sourceWithheld: "Source preview withheld",
    sourceWithheldBody:
      "Corrupt candidate bytes are not displayed as trustworthy research evidence.",
    auditTrail: "Audit trail",
    auditEvents: "Audit events",
    reviewEvents: "Review events",
    noAudit:
      "No digest-bound audit evidence is available. Unbound global and legacy logs are intentionally excluded.",
    noReviews: "No review events were recorded.",
    metadata: "Candidate metadata",
    noMetadata: "No candidate metadata was returned.",
    registryTitle: "Promoted registry context",
    registryUnavailable: "Promoted registry unavailable",
    registryUnavailableBody:
      "The factor catalog could not be verified. This is not evidence that the promoted registry is empty.",
    registered: "registered",
    promoted: "promoted",
    noPromoted: "No promoted factors are currently registered.",
    promotedTruncated: "Only the first 50 promoted factor IDs are shown.",
  },
  zh: {
    candidateIndex: "候选索引",
    candidateIndexHint: "选择任意已保存候选，检查其不可变证据。",
    selectedEvidence: "当前证据",
    selectCandidate: "请选择候选",
    selectCandidateBody: "从左侧候选索引选择一项，加载只读详情。",
    directSelection: "该候选来自直达链接，当前候选索引中没有这一项。",
    detailUnavailable: "候选详情不可用",
    detailUnavailableBody: "当前无法读取所选候选；这不代表源码或审计记录为空。",
    idMismatch: "候选详情不匹配",
    idMismatchBody: "详情响应与所选候选不一致，相关内容已安全隐藏。",
    goal: "研究目标",
    universe: "标的范围",
    type: "类型",
    status: "状态",
    binding: "绑定",
    integrity: "完整性",
    platformReview: "平台评审接口",
    platformReviewAvailable: "可用 · 不代表 HQA Gate 2",
    platformReviewUnavailable: "不可用",
    evidenceTruncated: "部分证据已安全截断",
    evidenceTruncatedBody: "响应超过只读展示上限；完整字节请回到权威候选仓库检查。",
    listDegraded: "部分候选行结构无效，已安全隐藏。",
    listTruncated: "候选索引超过安全展示上限，已截断。",
    authoritativeDigest: "权威 manifest digest",
    migrationEvidence: "仅为迁移证据，不能审批",
    corruptTitle: "完整性校验失败",
    sourcePreview: "源码预览",
    sourcePreviewHint: "仅展示纯文本证据，不会导入或执行任何内容。",
    sourceUnavailable: "源码预览不可用",
    sourceUnavailableBody: "候选详情没有返回源码预览。",
    sourceWithheld: "源码预览已隐藏",
    sourceWithheldBody: "损坏候选的字节不能作为可信研究证据展示。",
    auditTrail: "审计轨迹",
    auditEvents: "审计事件",
    reviewEvents: "复核事件",
    noAudit: "暂无与该 digest 精确绑定的审计证据；全局与旧版未绑定日志已主动排除。",
    noReviews: "尚未记录复核事件。",
    metadata: "候选元数据",
    noMetadata: "未返回候选元数据。",
    registryTitle: "已晋升因子注册表上下文",
    registryUnavailable: "已晋升因子注册表不可用",
    registryUnavailableBody: "当前无法核验因子目录；这不代表已晋升注册表为空。",
    registered: "已注册",
    promoted: "已晋升",
    noPromoted: "当前没有已注册的晋升因子。",
    promotedTruncated: "仅展示前 50 个已晋升 factor ID。",
  },
} as const;

function RegistryContext({
  registry,
  locale,
}: {
  registry: PromotedRegistryContext;
  locale: Locale;
}) {
  const text = copy[locale];
  if (registry.readStatus === "unavailable") {
    return (
      <Card className="border-warning/30 bg-warning/5" data-hermes-promoted-registry-unavailable>
        <p className="font-body-sm font-semibold text-warning">
          {text.registryUnavailable}
        </p>
        <p className="mt-1 font-body-sm text-text-secondary">
          {text.registryUnavailableBody}
        </p>
        {registry.error ? (
          <code className="mt-2 block break-words font-data-mono text-xs text-warning">
            {registry.error}
          </code>
        ) : null}
      </Card>
    );
  }
  return (
    <Card data-hermes-promoted-registry>
      <SectionTitle title={text.registryTitle} />
      <p className="font-data-mono text-xs text-text-secondary">
        <strong className="text-text-primary">{registry.registeredCount}</strong>{" "}
        {text.registered} ·{" "}
        <strong className="text-text-primary">
          {registry.promotedFactorIds.length}
        </strong>{" "}
        {text.promoted}
      </p>
      {registry.promotedFactorIds.length > 0 ? (
        <ul className="mt-3 space-y-1.5" data-hermes-promoted-factor-list>
          {registry.promotedFactorIds.map((factorId) => (
            <li
              className="break-all rounded-md border border-border-subtle bg-bg-surface-muted px-2 py-1.5 font-data-mono text-xs text-text-primary"
              data-hermes-promoted-factor-id={factorId}
              key={factorId}
            >
              {factorId}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 font-body-sm text-text-secondary">{text.noPromoted}</p>
      )}
      {registry.truncated ? (
        <p className="mt-2 font-body-sm text-warning">{text.promotedTruncated}</p>
      ) : null}
    </Card>
  );
}

function integrityTone(value: CandidateSummary["integrity_state"]): Tone {
  if (value === "verified") return "success";
  if (value === "migration_required") return "warning";
  return "danger";
}

function CandidateLink({
  candidate,
  selected,
  locale,
}: {
  candidate: CandidateSummary;
  selected: boolean;
  locale: Locale;
}) {
  const text = copy[locale];
  return (
    <li data-hermes-approval-id={candidate.candidate_id}>
      <Link
        aria-current={selected ? "page" : undefined}
        className={`block min-h-11 rounded-lg border p-3 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info ${
          selected
            ? "border-info/50 bg-info/10"
            : "border-border-subtle bg-bg-surface-muted hover:border-info/30 hover:bg-info/5"
        }`}
        href={hermesRouteHref("approvals", locale, {
          candidate: candidate.candidate_id,
        })}
        prefetch={false}
      >
        <span className="flex min-w-0 items-center gap-2">
          <Fingerprint className={selected ? "text-info" : "text-text-secondary"} size={14} />
          <span className="min-w-0 flex-1 truncate font-data-mono text-xs font-semibold text-text-primary">
            {candidate.candidate_id}
          </span>
        </span>
        {candidate.goal ? (
          <span className="mt-2 line-clamp-2 block font-body-sm text-text-secondary">
            {candidate.goal}
          </span>
        ) : null}
        <span className="mt-2 flex flex-wrap gap-1.5">
          <StatusPill
            label={text.integrity}
            value={candidate.integrity_state}
            tone={integrityTone(candidate.integrity_state)}
          />
          <StatusPill
            label={text.status}
            value={candidate.status ?? "—"}
            tone={candidateBindingTone(
              asCandidateApprovalBinding(candidate.status),
            )}
          />
        </span>
      </Link>
    </li>
  );
}

function EventList({
  events,
  empty,
  kind,
}: {
  events: string[];
  empty: string;
  kind: "audit" | "review";
}) {
  if (events.length === 0) {
    return <p className="mt-2 font-body-sm text-text-secondary">{empty}</p>;
  }
  return (
    <ol className="mt-2 space-y-2" data-hermes-candidate-events={kind}>
      {events.map((event, index) => (
        <li
          className="flex gap-2 rounded-lg border border-border-subtle bg-bg-surface-muted p-3"
          key={`${kind}-${index}-${event}`}
        >
          {kind === "audit" ? (
            <History className="mt-0.5 shrink-0 text-info" size={14} />
          ) : (
            <CheckCircle2 className="mt-0.5 shrink-0 text-text-secondary" size={14} />
          )}
          <span className="min-w-0 break-words font-data-mono text-xs text-text-primary">
            {event}
          </span>
        </li>
      ))}
    </ol>
  );
}

function CandidateEvidence({
  detail,
  summary,
  selectedCandidateId,
  locale,
}: {
  detail: NormalizedCandidateDetailResponse | null;
  summary: CandidateSummary | undefined;
  selectedCandidateId: string | null;
  locale: Locale;
}) {
  const text = copy[locale];
  if (!selectedCandidateId || !detail) {
    return (
      <Card data-hermes-candidate-not-selected>
        <p className="font-body-sm font-semibold text-text-primary">{text.selectCandidate}</p>
        <p className="mt-1 font-body-sm text-text-secondary">{text.selectCandidateBody}</p>
      </Card>
    );
  }

  if (detail.apiError) {
    return (
      <Card className="border-danger/40 bg-danger/5" data-hermes-candidate-detail-unavailable>
        <p className="font-body-sm font-semibold text-danger">{text.detailUnavailable}</p>
        <p className="mt-1 font-body-sm text-text-secondary">{text.detailUnavailableBody}</p>
        <p className="mt-2 break-words font-data-mono text-xs text-danger">{detail.apiError}</p>
      </Card>
    );
  }

  if (detail.candidate_id !== selectedCandidateId) {
    return (
      <Card className="border-danger/40 bg-danger/5" data-hermes-candidate-detail-mismatch>
        <p className="font-body-sm font-semibold text-danger">{text.idMismatch}</p>
        <p className="mt-1 font-body-sm text-text-secondary">{text.idMismatchBody}</p>
      </Card>
    );
  }

  const binding = asCandidateApprovalBinding(detail.approval_binding);
  const digest = candidateDigestPresentation(detail);
  const sourceVisible =
    detail.integrity_state !== "corrupt" &&
    typeof detail.source_preview === "string" &&
    detail.source_preview.length > 0;

  return (
    <article
      className="space-y-4"
      data-hermes-approval-enabled={detail.approval_enabled ? "true" : "false"}
      data-hermes-approval-binding={binding ?? "null"}
      data-hermes-integrity={detail.integrity_state}
      data-hermes-selected-candidate={selectedCandidateId}
    >
      {!summary ? (
        <Card className="border-info/30 bg-info/5" tone="info">
          <p className="font-body-sm text-text-secondary">{text.directSelection}</p>
        </Card>
      ) : null}

      {detail.candidateReadWarning === "candidate_evidence_truncated" ? (
        <Card className="border-warning/30 bg-warning/5" data-hermes-candidate-truncated>
          <p className="font-body-sm font-semibold text-warning">
            {text.evidenceTruncated}
          </p>
          <p className="mt-1 font-body-sm text-text-secondary">
            {text.evidenceTruncatedBody}
          </p>
        </Card>
      ) : null}

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="font-label-caps uppercase text-text-secondary">{text.selectedEvidence}</p>
            <h2 className="mt-1 break-all font-data-mono text-base font-semibold text-text-primary">
              {detail.candidate_id}
            </h2>
            {summary?.goal ? (
              <p className="mt-3 max-w-3xl font-body-sm text-text-secondary">
                <span className="font-semibold text-text-primary">{text.goal}: </span>
                {summary.goal}
              </p>
            ) : null}
            {summary?.universe?.length ? (
              <p className="mt-1 font-data-mono text-xs text-text-secondary">
                <span className="opacity-70">{text.universe} </span>
                {summary.universe.join(" · ")}
              </p>
            ) : null}
          </div>
          <div className="flex max-w-xl flex-wrap justify-start gap-1.5 lg:justify-end">
            <StatusPill label={text.type} value={summary?.artifact_type ?? "—"} />
            <StatusPill
              label={text.status}
              value={detail.status ?? "—"}
              tone={candidateBindingTone(
                asCandidateApprovalBinding(detail.status),
              )}
            />
            <StatusPill
              label={text.integrity}
              value={detail.integrity_state}
              tone={integrityTone(detail.integrity_state)}
            />
            <StatusPill
              label={text.binding}
              value={binding ?? "—"}
              tone={candidateBindingTone(binding)}
            />
            <StatusPill
              label={text.platformReview}
              value={
                detail.approval_enabled
                  ? text.platformReviewAvailable
                  : text.platformReviewUnavailable
              }
              tone="neutral"
            />
          </div>
        </div>

        {digest.kind === "authoritative" ? (
          <div className="mt-4 rounded-lg border border-accent-success/30 bg-accent-success/5 p-3">
            <p className="flex items-center gap-2 font-body-sm font-semibold text-accent-success">
              <Fingerprint size={15} /> {text.authoritativeDigest}
            </p>
            <code className="mt-2 block break-all font-data-mono text-xs text-text-primary">
              {digest.digest}
            </code>
          </div>
        ) : null}

        {digest.kind === "migration_evidence" ? (
          <div className="mt-4 rounded-lg border border-warning/40 bg-warning/5 p-3">
            <p className="flex items-center gap-2 font-body-sm font-semibold text-warning">
              <AlertTriangle size={15} /> {text.migrationEvidence}
            </p>
            <p className="mt-2 break-all font-data-mono text-xs text-text-secondary">
              <span className="opacity-70">observed_manifest_digest </span>
              <code>{digest.digest}</code>
            </p>
          </div>
        ) : null}

        {digest.kind === "corrupt" ? (
          <div className="mt-4 rounded-lg border border-danger/40 bg-danger/5 p-3">
            <p className="flex items-center gap-2 font-body-sm font-semibold text-danger">
              <ShieldX size={15} /> {text.corruptTitle}
            </p>
            <code className="mt-2 block break-all font-data-mono text-xs text-danger">
              {digest.errorCode}
            </code>
          </div>
        ) : null}
      </Card>

      <Card>
        <SectionTitle
          hint={text.sourcePreviewHint}
          right={<FileCode2 className="text-text-secondary" size={17} />}
          title={text.sourcePreview}
        />
        {detail.integrity_state === "corrupt" ? (
          <div className="rounded-lg border border-danger/30 bg-danger/5 p-3" data-hermes-source-withheld>
            <p className="font-body-sm font-semibold text-danger">{text.sourceWithheld}</p>
            <p className="mt-1 font-body-sm text-text-secondary">{text.sourceWithheldBody}</p>
          </div>
        ) : sourceVisible ? (
          <pre
            aria-label={text.sourcePreview}
            className="max-h-[32rem] overflow-auto whitespace-pre rounded-lg border border-border-subtle bg-bg-base p-4 font-code-sm text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
            data-hermes-candidate-source
            tabIndex={0}
          >
            {detail.source_preview}
          </pre>
        ) : (
          <div className="rounded-lg border border-border-subtle bg-bg-surface-muted p-3" data-hermes-source-empty>
            <p className="font-body-sm font-semibold text-text-primary">{text.sourceUnavailable}</p>
            <p className="mt-1 font-body-sm text-text-secondary">{text.sourceUnavailableBody}</p>
          </div>
        )}
      </Card>

      <Card>
        <SectionTitle
          right={<History className="text-text-secondary" size={17} />}
          title={text.auditTrail}
        />
        <div className="grid gap-4 xl:grid-cols-2">
          <section aria-labelledby="candidate-audit-title">
            <h3 className="font-label-caps text-text-secondary" id="candidate-audit-title">
              {text.auditEvents}
            </h3>
            <EventList empty={text.noAudit} events={detail.audit} kind="audit" />
          </section>
          <section aria-labelledby="candidate-review-title">
            <h3 className="font-label-caps text-text-secondary" id="candidate-review-title">
              {text.reviewEvents}
            </h3>
            <EventList empty={text.noReviews} events={detail.reviews} kind="review" />
          </section>
        </div>
      </Card>

      <Card>
        <SectionTitle
          right={<Braces className="text-text-secondary" size={17} />}
          title={text.metadata}
        />
        {detail.metadata && Object.keys(detail.metadata).length > 0 ? (
          <pre
            aria-label={text.metadata}
            className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border-subtle bg-bg-base p-4 font-code-sm text-text-primary"
            data-hermes-candidate-metadata
            tabIndex={0}
          >
            {JSON.stringify(detail.metadata, null, 2)}
          </pre>
        ) : (
          <p className="font-body-sm text-text-secondary">{text.noMetadata}</p>
        )}
      </Card>
    </article>
  );
}

/**
 * Read-only candidate evidence browser. Links only change the selected GET
 * resource; there are deliberately no review controls or mutation clients.
 */
export function CandidateApprovalWorkspace({
  candidates,
  selectedCandidateId,
  detail,
  locale,
  registry,
}: CandidateApprovalWorkspaceProps) {
  const text = copy[locale];
  const selectedSummary = candidates.candidates.find(
    (candidate) => candidate.candidate_id === selectedCandidateId,
  );
  const listWarning = (
    candidates as AgentCandidatesResponse & {
      candidateReadWarning?: CandidateReadWarning;
    }
  ).candidateReadWarning;

  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(15rem,19rem)_minmax(0,1fr)]">
      <aside className="min-w-0 space-y-4 lg:sticky lg:top-4 lg:self-start">
        <Card className="bg-[var(--color-stream-surface)]" padded={false}>
          <div className="border-b border-border-subtle p-4">
            <SectionTitle title={text.candidateIndex} hint={text.candidateIndexHint} />
          </div>
          <div className="max-h-[42rem] overflow-y-auto p-3">
            {listWarning ? (
              <p
                className="mb-3 rounded-lg border border-warning/30 bg-warning/5 p-3 font-body-sm text-warning"
                data-hermes-candidate-list-warning={listWarning}
              >
                {listWarning === "candidate_list_truncated"
                  ? text.listTruncated
                  : text.listDegraded}
              </p>
            ) : null}
            {candidates.apiError || candidates.candidates.length === 0 ? (
              <CandidateApprovalListState candidates={candidates} locale={locale} />
            ) : (
              <nav aria-label={text.candidateIndex}>
                <ul className="space-y-2" data-hermes-candidate-index>
                  {candidates.candidates.map((candidate) => (
                    <CandidateLink
                      candidate={candidate}
                      key={candidate.candidate_id}
                      locale={locale}
                      selected={candidate.candidate_id === selectedCandidateId}
                    />
                  ))}
                </ul>
              </nav>
            )}
          </div>
        </Card>
        {registry ? <RegistryContext locale={locale} registry={registry} /> : null}
      </aside>
      <div className="min-w-0">
        <CandidateEvidence
          detail={detail}
          locale={locale}
          selectedCandidateId={selectedCandidateId}
          summary={selectedSummary}
        />
      </div>
    </div>
  );
}
