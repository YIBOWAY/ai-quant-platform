import type { WorkspaceRunActivityResponse } from "@/lib/api.generated";
import type { WorkspaceCommandProjection } from "@/lib/hermes/workspaceClient";

export type WorkspaceRunActivity = WorkspaceRunActivityResponse;
export type WorkspaceRunActivityStage = WorkspaceRunActivity["stage"];

/** Newest-first by updated_at, then created_at, then stable command_id. */
export function sortCommandsNewestFirst(
  commands: WorkspaceCommandProjection[] | null | undefined,
): WorkspaceCommandProjection[] {
  if (!Array.isArray(commands) || commands.length === 0) return [];
  return [...commands].sort((a, b) => {
    const ta = Date.parse(a.updated_at || a.created_at || "") || 0;
    const tb = Date.parse(b.updated_at || b.created_at || "") || 0;
    if (tb !== ta) return tb - ta;
    return String(b.command_id).localeCompare(String(a.command_id));
  });
}

export function shortId(value: string | null | undefined, head = 8): string {
  if (!value) return "";
  const s = value.trim();
  if (s.length <= head + 1) return s;
  return `${s.slice(0, head)}…`;
}

/** Operator-facing lifecycle label (en). */
export function commandStateLabel(
  state: string | null | undefined,
  isZh = false,
): string {
  const s = (state || "").trim() || "unknown";
  if (!isZh) {
    switch (s) {
      case "queued":
        return "Queued";
      case "leased":
        return "Leased";
      case "delivered":
        return "Delivered";
      case "succeeded":
        return "Succeeded";
      case "failed":
        return "Failed";
      case "rejected":
        return "Rejected";
      case "cancelled":
        return "Cancelled";
      case "timed_out":
        return "Timed out";
      case "outcome_unknown":
        return "Outcome unknown";
      default:
        return s;
    }
  }
  switch (s) {
    case "queued":
      return "排队中";
    case "leased":
      return "已租约";
    case "delivered":
      return "已送达";
    case "succeeded":
      return "已成功";
    case "failed":
      return "失败";
    case "rejected":
      return "已拒绝";
    case "cancelled":
      return "已取消";
    case "timed_out":
      return "超时";
    case "outcome_unknown":
      return "结果未知";
    default:
      return s;
  }
}

export function isActiveCommandState(state: string | null | undefined): boolean {
  const s = (state || "").trim();
  return s === "queued" || s === "leased";
}

/**
 * UI-1 Direction A "Running" lane: in-flight per the demo data contract §2.2 —
 * terminal = succeeded|cancelled|failed|rejected|timed_out (+ outcome_unknown
 * as an honest terminal); "delivered" still awaits the Hermes receipt and
 * therefore remains in-flight. Distinct from the ledger-terminal set in
 * workspaceClient.isTerminalCommandState, which the submit controller uses.
 */
const RUNNING_TERMINAL_STATES = new Set([
  "succeeded",
  "cancelled",
  "failed",
  "rejected",
  "timed_out",
  "outcome_unknown",
]);

export function isInFlightCommandState(state: string | null | undefined): boolean {
  const s = (state || "").trim();
  if (!s) return false;
  return !RUNNING_TERMINAL_STATES.has(s);
}

export function selectChatCommand(
  commands: WorkspaceCommandProjection[] | null | undefined,
  hermesSessionId: string | null | undefined,
): WorkspaceCommandProjection | null {
  const sessionId = hermesSessionId?.trim();
  if (!sessionId) return null;
  const matches = sortCommandsNewestFirst(commands).filter(
    (command) => command.hermes_session_id === sessionId,
  );
  return matches.find((command) => isInFlightCommandState(command.state)) ?? matches[0] ?? null;
}

export function activityStageLabel(
  stage: WorkspaceRunActivityStage | null | undefined,
  commandState: string | null | undefined,
  isZh: boolean,
): string {
  const commandTerminal = RUNNING_TERMINAL_STATES.has(commandState?.trim() ?? "");
  const key = commandTerminal ? commandState ?? "" : stage ?? commandState ?? "";
  const zh: Record<string, string> = {
    queued: "等待 Hermes 接单",
    leased: "正在交给 Hermes",
    delivered: "Hermes 正在处理",
    running: "Hermes 正在处理",
    analyzing: "正在分析你的问题",
    using_tool: "正在使用本机工具",
    answering: "正在生成回复",
    waiting_for_approval: "等待你的确认",
    stopping: "正在停止",
    succeeded: commandState === "succeeded" ? "回复已完成" : "正在整理回复",
    failed: "处理失败",
    rejected: "请求已拒绝",
    cancelled: "已取消",
    timed_out: "处理超时",
    outcome_unknown: "仍在确认处理结果",
    stopped: "已停止",
  };
  const en: Record<string, string> = {
    queued: "Waiting for Hermes",
    leased: "Sending to Hermes",
    delivered: "Hermes is working",
    running: "Hermes is working",
    analyzing: "Analyzing your request",
    using_tool: "Using a local tool",
    answering: "Writing the reply",
    waiting_for_approval: "Waiting for your approval",
    stopping: "Stopping",
    succeeded: commandState === "succeeded" ? "Reply complete" : "Finalizing the reply",
    failed: "Processing failed",
    rejected: "Request rejected",
    cancelled: "Cancelled",
    timed_out: "Timed out",
    outcome_unknown: "Confirming the result",
    stopped: "Stopped",
  };
  return (isZh ? zh : en)[key] ?? (isZh ? "等待发送" : "Waiting to send");
}

export function activityTransportLabel(
  transport: string,
  error: string | null | undefined,
  isZh: boolean,
): string {
  if (error) {
    return isZh
      ? "连接中断，任务可能仍在后台继续"
      : "Connection interrupted; the task may still be running";
  }
  if (transport === "sse") return isZh ? "实时连接" : "Live connection";
  if (transport === "poll") return isZh ? "正在定时获取进度" : "Checking progress";
  return isZh ? "正在连接 Hermes" : "Connecting to Hermes";
}

export function activityToolLabel(
  activity: Pick<WorkspaceRunActivity, "tool_state" | "tool_duration_seconds">,
  isZh: boolean,
): string {
  if (activity.tool_state === "active") return isZh ? "正在使用本机工具" : "Using a local tool";
  if (activity.tool_state === "failed") return isZh ? "本机工具执行失败" : "Local tool failed";
  const duration = activity.tool_duration_seconds;
  const suffix = duration == null ? "" : ` · ${duration.toFixed(1)} ${isZh ? "秒" : "s"}`;
  return `${isZh ? "本机工具完成" : "Local tool complete"}${suffix}`;
}
