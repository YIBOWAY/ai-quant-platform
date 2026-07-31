import { CHAT_PROMPT_MAX_BYTES } from "./darkIdentity";
import { WorkspaceClientError } from "./workspaceClient";
import type { Locale } from "@/lib/locale";

export type ComposerDraftState = {
  byteLength: number;
  empty: boolean;
  overLimitBytes: number;
  valid: boolean;
  counterText: string;
};

function shortCommandId(commandId?: string | null): string {
  if (!commandId) return "";
  return commandId.length > 8 ? `${commandId.slice(0, 8)}…` : commandId;
}

export function composerDraftState(
  draft: string,
  locale: Locale,
): ComposerDraftState {
  const byteLength = new TextEncoder().encode(draft).length;
  const empty = !draft.trim();
  const overLimitBytes = Math.max(0, byteLength - CHAT_PROMPT_MAX_BYTES);
  const counterText =
    locale === "zh"
      ? overLimitBytes > 0
        ? `已输入 ${byteLength.toLocaleString("en-US")} / ${CHAT_PROMPT_MAX_BYTES.toLocaleString("en-US")} 字节；超出 ${overLimitBytes.toLocaleString("en-US")} 字节`
        : `已输入 ${byteLength.toLocaleString("en-US")} / ${CHAT_PROMPT_MAX_BYTES.toLocaleString("en-US")} 字节`
      : overLimitBytes > 0
        ? `${byteLength.toLocaleString("en-US")} / ${CHAT_PROMPT_MAX_BYTES.toLocaleString("en-US")} bytes; ${overLimitBytes.toLocaleString("en-US")} bytes over`
        : `${byteLength.toLocaleString("en-US")} / ${CHAT_PROMPT_MAX_BYTES.toLocaleString("en-US")} bytes`;
  return {
    byteLength,
    empty,
    overLimitBytes,
    valid: !empty && overLimitBytes === 0,
    counterText,
  };
}

export function formatComposerReceiptStatus(
  status: string,
  commandId: string | undefined,
  reason: string | undefined,
  locale: Locale,
): string {
  const command = commandId
    ? locale === "zh"
      ? ` · 命令 ${shortCommandId(commandId)}`
      : ` · command ${shortCommandId(commandId)}`
    : "";
  const why = reason ? ` (${reason})` : "";
  const zh: Record<string, string> = {
    accepted: "已接受",
    outcome_unknown: "结果未知——请重试同一次发送，或继续跟踪工作区",
    conflict: "发生冲突",
    unavailable: "暂不可用",
    reconciling: "正在对账",
  };
  const en: Record<string, string> = {
    accepted: "Accepted",
    outcome_unknown: "Outcome unknown — retry same send or follow workspace",
    conflict: "Conflict",
    unavailable: "Unavailable",
    reconciling: "Reconciling",
  };
  const label = (locale === "zh" ? zh : en)[status] ?? status;
  return `${label}${status === "outcome_unknown" ? "" : command}${why}`;
}

export function formatComposerLifecycleStatus(
  state: string | null,
  commandId: string | null | undefined,
  hermesRunId: string | null | undefined,
  locale: Locale,
): string {
  const command = commandId ? ` · ${shortCommandId(commandId)}` : "";
  const runLabel = locale === "zh" ? "运行" : "run";
  const run =
    hermesRunId && hermesRunId.length > 12
      ? ` · ${runLabel} ${hermesRunId.slice(0, 12)}…`
      : hermesRunId
        ? ` · ${runLabel} ${hermesRunId}`
        : "";
  const zh: Record<string, string> = {
    queued: "排队中",
    leased: "已领取",
    delivered: "已送达",
    succeeded: "已成功",
    failed: "失败",
    rejected: "已拒绝",
    cancelled: "已取消",
    timed_out: "已超时",
    outcome_unknown: "结果未知",
  };
  const en: Record<string, string> = {
    queued: "Queued",
    leased: "Leased",
    delivered: "Delivered",
    succeeded: "Succeeded",
    failed: "Failed",
    rejected: "Rejected",
    cancelled: "Cancelled",
    timed_out: "Timed out",
    outcome_unknown: "Outcome unknown",
  };
  const label = state
    ? (locale === "zh" ? zh : en)[state] ?? state
    : locale === "zh"
      ? "跟踪中"
      : "Tracking";
  return `${label}${command}${
    state === "delivered" || state === "succeeded" ? run : ""
  }`;
}

export function composerSubmittingText(locale: Locale): string {
  return locale === "zh" ? "提交中…" : "Submitting…";
}

export function composerLoadingReplyText(locale: Locale): string {
  return locale === "zh" ? "正在加载回复…" : "loading reply…";
}

export function composerStillTrackingText(locale: Locale): string {
  return locale === "zh"
    ? "仍在通过事件流跟踪"
    : "still tracking via follow spine";
}

export function composerErrorMessage(
  error: unknown,
  locale: Locale,
): string {
  const code =
    error instanceof WorkspaceClientError ? error.code : undefined;
  if (code === "prompt_too_large") {
    return locale === "zh"
      ? "消息超过 16,384 字节，请缩短后再发送。"
      : "The message exceeds 16,384 bytes. Shorten it before sending.";
  }
  if (
    code === "intent_crypto_unavailable" ||
    code === "keychain_unavailable" ||
    code === "crypto_helper_unavailable" ||
    code === "crypto_helper_timeout"
  ) {
    return locale === "zh"
      ? "加密存储暂不可用。请解锁 macOS 钥匙串并授权 Hermes 的加密 helper，然后点击“重试同一次发送”；系统不会重复创建命令。"
      : "Encrypted storage is unavailable. Unlock macOS Keychain and authorize the Hermes crypto helper, then choose “Retry same send”; the same action will not create a duplicate command.";
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return locale === "zh" ? "提交失败" : "Submit failed";
}
