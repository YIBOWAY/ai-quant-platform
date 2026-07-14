"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import type {
  AgentReviewResponse,
  CandidateSummary,
} from "@/lib/api";
import { getAgentCandidateDetail } from "@/lib/api";
import { ApiClientError, apiPost } from "@/lib/apiClient";
import {
  canReviewCandidateDetail,
  listRowShowsGate2Controls,
} from "@/lib/hermes/gate2Review";
import { useIsHydrated } from "@/lib/hydration";
import type { Locale } from "@/lib/locale";
import { TerminalToolbarButton, terminalInputClass } from "@/components/ui/primitives";

const copy = {
  en: {
    approve: "Approve",
    reject: "Reject",
    approveTitle: "Approve candidate (Gate 2 CAS)",
    rejectTitle: "Reject candidate (Gate 2 CAS)",
    approveNote:
      "Approving writes an `approved.lock` only after binding the re-fetched detail digest + pending status. It does NOT register the factor.",
    rejectNote:
      "Rejecting writes a `rejected.lock` only after binding the re-fetched detail digest + pending status.",
    reviewNote: "Review note (required)",
    cancel: "Cancel",
    writingLock: "Writing lock…",
    confirm: "Confirm",
    approvedToast: "Approved",
    rejectedToast: "Rejected",
    loadingDetail: "Loading candidate detail…",
    reviewDisabled:
      "Approve/reject disabled until a verified pending detail with an authoritative digest is available.",
    migrationEvidence: "Migration evidence only — cannot approve.",
    corruptEvidence: "Integrity failed — cannot approve.",
    digestLabel: "manifest digest",
    noteRequired: "Enter a non-empty review note before confirming.",
  },
  zh: {
    approve: "批准",
    reject: "拒绝",
    approveTitle: "批准候选（Gate 2 CAS）",
    rejectTitle: "拒绝候选（Gate 2 CAS）",
    approveNote:
      "批准会在绑定重新拉取的详情 digest 与 pending 状态后写入 `approved.lock`，不会自动注册因子。",
    rejectNote:
      "拒绝会在绑定重新拉取的详情 digest 与 pending 状态后写入 `rejected.lock`。",
    reviewNote: "复核备注（必填）",
    cancel: "取消",
    writingLock: "正在写入锁文件……",
    confirm: "确认",
    approvedToast: "已批准",
    rejectedToast: "已拒绝",
    loadingDetail: "正在加载候选详情……",
    reviewDisabled:
      "在获得已验证、pending 且带权威 digest 的详情之前，批准/拒绝不可用。",
    migrationEvidence: "迁移证据，不能审批",
    corruptEvidence: "完整性失败，不能审批",
    digestLabel: "manifest digest",
    noteRequired: "确认前必须填写非空复核备注。",
  },
} as const;

const reviewSchema = z.object({
  note: z.string().min(1, "Review note is required").max(2000),
});

type ReviewValues = z.infer<typeof reviewSchema>;
type ReviewDecision = "approve" | "reject";

function Gate2ReviewDialog({
  candidate,
  decision,
  locale = "en",
}: {
  candidate: CandidateSummary;
  decision: ReviewDecision;
  locale?: Locale;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const isHydrated = useIsHydrated();
  const text = copy[locale];
  const form = useForm<ReviewValues>({
    resolver: zodResolver(reviewSchema),
    defaultValues: { note: "" },
  });
  const noteValue = form.watch("note");

  const detailQuery = useQuery({
    queryKey: ["hermes-gate2-candidate-detail", candidate.candidate_id],
    queryFn: () => getAgentCandidateDetail(candidate.candidate_id),
    enabled: open && isHydrated,
    staleTime: 0,
    refetchOnMount: "always",
  });

  const detail = detailQuery.data;
  const reviewReady = canReviewCandidateDetail(detail);

  const mutation = useMutation({
    mutationFn: (values: ReviewValues) => {
      // Always re-validate the latest detail object; digest comes only from detail.
      if (!canReviewCandidateDetail(detail)) {
        throw new Error("candidate detail is not reviewable");
      }
      return apiPost<AgentReviewResponse>(
        `/api/agent/candidates/${candidate.candidate_id}/review`,
        {
          decision,
          note: values.note,
          expected_manifest_digest: detail.manifest_digest,
          expected_status: "pending" as const,
        },
      );
    },
    onSuccess: () => {
      toast.success(
        `${decision === "approve" ? text.approvedToast : text.rejectedToast} ${candidate.candidate_id}`,
      );
      form.reset({ note: "" });
      setOpen(false);
      router.refresh();
    },
  });

  const error =
    mutation.error instanceof ApiClientError
      ? mutation.error.message
      : mutation.error instanceof Error
        ? mutation.error.message
        : detailQuery.error instanceof Error
          ? detailQuery.error.message
          : detail?.apiError;

  const writeReview = form.handleSubmit((values) => mutation.mutate(values));
  const noteEmpty = !noteValue?.trim();
  const controlsDisabled =
    !isHydrated ||
    !reviewReady ||
    noteEmpty ||
    mutation.isPending ||
    detailQuery.isLoading ||
    detailQuery.isFetching;

  const openDialog = () => {
    form.reset({ note: "" });
    setOpen(true);
  };

  return (
    <>
      <TerminalToolbarButton
        className="app-touch-target h-11 min-h-[44px] flex-1"
        disabled={!isHydrated || !listRowShowsGate2Controls(candidate)}
        onClick={openDialog}
        title={decision === "approve" ? text.approve : text.reject}
        tone={decision === "approve" ? "info" : "danger"}
      >
        {decision === "approve" ? text.approve : text.reject}
      </TerminalToolbarButton>
      {open ? (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-4">
          <div
            className="w-full max-w-lg rounded-lg border border-info/40 bg-bg-surface p-5"
            data-hermes-gate2-dialog={decision}
            role="alertdialog"
            aria-modal="true"
          >
            <h3 className="font-headline-lg text-text-primary">
              {decision === "approve" ? text.approveTitle : text.rejectTitle}
            </h3>
            <p className="mt-2 truncate font-data-mono text-xs text-text-secondary">
              {candidate.candidate_id}
            </p>
            {decision === "approve" ? (
              <p className="mt-3 rounded-lg border border-info/40 bg-info/5 p-3 font-body-sm text-info">
                {text.approveNote}
              </p>
            ) : (
              <p className="mt-3 rounded-lg border border-border-subtle bg-bg-surface-muted p-3 font-body-sm text-text-secondary">
                {text.rejectNote}
              </p>
            )}
            {detailQuery.isLoading || detailQuery.isFetching ? (
              <p className="mt-3 font-body-sm text-text-secondary">{text.loadingDetail}</p>
            ) : null}
            {detail && !reviewReady ? (
              <p className="mt-3 rounded-lg border border-danger/40 bg-danger/5 p-3 font-body-sm text-danger">
                {detail.integrity_state === "migration_required"
                  ? text.migrationEvidence
                  : detail.integrity_state === "corrupt"
                    ? text.corruptEvidence
                    : text.reviewDisabled}
                {detail.observed_manifest_digest
                  ? ` observed=${detail.observed_manifest_digest}`
                  : ""}
                {detail.apiError ? ` (${detail.apiError})` : ""}
              </p>
            ) : null}
            {reviewReady ? (
              <p
                className="mt-3 break-all font-data-mono text-[10px] text-text-secondary"
                data-hermes-gate2-detail-digest
              >
                {text.digestLabel}: {detail.manifest_digest}
              </p>
            ) : null}
            <form
              className="mt-4 flex flex-col gap-3"
              onSubmit={(event) => event.preventDefault()}
            >
              <label className="flex flex-col gap-1 font-body-sm text-text-primary">
                {text.reviewNote}
                <textarea
                  className={`min-h-24 ${terminalInputClass}`}
                  data-hermes-gate2-note
                  disabled={!reviewReady}
                  {...form.register("note")}
                />
              </label>
              {reviewReady && noteEmpty ? (
                <p className="font-body-sm text-text-secondary">{text.noteRequired}</p>
              ) : null}
              {error ? <p className="font-body-sm text-danger">{error}</p> : null}
              <div className="flex justify-end gap-2">
                <TerminalToolbarButton
                  className="app-touch-target min-h-[44px]"
                  onClick={() => setOpen(false)}
                  tone="neutral"
                >
                  {text.cancel}
                </TerminalToolbarButton>
                <TerminalToolbarButton
                  className="app-touch-target min-h-[44px]"
                  disabled={controlsDisabled}
                  onClick={() => void writeReview()}
                  title={text.confirm}
                  tone="info"
                >
                  {mutation.isPending ? text.writingLock : text.confirm}
                </TerminalToolbarButton>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}

/**
 * Hermes Approvals Gate 2 entry controls.
 * Shows Approve/Reject only for list rows that advertise approval_enabled +
 * verified pending; the mutation always re-fetches detail digest.
 */
export function HermesGate2ReviewControls({
  candidate,
  locale = "en",
}: {
  candidate: CandidateSummary;
  locale?: Locale;
}) {
  if (!listRowShowsGate2Controls(candidate)) {
    return null;
  }

  return (
    <div
      className="mt-3 flex gap-2"
      data-hermes-gate2-controls
      data-hermes-gate2-candidate={candidate.candidate_id}
    >
      <Gate2ReviewDialog candidate={candidate} decision="approve" locale={locale} />
      <Gate2ReviewDialog candidate={candidate} decision="reject" locale={locale} />
    </div>
  );
}
