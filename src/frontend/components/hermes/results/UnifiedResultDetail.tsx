import {
  ArrowLeft,
  Braces,
  ExternalLink,
  Fingerprint,
  Link2,
} from "lucide-react";
import Link from "next/link";

import { Card, SectionTitle, StatusPill } from "@/components/ui/primitives";
import { formatDateTime } from "@/components/hermes/artifacts/formatters";
import {
  resultAuthorityLabel,
  resultDisplayTitle,
  resultFreshnessLabel,
  resultFreshnessTone,
  resultKindLabel,
  resultReadStatusLabel,
  resultReadStatusTone,
  resultSourceLabel,
  resultStatusLabel,
  resultSummaryText,
  resultWarningText,
} from "@/lib/hermes/resultsPresentation";
import {
  hermesResultKey,
  type HermesResultDetailEnvelope,
  type HermesResultRunLink,
} from "@/lib/hermes/resultsTypes";
import type { Locale } from "@/lib/locale";

export type UnifiedResultDetailProps = {
  envelope: HermesResultDetailEnvelope;
  locale: Locale;
  backHref: string;
  /** UI route supplied by the page adapter; raw API provenance is never rewritten. */
  originalResourceHref?: string | null;
};

const copy = {
  en: {
    back: "Back to unified results",
    status: "status",
    read: "read",
    freshness: "freshness",
    source: "source",
    authority: "Authority",
    occurredAt: "Occurred at",
    resourceId: "Resource ID",
    provenance: "Provenance",
    detailHref: "Unified detail endpoint",
    originalHref: "Original resource endpoint",
    openOriginal: "Open original result view",
    runLinks: "Exact Hermes run links",
    runLinksHint: "Causal links recorded by exact platform resource identity.",
    runLinksUnavailable:
      "Exact Hermes run-link authority is unavailable, so whether a link exists cannot be determined.",
    noRunLinks:
      "The exact-link lookup completed and no Hermes run link is recorded for this resource.",
    command: "Command",
    relation: "Relation",
    session: "Hermes session",
    run: "Hermes run",
    digest: "Link digest",
    sourceEvent: "Source event",
    observed: "Observed",
    resource: "Resource payload",
    resourceHint: "Read-only JSON returned by the authoritative resource adapter.",
    missingTitle: "Result resource not found",
    missingBody: "No authoritative resource exists for this exact kind and resource id.",
    corruptTitle: "Result resource is corrupt",
    corruptBody: "Integrity checks failed. The payload is not rendered as evidence.",
    unavailableTitle: "Result source unavailable",
    unavailableBody: "The authoritative adapter could not read this resource.",
    savedFailureTitle: "Saved failure record",
    savedFailureBody: "This result was unavailable when generated. The saved record below preserves the original failure reason; it is not a successful risk assessment.",
    degradedTitle: "Result detail is degraded",
    degradedBody: "Readable evidence is shown with its exact limitations and warnings.",
    payloadWithheld: "Payload withheld",
  },
  zh: {
    back: "返回统一结果",
    status: "状态",
    read: "读取",
    freshness: "新鲜度",
    source: "来源",
    authority: "原始记录来源",
    occurredAt: "发生时间",
    resourceId: "资源编号",
    provenance: "来源记录",
    detailHref: "统一详情端点",
    originalHref: "原始资源端点",
    openOriginal: "打开原始结果界面",
    runLinks: "Hermes 精确运行关联",
    runLinksHint: "按平台资源精确身份记录的因果关联。",
    runLinksUnavailable: "精确关联权威当前不可用，因此无法判定该资源是否存在 Hermes 运行关联。",
    noRunLinks: "精确关联查询已完成，该资源没有记录 Hermes 运行关联。",
    command: "命令",
    relation: "关系",
    session: "Hermes 会话",
    run: "Hermes 运行",
    digest: "关联摘要",
    sourceEvent: "来源事件",
    observed: "记录时间",
    resource: "原始内容",
    resourceHint: "下面是已保存的原始数据，供核对；读取不会更改记录。",
    missingTitle: "结果资源不存在",
    missingBody: "该类型与资源 ID 没有对应的权威资源。",
    corruptTitle: "结果资源已损坏",
    corruptBody: "完整性校验失败，相关载荷不会作为证据展示。",
    unavailableTitle: "结果来源不可用",
    unavailableBody: "权威资源适配器当前无法读取该资源。",
    savedFailureTitle: "已保存的失败记录",
    savedFailureBody: "这次任务生成结果时未成功。下面保留当时的失败原因，不代表已经得到有效评估。",
    degradedTitle: "结果详情已降级",
    degradedBody: "仍可读取的证据会连同精确限制与警告一起展示。",
    payloadWithheld: "载荷已安全隐藏",
  },
} as const;

const focusClass =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info";

function RunLinkEvidence({
  link,
  locale,
}: {
  link: HermesResultRunLink;
  locale: Locale;
}) {
  const text = copy[locale];
  const fields = [
    [text.command, link.command_id],
    [text.relation, link.relation],
    [text.session, link.hermes_session_id],
    [text.run, link.hermes_run_id],
    [text.digest, link.link_digest],
    ...(link.source_event_id
      ? ([[text.sourceEvent, link.source_event_id]] as const)
      : []),
    [text.observed, link.observed_at],
  ] as const;
  return (
    <li className="rounded-lg border border-border-subtle bg-bg-surface-muted p-3">
      <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {fields.map(([label, value]) => (
          <div className="min-w-0" key={label}>
            <dt className="font-label-caps text-text-secondary">{label}</dt>
            <dd className="mt-1 break-all font-data-mono text-xs text-text-primary">{value}</dd>
          </div>
        ))}
      </dl>
    </li>
  );
}

export function UnifiedResultDetail({
  envelope,
  locale,
  backHref,
  originalResourceHref = null,
}: UnifiedResultDetailProps) {
  const text = copy[locale];
  const item = envelope.item;

  if (!item) {
    const failureStatus = envelope.apiError ? "unavailable" : envelope.read_status;
    const failureCopy =
      failureStatus === "missing"
        ? { title: text.missingTitle, body: text.missingBody }
        : failureStatus === "corrupt"
          ? { title: text.corruptTitle, body: text.corruptBody }
          : { title: text.unavailableTitle, body: text.unavailableBody };
    return (
      <section
        className="space-y-4"
        data-hermes-result-detail-failure={failureStatus}
        role="alert"
      >
        {/* Plain anchor on purpose: back navigation must stay a real document
            navigation even when the client router is unhealthy (a soft
            navigation that never resolves must not swallow this control). */}
        <a
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg px-2 font-body-sm text-info hover:bg-info/10 ${focusClass}`}
          data-hermes-result-back
          href={backHref}
        >
          <ArrowLeft size={15} /> {text.back}
        </a>
        <Card tone="danger">
          <p className="font-body-sm font-semibold text-danger">{failureCopy.title}</p>
          <p className="mt-1 font-body-sm text-text-secondary">{failureCopy.body}</p>
          {failureStatus === "corrupt" ? (
            <p className="mt-2 font-body-sm font-semibold text-danger">
              {text.payloadWithheld}
            </p>
          ) : null}
          {envelope.apiError ? (
            <p className="mt-2 break-words font-data-mono text-xs text-danger">
              {envelope.apiError}
            </p>
          ) : null}
          {envelope.warnings.length ? (
            <ul className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
              {envelope.warnings.map((warning, index) => (
                <li key={`${warning.source}:${warning.code}:${warning.resource_id ?? index}`}>
                  {resultWarningText(warning, locale)}
                </li>
              ))}
            </ul>
          ) : null}
        </Card>
      </section>
    );
  }
  const runLinks = item.run_links ?? null;
  const hasSavedFailure = envelope.read_status === "unavailable" && envelope.resource !== null;

  return (
    <article
      className="space-y-4"
      data-hermes-result-detail={hermesResultKey(item)}
      data-hermes-result-detail-read-status={envelope.read_status}
    >
      {/* Plain anchor on purpose: back navigation must stay a real document
          navigation even when the client router is unhealthy (a soft
          navigation that never resolves must not swallow this control). */}
      <a
        className={`inline-flex min-h-11 items-center gap-2 rounded-lg px-2 font-body-sm text-info hover:bg-info/10 ${focusClass}`}
        data-hermes-result-back
        href={backHref}
      >
        <ArrowLeft size={15} /> {text.back}
      </a>

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="font-label-caps uppercase text-info">
              {resultKindLabel(item.kind, locale)}
            </p>
            <h1 className="mt-1 font-headline-lg text-text-primary">
              {resultDisplayTitle(item, locale)}
            </h1>
            {resultSummaryText(item, locale) ? (
              <p className="mt-2 max-w-3xl font-body-sm text-text-secondary">
                {resultSummaryText(item, locale)}
              </p>
            ) : null}
          </div>
          <div className="flex max-w-xl flex-wrap gap-1.5">
            {item.data_mode === "sample" && <StatusPill label="" value={locale === "zh" ? "样例数据 · 非真实表现" : "SAMPLE · NOT REAL PERFORMANCE"} tone="warning" />}
            <StatusPill label={text.status} value={resultStatusLabel(item.status, locale)} />
            <StatusPill
              label={text.read}
              value={resultReadStatusLabel(envelope.read_status, locale)}
              tone={resultReadStatusTone(envelope.read_status)}
            />
            <StatusPill
              label={text.freshness}
              value={resultFreshnessLabel(item.freshness, locale)}
              tone={resultFreshnessTone(item.freshness)}
            />
            <StatusPill label={text.source} value={resultSourceLabel(item.source, locale)} />
          </div>
        </div>
      </Card>

      {envelope.read_status !== "available" ? (
        <div
          data-hermes-result-detail-degraded={
            envelope.read_status === "degraded" ? "true" : undefined
          }
          role="status"
        >
          <Card tone={envelope.read_status === "degraded" ? "warning" : "danger"}>
            <p
              className={`font-body-sm font-semibold ${
                envelope.read_status === "degraded" ? "text-warning" : "text-danger"
              }`}
            >
              {envelope.read_status === "degraded"
                ? text.degradedTitle
                : envelope.read_status === "corrupt"
                  ? text.corruptTitle
                  : hasSavedFailure
                    ? text.savedFailureTitle
                  : text.unavailableTitle}
            </p>
            <p className="mt-1 font-body-sm text-text-secondary">
              {envelope.read_status === "degraded"
                ? text.degradedBody
                : envelope.read_status === "corrupt"
                  ? text.corruptBody
                  : hasSavedFailure
                    ? text.savedFailureBody
                  : text.unavailableBody}
            </p>
            {envelope.warnings.length ? (
              <ul className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
                {envelope.warnings.map((warning, index) => (
                  <li key={`${warning.source}:${warning.code}:${warning.resource_id ?? index}`}>
                    {resultWarningText(warning, locale)}
                  </li>
                ))}
              </ul>
            ) : null}
          </Card>
        </div>
      ) : null}

      <Card>
        <SectionTitle
          right={<Fingerprint className="text-text-secondary" size={17} />}
          title={text.provenance}
        />
        <dl className="grid gap-4 lg:grid-cols-2">
          <div>
            <dt className="font-label-caps text-text-secondary">{text.resourceId}</dt>
            <dd className="mt-1 break-all font-data-mono text-xs text-text-primary">
              {item.resource_id}
            </dd>
          </div>
          <div>
            <dt className="font-label-caps text-text-secondary">{text.authority}</dt>
            <dd className="mt-1 font-body-sm text-text-primary">
              {resultAuthorityLabel(item.authority, locale)}
            </dd>
          </div>
          <div>
            <dt className="font-label-caps text-text-secondary">{text.occurredAt}</dt>
            <dd className="mt-1 font-data-mono text-xs text-text-primary">
              <time dateTime={item.occurred_at}>{formatDateTime(item.occurred_at, locale)}</time>
            </dd>
          </div>
          <div className="min-w-0">
            <dt className="font-label-caps text-text-secondary">{text.detailHref}</dt>
            <dd className="mt-1 break-all font-data-mono text-xs text-text-primary">
              {item.detail_href}
            </dd>
          </div>
          <div className="min-w-0">
            <dt className="font-label-caps text-text-secondary">{text.originalHref}</dt>
            <dd className="mt-1 break-all font-data-mono text-xs text-text-primary">
              {item.original_href}
            </dd>
          </div>
        </dl>
        {originalResourceHref ? (
          <Link
            className={`mt-4 inline-flex min-h-11 items-center gap-2 rounded-lg border border-info/40 bg-info/5 px-3 font-data-mono text-xs text-info hover:bg-info/10 ${focusClass}`}
            href={originalResourceHref}
            prefetch={false}
          >
            <ExternalLink size={14} /> {text.openOriginal}
          </Link>
        ) : null}
      </Card>

      <Card>
        <SectionTitle
          hint={text.runLinksHint}
          right={<Link2 className="text-text-secondary" size={17} />}
          title={text.runLinks}
        />
        {runLinks === null ? (
          <p
            className="font-body-sm text-warning"
            data-hermes-result-run-links-unavailable
          >
            {text.runLinksUnavailable}
          </p>
        ) : runLinks.length ? (
          <ol className="space-y-2" data-hermes-result-run-links>
            {runLinks.map((link) => (
              <RunLinkEvidence
                key={`${link.command_id}:${link.relation}:${link.hermes_run_id}`}
                link={link}
                locale={locale}
              />
            ))}
          </ol>
        ) : (
          <p
            className="font-body-sm text-text-secondary"
            data-hermes-result-run-links-empty
          >
            {text.noRunLinks}
          </p>
        )}
      </Card>

      <Card>
        <SectionTitle
          hint={text.resourceHint}
          right={<Braces className="text-text-secondary" size={17} />}
          title={text.resource}
        />
        {envelope.resource &&
        (envelope.read_status === "available" || envelope.read_status === "degraded" || hasSavedFailure) ? (
          <pre
            aria-label={text.resource}
            className={`max-h-[38rem] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border-subtle bg-bg-base p-4 font-code-sm text-text-primary ${focusClass}`}
            data-hermes-result-resource
            tabIndex={0}
          >
            {JSON.stringify(envelope.resource, null, 2)}
          </pre>
        ) : (
          <div className="rounded-lg border border-danger/30 bg-danger/5 p-3">
            <p className="font-body-sm font-semibold text-danger">{text.payloadWithheld}</p>
          </div>
        )}
      </Card>
    </article>
  );
}
