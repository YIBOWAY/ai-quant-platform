'use client';

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  RefreshCw,
  ShieldCheck,
  TerminalSquare,
} from "lucide-react";
import { Card, MetricStat, StatusPill } from "@/components/ui/primitives";
import type { StrategyOpsStatusResponse } from "@/lib/api";
import { ApiClientError, apiRequest } from "@/lib/apiClient";

type Locale = "en" | "zh";

const copy = {
  en: {
    title: "Automation Ops",
    desc: "Read-only status for the local CLI / launchd workflow. It shows what is waiting; it does not create signals or execute plans.",
    refresh: "Refresh",
    refreshing: "Refreshing",
    schedule: "scheduler",
    scheduleValue: "local CLI",
    safety: "mode",
    safetyValue: "paper only",
    targetDate: "target date",
    lastUpdated: "updated",
    never: "not yet",
    status: "status",
    clear: "clear",
    waiting: "waiting",
    review: "review",
    offline: "offline",
    runningSleeves: "Running sleeves",
    pendingPlans: "Pending plans",
    duePlans: "Due today",
    blockedPlans: "Blocked",
    recovery: "Recovery",
    journals: "Journals",
    allClear: "No due local execution work.",
    dueHint: "Due plans are waiting for the scheduled next-open processor.",
    blockedHint: "Blocked executions need manual review before another run.",
    recoveryHint: "Recovery-required executions indicate an interrupted journal.",
    journalHint: "Pending journals should reconcile on the next status/detail access.",
    unavailable: "Automation status unavailable",
    accountDown: "Account API is unreachable; status may be stale until the backend recovers.",
  },
  zh: {
    title: "自动化运维",
    desc: "本地 CLI / launchd 工作流的只读状态。这里展示等待处理的事项，不会创建信号，也不会执行计划。",
    refresh: "刷新",
    refreshing: "刷新中",
    schedule: "调度",
    scheduleValue: "本地 CLI",
    safety: "模式",
    safetyValue: "仅模拟",
    targetDate: "目标日",
    lastUpdated: "更新",
    never: "尚未",
    status: "状态",
    clear: "正常",
    waiting: "等待",
    review: "查看",
    offline: "离线",
    runningSleeves: "运行袖珍仓",
    pendingPlans: "待执行计划",
    duePlans: "今日待执行",
    blockedPlans: "阻塞",
    recovery: "待恢复",
    journals: "日志",
    allClear: "暂无到期的本地执行工作。",
    dueHint: "到期计划正在等待定时的 next-open 处理器。",
    blockedHint: "阻塞执行需要人工查看后再运行。",
    recoveryHint: "待恢复通常表示执行日志曾被中断。",
    journalHint: "待提交日志会在下一次状态或详情访问时尝试对账。",
    unavailable: "自动化状态不可用",
    accountDown: "账户 API 当前不可达；后端恢复前状态可能滞后。",
  },
} as const;

export function PaperStrategyOpsPanel({
  locale = "en",
  accountDown = false,
}: {
  locale?: Locale;
  accountDown?: boolean;
}) {
  const text = copy[locale];
  const statusQuery = useQuery({
    queryKey: ["paper-strategy-ops-status"],
    queryFn: () =>
      apiRequest<StrategyOpsStatusResponse>(
        "/api/paper/strategy-sleeves/ops/status",
      ),
  });
  const status = statusQuery.data?.status ?? null;
  const lastUpdated =
    statusQuery.dataUpdatedAt > 0 ? new Date(statusQuery.dataUpdatedAt) : null;
  const error =
    statusQuery.error instanceof ApiClientError || statusQuery.error instanceof Error
      ? statusQuery.error.message
      : statusQuery.error
        ? text.unavailable
        : null;
  const refreshing = statusQuery.isFetching;

  const healthTone = useMemo(() => {
    if (error || accountDown) {
      return "danger" as const;
    }
    if (
      (status?.blocked_count ?? 0) > 0 ||
      (status?.recovery_required_count ?? 0) > 0 ||
      (status?.pending_journal_count ?? 0) > 0
    ) {
      return "warning" as const;
    }
    if ((status?.pending_due_count ?? 0) > 0) {
      return "info" as const;
    }
    return "success" as const;
  }, [accountDown, error, status]);

  const healthLabel = useMemo(() => {
    if (error || accountDown) {
      return text.offline;
    }
    if (
      (status?.blocked_count ?? 0) > 0 ||
      (status?.recovery_required_count ?? 0) > 0 ||
      (status?.pending_journal_count ?? 0) > 0
    ) {
      return text.review;
    }
    if ((status?.pending_due_count ?? 0) > 0) {
      return text.waiting;
    }
    return text.clear;
  }, [accountDown, error, status, text]);

  const issueRows = useMemo(() => {
    if (!status) {
      return [];
    }
    const rows: Array<{ key: string; label: string; count: number; tone: string }> = [];
    if (status.pending_due_count > 0) {
      rows.push({
        key: "due",
        label: text.dueHint,
        count: status.pending_due_count,
        tone: "text-info",
      });
    }
    if (status.blocked_count > 0) {
      rows.push({
        key: "blocked",
        label: text.blockedHint,
        count: status.blocked_count,
        tone: "text-warning",
      });
    }
    if (status.recovery_required_count > 0) {
      rows.push({
        key: "recovery",
        label: text.recoveryHint,
        count: status.recovery_required_count,
        tone: "text-danger",
      });
    }
    if (status.pending_journal_count > 0) {
      rows.push({
        key: "journals",
        label: text.journalHint,
        count: status.pending_journal_count,
        tone: "text-warning",
      });
    }
    return rows;
  }, [status, text]);

  const updatedLabel = lastUpdated
    ? lastUpdated.toLocaleTimeString(locale === "zh" ? "zh-CN" : "en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : text.never;

  return (
    <Card padded className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 font-label-caps text-text-primary">
            <TerminalSquare className="text-accent-success" size={16} />
            {text.title}
          </h2>
          <p className="mt-1 max-w-3xl font-body-sm text-text-secondary">{text.desc}</p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <StatusPill label={text.status} value={healthLabel} tone={healthTone} />
          <button
            type="button"
            onClick={() => void statusQuery.refetch()}
            disabled={refreshing}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-border-subtle px-3 py-2 font-body-sm text-text-primary transition-colors hover:bg-bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className={refreshing ? "animate-spin" : ""} size={14} />
            {refreshing ? text.refreshing : text.refresh}
          </button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-2 border-y border-border-subtle py-2 md:grid-cols-4">
        <MetricStat
          label={text.schedule}
          value={text.scheduleValue}
          size="inline"
          hint="External scheduler identity"
        />
        <MetricStat
          label={text.safety}
          value={text.safetyValue}
          size="inline"
          tone="success"
          hint="Paper account only"
        />
        <MetricStat
          label={text.targetDate}
          value={status?.target_date ?? "..."}
          size="inline"
          hint="Local due date"
        />
        <MetricStat label={text.lastUpdated} value={updatedLabel} size="inline" />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-6">
        <MetricStat
          label={text.runningSleeves}
          value={status?.running_sleeve_count ?? "..."}
          size="inline"
        />
        <MetricStat
          label={text.pendingPlans}
          value={status?.pending_execution_count ?? "..."}
          size="inline"
          tone={(status?.pending_execution_count ?? 0) > 0 ? "info" : "neutral"}
        />
        <MetricStat
          label={text.duePlans}
          value={status?.pending_due_count ?? "..."}
          size="inline"
          tone={(status?.pending_due_count ?? 0) > 0 ? "info" : "neutral"}
        />
        <MetricStat
          label={text.blockedPlans}
          value={status?.blocked_count ?? "..."}
          size="inline"
          tone={(status?.blocked_count ?? 0) > 0 ? "warning" : "neutral"}
        />
        <MetricStat
          label={text.recovery}
          value={status?.recovery_required_count ?? "..."}
          size="inline"
          tone={(status?.recovery_required_count ?? 0) > 0 ? "danger" : "neutral"}
        />
        <MetricStat
          label={text.journals}
          value={status?.pending_journal_count ?? "..."}
          size="inline"
          tone={(status?.pending_journal_count ?? 0) > 0 ? "warning" : "neutral"}
        />
      </div>

      <div className="mt-4 rounded-lg border border-border-subtle bg-bg-surface-muted/60 p-3">
        {error ? (
          <div className="flex items-start gap-2 font-body-sm text-danger">
            <AlertTriangle className="mt-0.5 shrink-0" size={16} />
            <span>{error}</span>
          </div>
        ) : accountDown ? (
          <div className="flex items-start gap-2 font-body-sm text-warning">
            <AlertTriangle className="mt-0.5 shrink-0" size={16} />
            <span>{text.accountDown}</span>
          </div>
        ) : issueRows.length > 0 ? (
          <div className="space-y-2">
            {issueRows.map((row) => (
              <div key={row.key} className="flex items-start gap-2 font-body-sm text-text-secondary">
                <Clock3 className={`mt-0.5 shrink-0 ${row.tone}`} size={16} />
                <span className="font-data-mono text-text-primary">{row.count}</span>
                <span>{row.label}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex items-start gap-2 font-body-sm text-text-secondary">
            <CheckCircle2 className="mt-0.5 shrink-0 text-accent-success" size={16} />
            <span>{text.allClear}</span>
            <ShieldCheck className="ml-auto hidden text-accent-success sm:block" size={16} />
          </div>
        )}
      </div>
    </Card>
  );
}
