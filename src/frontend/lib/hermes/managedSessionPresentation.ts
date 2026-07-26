import { WorkspaceClientError } from "@/lib/hermes/workspaceClient";
import type { Locale } from "@/lib/locale";

const RETRYABLE_CODES = new Set([
  "managed_session_not_observed",
  "managed_session_provision_retryable",
  "managed_session_provision_timeout",
  "managed_session_provision_unavailable",
]);

const IDENTITY_CODES = new Set([
  "managed_session_create_projection_mismatch",
  "managed_session_create_receipt_digest_invalid",
  "managed_session_create_receipt_digest_mismatch",
  "managed_session_create_receipt_identity_mismatch",
  "managed_session_create_receipt_session_identity_mismatch",
  "managed_session_create_receipt_workspace_mismatch",
  "managed_session_create_ref_invalid",
  "managed_session_create_ref_missing",
  "managed_session_admission_mismatch",
  "managed_session_identity_ambiguous",
  "managed_session_projection_invalid",
  "managed_session_ready_contract_invalid",
]);

/**
 * User-facing recovery copy for explicit new-session creation. Do not expose
 * backend exception text or discard the stable client_action_id: the next
 * click retries the same durable attempt.
 */
export function freshManagedSessionErrorCopy(
  error: unknown,
  locale: Locale,
): string {
  const isZh = locale === "zh";
  const code =
    error instanceof WorkspaceClientError ? error.code ?? "" : "";
  if (code === "owner_bootstrap_required") {
    return isZh
      ? "本机授权已失效。请重新完成首次使用授权，然后再次点击“新建空白对话”；系统会重试同一次创建。"
      : "Local authorization expired. Complete first-use authorization, then select “New blank conversation” again; the same create attempt will be retried.";
  }
  if (RETRYABLE_CODES.has(code)) {
    return isZh
      ? "新会话尚未就绪。请再次点击“新建空白对话”重试同一次创建；不会重复创建会话。"
      : "The new session is not ready yet. Select “New blank conversation” again to retry the same create attempt; it will not create a duplicate.";
  }
  if (IDENTITY_CODES.has(code) || code === "conflict") {
    return isZh
      ? "无法验证新会话的完整身份，当前会话未切换。请再次点击“新建空白对话”重试同一次创建；若仍失败，请检查本机后端健康状态。"
      : "The new session identity could not be verified, so the current session was not changed. Retry the same create attempt with “New blank conversation”; if it still fails, check local backend health.";
  }
  if (code === "managed_session_provision_failed") {
    return isZh
      ? "Hermes 未能创建新会话。请检查 Hermes 服务后，再次点击“新建空白对话”重试同一次创建。"
      : "Hermes could not create the new session. Check the Hermes service, then retry the same create attempt with “New blank conversation”.";
  }
  return isZh
    ? "新会话创建失败，当前会话未切换。请再次点击“新建空白对话”重试同一次创建；不会重复创建会话。"
    : "The new session could not be created, and the current session was not changed. Select “New blank conversation” again to retry the same create attempt without creating a duplicate.";
}
