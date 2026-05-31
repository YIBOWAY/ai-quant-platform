'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import type { CandidateSummary } from "@/lib/api";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";
import type { Locale } from "@/lib/locale";

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
    manualReviewNote: "Review writes lock files only. It never registers a factor.",
    noCandidate: "No candidate available.",
    candidateCreatedToast: "Agent candidate created:",
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
    manualReviewNote: "复核仅写入锁文件，绝不会注册因子。",
    noCandidate: "暂无可用候选。",
    candidateCreatedToast: "已创建智能体候选：",
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
  note: z.string().min(1, "Review note is required"),
});

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };

type TaskValues = z.infer<typeof taskSchema>;
type ReviewValues = z.infer<typeof reviewSchema>;
type ReviewDecision = "approve" | "reject";

type AgentTaskResponse = {
  candidate_id: string;
};

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
  const mutation = useMutation({
    mutationFn: (values: ReviewValues) =>
      apiPost(`/api/agent/candidates/${candidate.candidate_id}/review`, {
        decision,
        note: values.note,
      }),
    onSuccess: () => {
      toast.success(`${decision === "approve" ? text.approvedToast : text.rejectedToast} ${candidate.candidate_id}`);
      setOpen(false);
      router.refresh();
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;
  const writeReview = form.handleSubmit((values) => mutation.mutate(values));

  return (
    <>
      <button
        className={`rounded border px-3 py-2 font-body-sm ${
          decision === "approve"
            ? "border-accent-success/40 text-accent-success"
            : "border-danger/40 text-danger"
        }`}
        disabled={!isHydrated}
        onClick={() => setOpen(true)}
        type="button"
      >
        {decision === "approve" ? text.approve : text.reject}
      </button>
      {open ? (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-lg rounded border border-warning/40 bg-bg-surface p-5 shadow-xl" role="alertdialog" aria-modal="true">
            <h3 className="font-headline-lg text-text-primary">
              {decision === "approve" ? text.approveTitle : text.rejectTitle}
            </h3>
            {decision === "approve" ? (
              <p className="mt-3 font-body-sm text-warning">
                {text.approveNote}
              </p>
            ) : (
              <p className="mt-3 font-body-sm text-text-secondary">
                {text.rejectNote}
              </p>
            )}
            <form className="mt-4 flex flex-col gap-3" onSubmit={(event) => event.preventDefault()}>
              <label className="flex flex-col gap-1 font-body-sm text-text-primary">
                {text.reviewNote}
                <textarea className="min-h-24 rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary" {...form.register("note")} />
              </label>
              {error ? <p className="font-body-sm text-danger">{error}</p> : null}
              <div className="flex justify-end gap-2">
                <button className="rounded border border-border-subtle px-4 py-2 font-body-sm text-text-primary" onClick={() => setOpen(false)} type="button">
                  {text.cancel}
                </button>
                <button className="rounded bg-warning px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50" disabled={!isHydrated || mutation.isPending} onClick={() => void writeReview()} type="button">
                  {mutation.isPending ? text.writingLock : text.confirm}
                </button>
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
  const firstPending = candidates.find((candidate) => candidate.status === "pending") ?? candidates[0];
  const runTask = form.handleSubmit((values) => mutation.mutate(values));

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_320px]">
      <form className="flex flex-col gap-4 rounded border border-border-subtle bg-bg-surface p-4" onSubmit={(event) => event.preventDefault()}>
        <h2 className="font-headline-lg text-text-primary">{text.runAgentTask}</h2>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.taskType}
          <select className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary" {...form.register("task_type")}>
            <option style={optionStyle}>propose-factor</option>
            <option style={optionStyle}>propose-experiment</option>
            <option style={optionStyle}>summarize</option>
            <option style={optionStyle}>audit-leakage</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.goal}
          <textarea className="min-h-24 rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary" {...form.register("goal")} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.universe}
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" {...form.register("universe")} />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.experimentId}
            <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" {...form.register("experiment_id")} />
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.factorId}
            <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" {...form.register("factor_id")} />
          </label>
        </div>
        {error ? <p className="font-body-sm text-danger">{error}</p> : null}
        <button className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50" disabled={!isHydrated || mutation.isPending} onClick={() => void runTask()} type="button">
          {mutation.isPending ? text.running : text.runTask}
        </button>
      </form>

      <div className="rounded border border-border-subtle bg-bg-surface p-4">
        <h2 className="font-headline-lg text-text-primary">{text.manualReview}</h2>
        <p className="mt-1 font-body-sm text-text-secondary">
          {text.manualReviewNote}
        </p>
        {firstPending ? (
          <div className="mt-4 space-y-3">
            <div className="truncate rounded border border-border-subtle bg-surface-muted p-3 font-data-mono text-xs text-text-primary">
              {firstPending.candidate_id}
            </div>
            <div className="flex gap-2">
              <ApproveDialog candidate={firstPending} locale={locale} />
              <RejectDialog candidate={firstPending} locale={locale} />
            </div>
          </div>
        ) : (
          <p className="mt-4 font-body-sm text-text-secondary">{text.noCandidate}</p>
        )}
      </div>
    </div>
  );
}
