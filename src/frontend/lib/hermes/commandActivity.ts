import type { WorkspaceCommandProjection } from "@/lib/hermes/workspaceClient";

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
