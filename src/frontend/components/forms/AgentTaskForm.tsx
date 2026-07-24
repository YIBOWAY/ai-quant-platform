'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import type {
  AgentCandidateDetailResponse,
  AgentReviewResponse,
  AgentTaskResponse,
  CandidateSummary,
} from "@/lib/api";
import { getAgentCandidateDetail } from "@/lib/api";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";
import type { Locale } from "@/lib/locale";
import {
  Card,
  SectionTitle,
  StatusPill,
  TerminalToolbarButton,
  terminalInputClass,
} from "@/components/ui/primitives";

const copy = {
  en: {
    approve: "Approve",
    reject: "Reject",
    approveTitle: "Approve candidate",
    rejectTitle: "Reject candidate",
    approveNote:
      "Approving creates an `approved.lock` file only. It does NOT register the factor automatically.",
    rejectNote: "Rejecting creates a `rejected.lock` file only.",
    reviewNote: "Review note",
    cancel: "Cancel",
    writingLock: "Writing lock...",
    confirm: "Confirm",
    approvedToast: "Approved",
    rejectedToast: "Rejected",
    runAgentTask: "Run Agent Task",
    taskType: "Task type",
    goal: "Goal",
    universe: "Universe",
    experimentId: "Experiment ID",
    factorId: "Factor ID",
    running: "Running...",
    runTask: "Run task",
    manualReview: "Manual Review",
    manualReviewNote:
      "Review writes lock files only after reading the selected candidate detail and binding both digest and pending status. It never registers a factor.",
    noCandidate: "No candidate available.",
    candidateCreatedToast: "Agent candidate created:",
    runTaskHint: "Generates an inert candidate file. Nothing is registered or executed.",
    status: "status",
    pendingReview: "pending review",
    loadingDetail: "Loading candidate detail…",
    reviewDisabled:
      "Approve/reject disabled until a verified pending detail with an authoritative digest is available.",
    migrationEvidence: "Migration evidence only — cannot approve.",
    digestLabel: "manifest digest",
  },
  zh: {
    approve: "批准",
    reject: "拒绝",
    approveTitle: "批准候选",
    rejectTitle: "拒绝候选",
    approveNote:
      "批准仅会创建一个 `approved.lock` 文件，不会自动注册该因子。",
    rejectNote: "拒绝仅会创建一个 `rejected.lock` 文件。",
    reviewNote: "复核备注",
    cancel: "取消",
    writingLock: "正在写入锁文件……",
    confirm: "确认",
    approvedToast: "已批准",
    rejectedToast: "已拒绝",
    runAgentTask: "运行智能体任务",
    taskType: "任务类型",
    goal: "目标",
    universe: "标的池",
    experimentId: "实验 ID",
    factorId: "因子 ID",
    running: "运行中……",
    runTask: "运行任务",
    manualReview: "人工复核",
    manualReviewNote:
      "复核会先读取候选详情并同时绑定 digest 与 pending 状态后才写入锁文件，绝不会注册因子。",
    noCandidate: "暂无可用候选。",
    candidateCreatedToast: "已创建智能体候选：",
    runTaskHint: "生成一个惰性候选文件，不会注册或执行任何内容。",
    status: "状态",
    pendingReview: "待复核",
    loadingDetail: "正在加载候选详情……",
    reviewDisabled: "在获得已验证、pending 且带权威 digest 的详情之前，批准/拒绝不可用。",
    migrationEvidence: "迁移证据，不能审批",
    digestLabel: "manifest digest",
  },
} as const;

const taskSchema = z.object({
  task_type: z.enum(["propose-factor", "propose-experiment", "summarize", "audit-leakage"]),
  goal: z.string(),
  universe: z.string().min(1),
  experiment_id: z.string(),
  factor_id: z.string(),
});

const reviewSchema = z.object({
  note: z.string().min(1, "Review note is required").max(2000),
});

type Tone = "neutral" | "success" | "warning" | "danger" | "info";
type TaskValues = z.infer<typeof taskSchema>;
type ReviewValues = z.infer<typeof reviewSchema>;
type ReviewDecision = "approve" | "reject";

function statusTone(status: string | null | undefined): Tone {
  const normalized = (status ?? "").toLowerCase();
  if (normalized === "approved") return "success";
  if (normalized === "rejected") return "danger";
  if (normalized === "pending") return "warning";
  return "neutral";
}

const fieldClass = terminalInputClass;

function canReview(detail: AgentCandidateDetailResponse | undefined): detail is AgentCandidateDetailResponse & {
  manifest_digest: string;
} {
  if (!detail) return false;
  if (detail.approval_enabled !== true) return false;
  if (detail.status !== "pending") return false;
  if (detail.integrity_state !== "verified") return false;
  if (detail.approval_binding !== "pending") return false;
  const digest = detail.manifest_digest;
  return typeof digest === "string" && /^[0-9a-f]{64}$/.test(digest);
}

function ReviewDialog({
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

  const detailQuery = useQuery({
    queryKey: ["agent-candidate-detail", candidate.candidate_id],
    queryFn: () => getAgentCandidateDetail(candidate.candidate_id),
    enabled: open && isHydrated,
    staleTime: 0,
    refetchOnMount: "always",
  });

  const detail = detailQuery.data;
  const reviewReady = canReview(detail);

  const mutation = useMutation({
    mutationFn: (values: ReviewValues) => {
      if (!canReview(detail)) {
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
          : undefined;
  const writeReview = form.handleSubmit((values) => mutation.mutate(values));
  const controlsDisabled =
    !isHydrated || !reviewReady || mutation.isPending || detailQuery.isLoading || detailQuery.isFetching;

  return (
    <>
      <TerminalToolbarButton
        className="h-9 flex-1"
        disabled={!isHydrated || candidate.approval_enabled !== true}
        onClick={() => setOpen(true)}
        tone={decision === "approve" ? "info" : "danger"}
      >
        {decision === "approve" ? text.approve : text.reject}
      </TerminalToolbarButton>
      {open ? (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-4">
          <div
            className="w-full max-w-lg rounded-lg border border-warning/40 bg-bg-surface p-5"
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
              <p className="mt-3 rounded-lg border border-warning/40 bg-warning/5 p-3 font-body-sm text-warning">
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
                  : text.reviewDisabled}
                {detail.observed_manifest_digest
                  ? ` observed=${detail.observed_manifest_digest}`
                  : ""}
              </p>
            ) : null}
            {reviewReady ? (
              <p className="mt-3 break-all font-data-mono text-[10px] text-text-secondary">
                {text.digestLabel}: {detail.manifest_digest}
              </p>
            ) : null}
            <form className="mt-4 flex flex-col gap-3" onSubmit={(event) => event.preventDefault()}>
              <label className="flex flex-col gap-1 font-body-sm text-text-primary">
                {text.reviewNote}
                <textarea
                  className={`min-h-24 ${fieldClass}`}
                  disabled={!reviewReady}
                  {...form.register("note")}
                />
              </label>
              {error ? <p className="font-body-sm text-danger">{error}</p> : null}
              <div className="flex justify-end gap-2">
                <TerminalToolbarButton onClick={() => setOpen(false)} tone="neutral">
                  {text.cancel}
                </TerminalToolbarButton>
                <TerminalToolbarButton
                  disabled={controlsDisabled}
                  onClick={() => void writeReview()}
                  tone="warning"
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

export function ApproveDialog({ candidate, locale }: { candidate: CandidateSummary; locale?: Locale }) {
  return <ReviewDialog candidate={candidate} decision="approve" locale={locale} />;
}

export function RejectDialog({ candidate, locale }: { candidate: CandidateSummary; locale?: Locale }) {
  return <ReviewDialog candidate={candidate} decision="reject" locale={locale} />;
}

export function AgentTaskForm({ candidates, locale = "en" }: { candidates: CandidateSummary[]; locale?: Locale }) {
  const router = useRouter();
  const isHydrated = useIsHydrated();
  const text = copy[locale];
  const form = useForm<TaskValues>({
    resolver: zodResolver(taskSchema),
    defaultValues: {
      task_type: "propose-factor",
      goal: "low-vol momentum on liquid ETFs",
      universe: "SPY,QQQ",
      experiment_id: "",
      factor_id: "momentum",
    },
  });
  const mutation = useMutation({
    mutationFn: (values: TaskValues) =>
      apiPost<AgentTaskResponse>("/api/agent/tasks", {
        task_type: values.task_type,
        goal: values.goal,
        universe: splitSymbols(values.universe),
        experiment_id: values.experiment_id || null,
        factor_id: values.factor_id || null,
      }),
    onSuccess: (payload) => {
      toast.success(`${text.candidateCreatedToast} ${payload.candidate_id}`);
      router.refresh();
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;
  // Prefer a verified pending candidate with approval enabled.
  const firstPending =
    candidates.find(
      (candidate) =>
        candidate.status === "pending" &&
        candidate.approval_enabled === true &&
        candidate.integrity_state === "verified",
    ) ??
    candidates.find((candidate) => candidate.status === "pending") ??
    candidates[0];
  const runTask = form.handleSubmit((values) => mutation.mutate(values));
  const reviewAllowed =
    Boolean(firstPending) &&
    firstPending.approval_enabled === true &&
    firstPending.status === "pending" &&
    firstPending.integrity_state === "verified";

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_320px]">
      <Card padded={false}>
        <form className="flex flex-col gap-4 p-4" onSubmit={(event) => event.preventDefault()}>
          <SectionTitle title={text.runAgentTask} hint={text.runTaskHint} />
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.taskType}
            <select className={fieldClass} {...form.register("task_type")}>
              <option>propose-factor</option>
              <option>propose-experiment</option>
              <option>summarize</option>
              <option>audit-leakage</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.goal}
            <textarea className={`min-h-24 ${fieldClass}`} {...form.register("goal")} />
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.universe}
            <input className={`font-data-mono ${fieldClass}`} {...form.register("universe")} />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              {text.experimentId}
              <input className={`font-data-mono ${fieldClass}`} {...form.register("experiment_id")} />
            </label>
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              {text.factorId}
              <input className={`font-data-mono ${fieldClass}`} {...form.register("factor_id")} />
            </label>
          </div>
          {error ? <p className="font-body-sm text-danger">{error}</p> : null}
          <TerminalToolbarButton
            className="h-9"
            disabled={!isHydrated || mutation.isPending}
            onClick={() => void runTask()}
            tone="info"
          >
            {mutation.isPending ? text.running : text.runTask}
          </TerminalToolbarButton>
        </form>
      </Card>

      <Card tone="warning" padded={false} className="flex flex-col">
        <div className="p-4">
          <SectionTitle title={text.manualReview} hint={text.manualReviewNote} />
          {firstPending ? (
            <div className="space-y-3">
              <div className="rounded-lg border border-border-subtle bg-bg-surface-muted p-3">
                <p className="truncate font-data-mono text-xs text-text-primary">
                  {firstPending.candidate_id}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <StatusPill
                    label={text.status}
                    value={firstPending.status ?? "unknown"}
                    tone={statusTone(firstPending.status)}
                  />
                  {firstPending.integrity_state ? (
                    <StatusPill
                      label="integrity"
                      value={firstPending.integrity_state}
                      tone={
                        firstPending.integrity_state === "verified"
                          ? "success"
                          : firstPending.integrity_state === "migration_required"
                            ? "warning"
                            : "danger"
                      }
                    />
                  ) : null}
                </div>
                {firstPending.manifest_digest ? (
                  <p className="mt-2 break-all font-data-mono text-[10px] text-text-secondary">
                    {text.digestLabel}: {firstPending.manifest_digest}
                  </p>
                ) : null}
                {firstPending.integrity_state === "migration_required" &&
                firstPending.observed_manifest_digest ? (
                  <p className="mt-2 break-all font-data-mono text-[10px] text-warning">
                    {text.migrationEvidence}: {firstPending.observed_manifest_digest}
                  </p>
                ) : null}
              </div>
              {reviewAllowed ? (
                <div className="flex gap-2">
                  <ApproveDialog candidate={firstPending} locale={locale} />
                  <RejectDialog candidate={firstPending} locale={locale} />
                </div>
              ) : (
                <p className="font-body-sm text-text-secondary">{text.reviewDisabled}</p>
              )}
            </div>
          ) : (
            <p className="font-body-sm text-text-secondary">{text.noCandidate}</p>
          )}
        </div>
      </Card>
    </div>
  );
}
