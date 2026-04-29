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

type TaskValues = z.infer<typeof taskSchema>;
type ReviewValues = z.infer<typeof reviewSchema>;
type ReviewDecision = "approve" | "reject";

type AgentTaskResponse = {
  candidate_id: string;
};

function ReviewDialog({
  candidate,
  decision,
}: {
  candidate: CandidateSummary;
  decision: ReviewDecision;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
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
      toast.success(`${decision === "approve" ? "Approved" : "Rejected"} ${candidate.candidate_id}`);
      setOpen(false);
      router.refresh();
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;

  return (
    <>
      <button
        className={`rounded border px-3 py-2 font-body-sm ${
          decision === "approve"
            ? "border-accent-success/40 text-accent-success"
            : "border-danger/40 text-danger"
        }`}
        onClick={() => setOpen(true)}
        type="button"
      >
        {decision === "approve" ? "Approve" : "Reject"}
      </button>
      {open ? (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-lg rounded border border-warning/40 bg-bg-surface p-5 shadow-xl" role="alertdialog" aria-modal="true">
            <h3 className="font-headline-lg text-text-primary">
              {decision === "approve" ? "Approve candidate" : "Reject candidate"}
            </h3>
            {decision === "approve" ? (
              <p className="mt-3 font-body-sm text-warning">
                Approving creates an `approved.lock` file only. It does NOT register the factor automatically.
              </p>
            ) : (
              <p className="mt-3 font-body-sm text-text-secondary">
                Rejecting creates a `rejected.lock` file only.
              </p>
            )}
            <form className="mt-4 flex flex-col gap-3" onSubmit={form.handleSubmit((values) => mutation.mutate(values))}>
              <label className="flex flex-col gap-1 font-body-sm text-text-primary">
                Review note
                <textarea className="min-h-24 rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary" {...form.register("note")} />
              </label>
              {error ? <p className="font-body-sm text-danger">{error}</p> : null}
              <div className="flex justify-end gap-2">
                <button className="rounded border border-border-subtle px-4 py-2 font-body-sm text-text-primary" onClick={() => setOpen(false)} type="button">
                  Cancel
                </button>
                <button className="rounded bg-warning px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50" disabled={mutation.isPending} type="submit">
                  {mutation.isPending ? "Writing lock..." : "Confirm"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}

export function ApproveDialog({ candidate }: { candidate: CandidateSummary }) {
  return <ReviewDialog candidate={candidate} decision="approve" />;
}

export function RejectDialog({ candidate }: { candidate: CandidateSummary }) {
  return <ReviewDialog candidate={candidate} decision="reject" />;
}

export function AgentTaskForm({ candidates }: { candidates: CandidateSummary[] }) {
  const router = useRouter();
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
      toast.success(`Agent candidate created: ${payload.candidate_id}`);
      router.refresh();
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;
  const firstPending = candidates.find((candidate) => candidate.status === "pending") ?? candidates[0];

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_320px]">
      <form className="flex flex-col gap-4 rounded border border-border-subtle bg-bg-surface p-4" onSubmit={form.handleSubmit((values) => mutation.mutate(values))}>
        <h2 className="font-headline-lg text-text-primary">Run Agent Task</h2>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Task type
          <select className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary" {...form.register("task_type")}>
            <option>propose-factor</option>
            <option>propose-experiment</option>
            <option>summarize</option>
            <option>audit-leakage</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Goal
          <textarea className="min-h-24 rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary" {...form.register("goal")} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Universe
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" {...form.register("universe")} />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            Experiment ID
            <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" {...form.register("experiment_id")} />
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            Factor ID
            <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" {...form.register("factor_id")} />
          </label>
        </div>
        {error ? <p className="font-body-sm text-danger">{error}</p> : null}
        <button className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50" disabled={mutation.isPending} type="submit">
          {mutation.isPending ? "Running..." : "Run task"}
        </button>
      </form>

      <div className="rounded border border-border-subtle bg-bg-surface p-4">
        <h2 className="font-headline-lg text-text-primary">Manual Review</h2>
        <p className="mt-1 font-body-sm text-text-secondary">
          Review writes lock files only. It never registers a factor.
        </p>
        {firstPending ? (
          <div className="mt-4 space-y-3">
            <div className="truncate rounded border border-border-subtle bg-surface-muted p-3 font-data-mono text-xs text-text-primary">
              {firstPending.candidate_id}
            </div>
            <div className="flex gap-2">
              <ApproveDialog candidate={firstPending} />
              <RejectDialog candidate={firstPending} />
            </div>
          </div>
        ) : (
          <p className="mt-4 font-body-sm text-text-secondary">No candidate available.</p>
        )}
      </div>
    </div>
  );
}
