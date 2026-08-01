/**
 * Shared command-approval predicates (V7a decide gate + V7d projection filter).
 *
 * Extracted from WorkbenchCommandApprovalsPanel so non-panel consumers (dock
 * badge, Today attention) count exactly what the panel renders as decidable,
 * without importing a client component module. The panel re-exports both names
 * so existing import paths and its source-text contracts stay intact.
 */

import type { WorkspaceApprovalProjection } from "@/lib/hermes/workspaceClient";

/** V7a decide gate: full CAS binding required before any control renders. */
export function canDecideCommandApproval(
  row: WorkspaceApprovalProjection,
): boolean {
  const status = (row.status || row.expected_status || "pending").toLowerCase();
  if (status !== "pending") return false;
  if (!row.approval_id) return false;
  if (!row.run_id) return false;
  if (!row.digest || !/^[0-9a-f]{64}$/.test(row.digest)) return false;
  if (!row.expires_at) return false;
  return true;
}

/**
 * V7d: optimistic hide only while the spine still shows the row as pending.
 * Once the projector surfaces a terminal decided/expired fact, keep the row
 * so decision is visible and canDecideCommandApproval stays false.
 */
export function filterApprovalsForPanel(
  rows: WorkspaceApprovalProjection[],
  consumedIds: Record<string, true>,
): WorkspaceApprovalProjection[] {
  return rows.filter((row) => {
    if (!consumedIds[row.approval_id]) return true;
    // Hide only while still pending; surface terminal decided facts (V7d).
    return !canDecideCommandApproval(row);
  });
}
