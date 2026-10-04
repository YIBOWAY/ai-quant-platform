"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FlaskConical, Search } from "lucide-react";

import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { Card, ToneBadge } from "@/components/ui/primitives";
import { ApiClientError } from "@/lib/apiClient";
import type { Locale } from "@/lib/locale";
import { candidatePresentation } from "@/lib/hermes/candidatePresentation";
import {
  hangLibraryCandidate,
  loadVerifiedLibraryCandidates,
  resolveLibraryHangOutcome,
  type LibraryHangResolution,
  type VerifiedLibraryCandidate,
} from "@/lib/researchLibrary";

const copy = {
  en: {
    search: "Search verified candidates",
    searchPlaceholder: "Candidate, factor, objective or symbol…",
    loading: "Loading verified candidates…",
    empty: "No unbound verified candidate is available.",
    noMatch: "No verified candidate matches this search.",
    verified: "Verified candidate",
    reviewOnly: "Research review only",
    scope: "Symbols",
    technical: "Technical details",
    candidateId: "Candidate ID",
    factorId: "Factor ID",
    fingerprint: "Source fingerprint",
    sleeveId: "Strategy sleeve ID",
    enter: "Enable simulated running",
    recover: "Resume simulated running",
    activationHint: "Allocates USD 10,000 in simulated funds and runs automatically from daily signals.",
    recoveryHint: "Restores the existing USD 10,000 simulated sleeve without allocating it again.",
    pending: "Enabling…",
    hung: "Simulated run active",
    alreadyHung: "Simulated run active",
    readError: "The verified-candidate book is unavailable. No preview data was substituted.",
    hangUnknown: "Activation outcome unknown. Refresh and verify the candidate book before trying again.",
    refreshBook: "Refresh candidate book",
    resolvedHung: "Refresh confirmed that this exact candidate is running in simulation.",
    stillVerified: "Refresh confirmed that this candidate is research-verified but not enabled.",
    stillUnknown: "This candidate still cannot be resolved. Do not resubmit.",
  },
  zh: {
    search: "搜索已验证候选",
    searchPlaceholder: "候选、因子、研究目标或标的…",
    loading: "正在加载已验证候选…",
    empty: "当前没有未绑定的已验证候选。",
    noMatch: "没有匹配搜索条件的已验证候选。",
    verified: "已验证候选",
    reviewOnly: "仅供研究复核",
    scope: "标的范围",
    technical: "技术信息",
    candidateId: "候选编号",
    factorId: "因子编号",
    fingerprint: "来源校验指纹",
    sleeveId: "策略仓编号",
    enter: "启用模拟运行",
    recover: "恢复模拟运行",
    activationHint: "将分配 10,000 美元模拟资金，并按每日信号自动运行。",
    recoveryHint: "恢复现有的 10,000 美元策略仓，不会重复分配资金。",
    pending: "正在启用…",
    hung: "模拟运行中",
    alreadyHung: "模拟运行中",
    readError: "已验证候选账当前不可用；页面没有用预览数据替代。",
    hangUnknown: "启用结果未知。请先刷新并核对候选账，不要重复提交。",
    refreshBook: "刷新候选账",
    resolvedHung: "刷新已确认：这个候选正在模拟运行。",
    stillVerified: "刷新已确认：该候选已完成研究验证，但尚未启用模拟运行。",
    stillUnknown: "仍无法确认该候选状态，请勿重复提交。",
  },
} as const;

function activationErrorText(error: unknown, locale: Locale): string {
  const code =
    error && typeof error === "object" && "code" in error
      ? String((error as { code?: unknown }).code ?? "")
      : undefined;
  if (code === "paper_account_allocation_ledger_invalid") {
    return locale === "zh"
      ? "模拟账户的策略资金流水需要修复，暂时不能启用新的模拟运行。"
      : "The paper account allocation ledger needs repair before another simulated run can be enabled.";
  }
  if (code === "cost_sensitivity_failed") {
    return locale === "zh"
      ? "计入交易成本后，这个候选暂不适合启用模拟运行。"
      : "This candidate is not suitable for simulated running after trading costs.";
  }
  if (code === "hang_insufficient_funds") {
    return locale === "zh"
      ? "可分配的美元模拟资金不足，当前不能启用这条模拟运行。"
      : "There is not enough unallocated USD paper cash to enable this simulated run.";
  }
  if (
    code &&
    [
      "candidate_not_found",
      "candidate_source_digest_mismatch",
      "candidate_not_verified",
      "hung_sleeve_missing",
      "hung_sleeve_digest_mismatch",
    ].includes(code)
  ) {
    return locale === "zh"
      ? "候选状态已经变化，请刷新候选库后再试。"
      : "The candidate changed. Refresh the library before trying again.";
  }
  return locale === "zh"
    ? "暂时无法启用模拟运行，请刷新候选库后再试。"
    : "Simulated running could not be enabled. Refresh the library and try again.";
}

function searchText(candidate: VerifiedLibraryCandidate): string {
  return [
    candidate.candidate_id,
    candidate.factor_id ?? "",
    candidate.objective ?? "",
    candidate.display_name ?? "",
    candidate.display_name_zh ?? "",
    candidate.summary_zh ?? "",
    ...(candidate.universe ?? []),
  ]
    .join("\n")
    .toLowerCase();
}

export function LibraryWorkbench({ locale, initialCandidate = "" }: { locale: Locale; initialCandidate?: string }) {
  const text = copy[locale];
  const queryClient = useQueryClient();
  const [query, setQuery] = useState(initialCandidate);
  const [hangResolution, setHangResolution] = useState<LibraryHangResolution | null>(null);
  const libraryQuery = useQuery({
    queryKey: ["assistant-remote-book", "verified-library"],
    queryFn: loadVerifiedLibraryCandidates,
    refetchInterval: 15_000,
    retry: false,
  });
  const hangMutation = useMutation({
    mutationFn: hangLibraryCandidate,
    retry: false,
    onMutate: () => setHangResolution(null),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["assistant-remote-book"] });
    },
  });
  const resolutionMutation = useMutation({
    mutationFn: resolveLibraryHangOutcome,
    retry: false,
    onSuccess: async (resolution) => {
      setHangResolution(resolution);
      if (resolution !== "still_unknown") {
        await queryClient.invalidateQueries({ queryKey: ["assistant-remote-book"] });
        hangMutation.reset();
      }
    },
    onError: () => setHangResolution("still_unknown"),
  });

  const normalizedQuery = query.trim().toLowerCase();
  const candidates = useMemo(
    () =>
      (libraryQuery.data ?? []).filter(
        (candidate) => !normalizedQuery || searchText(candidate).includes(normalizedQuery),
      ),
    [libraryQuery.data, normalizedQuery],
  );
  const pendingCandidateId = hangMutation.isPending
    ? hangMutation.variables?.candidate_id
    : null;
  const hangOutcomeUnknown =
    hangMutation.error instanceof ApiClientError &&
    hangMutation.error.outcome === "outcome_unknown";
  const unknownCandidate = hangOutcomeUnknown ? hangMutation.variables : null;

  return (
    <section aria-label={text.search}>
      <label className="relative block max-w-xl">
        <span className="sr-only">{text.search}</span>
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary"
          size={15}
        />
        <input
          aria-label={text.search}
          className="app-touch-target w-full rounded-lg border border-border-subtle bg-bg-surface pl-9 pr-3 font-body-sm text-text-primary outline-none focus:border-info focus-visible:ring-2 focus-visible:ring-info"
          onChange={(event) => setQuery(event.target.value)}
          placeholder={text.searchPlaceholder}
          type="search"
          value={query}
        />
      </label>

      {libraryQuery.isError ? (
        <Card className="mt-4" role="alert" tone="danger">
          <p className="font-body-sm text-danger">{text.readError}</p>
        </Card>
      ) : null}

      {hangMutation.isError ? (
        <div
          aria-live="assertive"
          className="mt-4 rounded-lg border border-danger/40 bg-danger/5 p-3 font-body-sm text-danger"
          role="alert"
        >
          <p>
            {hangOutcomeUnknown
              ? text.hangUnknown
              : activationErrorText(hangMutation.error, locale)}
          </p>
          {hangOutcomeUnknown ? (
            <button
              className="app-touch-target mt-2 rounded-md border border-danger/40 px-3 font-semibold"
              disabled={resolutionMutation.isPending || !unknownCandidate}
              onClick={() => {
                if (unknownCandidate) resolutionMutation.mutate(unknownCandidate);
              }}
              type="button"
            >
              {text.refreshBook}
            </button>
          ) : null}
        </div>
      ) : null}

      {hangResolution ? (
        <p className="mt-4 font-body-sm text-text-primary" role="status">
          {hangResolution === "resolved_hung"
            ? text.resolvedHung
            : hangResolution === "still_verified"
              ? text.stillVerified
              : text.stillUnknown}
        </p>
      ) : null}

      {hangMutation.data ? (
        <div
          className="mt-4 rounded-lg border border-accent-success/30 bg-accent-success/5 p-3 font-body-sm text-accent-success"
          role="status"
        >
          {hangMutation.data.already_hung ? (
            <span data-hang-state="already_hung">{text.alreadyHung}</span>
          ) : (
            <span data-hang-state="hung">{text.hung}</span>
          )}
          {hangMutation.data.sleeve_id ? (
            <details className="mt-2 text-text-secondary">
              <summary className="cursor-pointer">{text.technical}</summary>
              <p className="mt-1 break-all font-data-mono text-xs">
                {text.sleeveId}: {hangMutation.data.sleeve_id}
              </p>
            </details>
          ) : null}
        </div>
      ) : null}

      {libraryQuery.isLoading ? (
        <div aria-label={text.loading} className="mt-4" role="status">
          <LoadingSkeleton rows={4} />
          <span className="sr-only">{text.loading}</span>
        </div>
      ) : null}

      {!libraryQuery.isLoading && !libraryQuery.isError && candidates.length === 0 ? (
        <Card className="mt-4 text-center">
          <FlaskConical aria-hidden="true" className="mx-auto text-text-secondary" size={22} />
          <p className="mt-2 font-body-sm text-text-secondary">
            {(libraryQuery.data ?? []).length === 0 ? text.empty : text.noMatch}
          </p>
        </Card>
      ) : null}

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        {candidates.map((candidate) => {
          const presentation = candidatePresentation(candidate, locale);
          const activationEligible = candidate.activation_eligibility.eligible;
          const recoveryAvailable =
            candidate.activation_eligibility.reason === "recovery_available";
          const pending = pendingCandidateId === candidate.candidate_id;
          const pendingStatusId = `hang-pending-${candidate.candidate_id}`;
          return (
            <Card className="flex min-h-64 flex-col" key={candidate.candidate_id}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <ToneBadge tone={activationEligible ? "success" : "warning"}>
                    {activationEligible ? text.verified : text.reviewOnly}
                  </ToneBadge>
                  <h2 className="mt-3 break-words font-headline-sm text-text-primary">
                    {presentation.name}
                  </h2>
                </div>
                {activationEligible ? (
                  <CheckCircle2
                    aria-hidden="true"
                    className="shrink-0 text-accent-success"
                    size={18}
                  />
                ) : (
                  <FlaskConical
                    aria-hidden="true"
                    className="shrink-0 text-warning"
                    size={18}
                  />
                )}
              </div>

              <p className="mt-4 line-clamp-3 font-body-sm text-text-secondary">
                {presentation.summary}
              </p>
              {presentation.activationNote ? (
                <p className="mt-3 font-body-sm text-warning">
                  {presentation.activationNote}
                </p>
              ) : null}
              <dl className="mt-4 border-t border-border-subtle pt-3">
                <div>
                  <dt className="font-label-caps text-text-secondary">{text.scope}</dt>
                  <dd className="mt-1 break-words font-data-mono text-xs text-text-primary">
                    {(candidate.universe ?? []).join(" · ") || "—"}
                  </dd>
                </div>
              </dl>
              <details className="mt-3 border-t border-border-subtle pt-3 font-body-sm text-text-secondary">
                <summary className="cursor-pointer select-none">{text.technical}</summary>
                <dl className="mt-2 grid gap-2 sm:grid-cols-2">
                  <div>
                    <dt className="font-label-caps">{text.candidateId}</dt>
                    <dd className="break-all font-data-mono text-xs">{candidate.candidate_id}</dd>
                  </div>
                  <div>
                    <dt className="font-label-caps">{text.factorId}</dt>
                    <dd className="break-all font-data-mono text-xs">{candidate.factor_id ?? "—"}</dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="font-label-caps">{text.fingerprint}</dt>
                    <dd className="break-all font-data-mono text-xs">{candidate.source_digest}</dd>
                  </div>
                </dl>
              </details>

              {activationEligible ? (
                <div className="mt-auto pt-5">
                  <p className="mb-2 font-body-sm text-text-secondary">
                    {recoveryAvailable ? text.recoveryHint : text.activationHint}
                  </p>
                  <button
                    aria-label={`${recoveryAvailable ? text.recover : text.enter}: ${presentation.name}`}
                    aria-busy={pending}
                    aria-describedby={pending ? pendingStatusId : undefined}
                    className="app-touch-target inline-flex items-center justify-center rounded-lg border border-info/40 bg-info/5 px-4 font-body-sm font-semibold text-info transition-colors hover:bg-info/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={hangMutation.isPending || hangOutcomeUnknown}
                    onClick={() => hangMutation.mutate(candidate)}
                    type="button"
                  >
                    {pending ? (
                      <span data-hang-state="pending">{text.pending}</span>
                    ) : (
                      recoveryAvailable ? text.recover : text.enter
                    )}
                  </button>
                  {pending ? (
                    <p
                      aria-live="polite"
                      className="sr-only"
                      id={pendingStatusId}
                      role="status"
                    >
                      {`${text.pending}: ${presentation.name}`}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </Card>
          );
        })}
      </div>
    </section>
  );
}
