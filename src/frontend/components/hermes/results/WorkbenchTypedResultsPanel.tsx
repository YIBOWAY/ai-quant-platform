'use client';

import { useMemo } from "react";

import { Panel } from "@/components/ui/Panel";
import {
  displayId,
  LONG_ID_CLASS,
} from "@/lib/hermes/workbenchA11y";
import type { WorkspaceResultProjection } from "@/lib/hermes/workspaceClient";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import type { Locale } from "@/lib/locale";

export type WorkbenchTypedResultsPanelProps = {
  locale: Locale;
};

/** Only exact "real" is real; unknown/typo/missing → sample (fail-closed). */
export function isSample(row: WorkspaceResultProjection): boolean {
  return (row.sample_or_real || "").toLowerCase() !== "real";
}

export function isReal(row: WorkspaceResultProjection): boolean {
  return (row.sample_or_real || "").toLowerCase() === "real";
}

/** Pure filter helper for tests — newest-first already from spine. */
export function filterResultsForPanel(
  rows: WorkspaceResultProjection[],
): WorkspaceResultProjection[] {
  return rows.filter((row) => Boolean(row.result_id || row.id));
}

export function resultRowKey(row: WorkspaceResultProjection): string {
  return row.result_id || row.id || "";
}

function num(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  return String(value);
}

/**
 * V7f-Typed-Results-M1: hermetic typed results on the workbench spine.
 * Separate from Gate/Approvals panels and from /hermes/results catalog pages.
 * Empty is honest. sample vs real is always visible. Exact links only when present.
 * Markers: data-hermes-typed-results-*=v7f-m1
 */
export function WorkbenchTypedResultsPanel({
  locale,
}: WorkbenchTypedResultsPanelProps) {
  const isZh = locale === "zh";
  const { state: follow } = useWorkspaceFollow();

  const results = useMemo(() => {
    const raw = Array.isArray(follow.results)
      ? (follow.results as WorkspaceResultProjection[])
      : [];
    // Coerce any residual bare strings from older spine states.
    const normalized: WorkspaceResultProjection[] = raw.map((item) => {
      if (typeof item === "string") {
        return {
          result_id: item,
          id: item,
          kind: "generic",
          display_title: item,
          sample_or_real: "sample",
        };
      }
      return item;
    });
    return filterResultsForPanel(normalized);
  }, [follow.results]);

  const health = follow.snapshotCursor != null || follow.transport !== "idle";
  const resultHealth = follow.authorityHealth?.result ?? "unavailable";
  const showEmpty = health && results.length === 0;

  return (
    <Panel
      count={results.length}
      data-hermes-typed-results=""
      data-hermes-typed-results-observe="v7f-m1"
      data-hermes-typed-results-projector="v7f-m1"
      data-hermes-typed-results-presenter="v7f-m1"
      data-hermes-result-health={resultHealth}
      empty={
        isZh
          ? "当前无类型化结果。空列表诚实——不会把 command / Gate / 审批伪装成结果。"
          : "No typed results. Empty is honest — commands, Gates, and approvals are never dressed as results."
      }
      headerExtra={
        <span
          className="font-body-sm text-text-secondary"
          data-hermes-typed-results-count
        >
          {resultHealth === "ready"
            ? isZh
              ? "投影就绪"
              : "projector ready"
            : isZh
              ? "未就绪"
              : "unavailable"}
        </span>
      }
      isEmpty={showEmpty}
      title={isZh ? "类型化结果" : "Typed results"}
    >
      <div data-hermes-typed-results-body id="hermes-typed-results-body">
        <p className="font-body-sm text-text-secondary break-words">
          {isZh
            ? "V7f 类型化结果：与 Gate / command-approval 分离。sample/real 醒目标记；仅展示已知 exact Task/Attempt/Run/artifact 链接；空列表诚实。hermetic ≠ 实盘行情。"
            : "V7f typed results: separate from Gate / command-approval. sample/real is always marked; exact Task/Attempt/Run/artifact links only when known; empty is honest. Hermetic ≠ live quotes."}
        </p>

        <ul
          className="mt-2 divide-y divide-border-subtle border-t border-border-subtle"
          data-hermes-typed-results-list
        >
          {results.map((row) => {
            const key = resultRowKey(row);
            const sample = isSample(row);
            const links = row.exact_links || {};
            return (
              <li
                className="space-y-2 py-3"
                data-hermes-typed-result-row
                data-hermes-result-id={key}
                data-hermes-result-kind={row.kind}
                data-hermes-result-sample={sample ? "sample" : "real"}
                key={key}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="font-body-sm text-text-primary break-words">
                    {row.display_title || key}
                  </p>
                  <p
                    className={
                      sample
                        ? "rounded border border-warning/40 bg-warning/10 px-2 py-0.5 font-data-mono text-[11px] text-warning"
                        : "rounded border border-accent-success/40 bg-accent-success/10 px-2 py-0.5 font-data-mono text-[11px] text-accent-success"
                    }
                    data-hermes-result-mark
                  >
                    {sample
                      ? isZh
                        ? "SAMPLE · 样例"
                        : "SAMPLE"
                      : isZh
                        ? "REAL · 真实"
                        : "REAL"}
                  </p>
                </div>
                <p className={`${LONG_ID_CLASS} break-all`} title={key}>
                  {displayId(key)}
                </p>
                <p className="font-data-mono text-[11px] text-text-secondary">
                  {row.kind}
                  {row.status ? ` · ${row.status}` : ""}
                  {row.freshness ? ` · freshness=${row.freshness}` : ""}
                  {row.read_status ? ` · read=${row.read_status}` : ""}
                </p>
                {row.summary ? (
                  <p className="font-body-sm text-text-secondary break-words">
                    {row.summary}
                  </p>
                ) : null}

                {/* Vertical A options fields */}
                {row.kind === "options_vertical_a" ||
                row.ticker ||
                row.expiry ||
                row.strike != null ? (
                  <dl
                    className="grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-4"
                    data-hermes-result-options-fields
                  >
                    {[
                      ["ticker", row.ticker],
                      ["expiry", row.expiry],
                      ["strike", num(row.strike)],
                      ["bid", num(row.bid)],
                      ["ask", num(row.ask)],
                      ["delta", num(row.delta)],
                      ["iv", num(row.iv)],
                      ["apr", num(row.apr)],
                    ].map(([label, value]) =>
                      value ? (
                        <div key={String(label)}>
                          <dt className="font-data-mono text-[10px] uppercase tracking-wide text-text-secondary">
                            {label}
                          </dt>
                          <dd className="font-data-mono text-[12px] text-text-primary">
                            {value}
                          </dd>
                        </div>
                      ) : null,
                    )}
                  </dl>
                ) : null}

                {row.filters && row.filters.length ? (
                  <p
                    className="font-body-sm text-text-secondary break-words"
                    data-hermes-result-filters
                  >
                    filters: {row.filters.join(", ")}
                  </p>
                ) : null}
                {row.exclusions && row.exclusions.length ? (
                  <p
                    className="font-body-sm text-text-secondary break-words"
                    data-hermes-result-exclusions
                  >
                    exclusions: {row.exclusions.join(", ")}
                  </p>
                ) : null}
                {row.limitations && row.limitations.length ? (
                  <p
                    className="font-body-sm text-text-secondary break-words"
                    data-hermes-result-limitations
                  >
                    limitations: {row.limitations.join(", ")}
                  </p>
                ) : null}
                {row.provider_evidence && row.provider_evidence.length ? (
                  <p
                    className="font-data-mono text-[11px] text-text-secondary break-all"
                    data-hermes-result-evidence
                  >
                    evidence: {row.provider_evidence.join(" · ")}
                  </p>
                ) : null}

                {/* Exact links — only known ids */}
                {links.task_ref ||
                links.attempt_ref ||
                links.run_ref ||
                links.artifact_ref ||
                links.command_id ||
                row.task_id ||
                row.run_id ? (
                  <ul
                    className="space-y-0.5 font-data-mono text-[11px] text-text-secondary"
                    data-hermes-result-exact-links
                  >
                    {(links.task_ref || row.task_id) && (
                      <li>task: {links.task_ref || row.task_id}</li>
                    )}
                    {(links.attempt_ref || row.attempt_id) && (
                      <li>attempt: {links.attempt_ref || row.attempt_id}</li>
                    )}
                    {(links.run_ref || row.run_id) && (
                      <li>run: {links.run_ref || row.run_id}</li>
                    )}
                    {(links.artifact_ref || row.artifact_id) && (
                      <li>
                        artifact: {links.artifact_ref || row.artifact_id}
                      </li>
                    )}
                    {(links.command_id || row.command_id) && (
                      <li>command: {links.command_id || row.command_id}</li>
                    )}
                  </ul>
                ) : null}

                {row.occurred_at ? (
                  <p className="font-data-mono text-[11px] text-text-secondary">
                    occurred: {row.occurred_at}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      </div>
    </Panel>
  );
}
