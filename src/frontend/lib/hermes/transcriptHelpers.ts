import type { HermesSessionMessage } from "@/lib/hermes/workspaceClient";

/**
 * Hermes messages BFF ids include canonical managed `web_*` sessions.
 * Platform registry `wm_*` must never hit /messages.
 */
export function isUsableHermesApiSessionId(
  value: string | null | undefined,
): value is string {
  if (typeof value !== "string") return false;
  const id = value.trim();
  if (!id) return false;
  if (id.startsWith("wm_")) return false;
  return true;
}

/** Keep non-empty user/assistant rows for workbench transcript canvas. */
export function displayableTranscriptMessages(
  messages: HermesSessionMessage[] | null | undefined,
): HermesSessionMessage[] {
  if (!Array.isArray(messages) || messages.length === 0) {
    return [];
  }
  return messages.filter((m) => {
    if (!m || typeof m !== "object") return false;
    if (m.role !== "user" && m.role !== "assistant") return false;
    return typeof m.content === "string" && m.content.trim().length > 0;
  });
}

/**
 * Prefer the newest command that already carries a usable hermes_session_id.
 */
export function pickLatestHermesSessionId(
  commands:
    | Array<{
        command_id?: string | null;
        state?: string | null;
        hermes_session_id?: string | null;
      }>
    | null
    | undefined,
): { hermesSessionId: string; commandId?: string } | null {
  if (!Array.isArray(commands) || commands.length === 0) {
    return null;
  }
  for (let i = commands.length - 1; i >= 0; i -= 1) {
    const row = commands[i];
    if (!row || !["succeeded", "failed", "cancelled"].includes(row.state ?? "")) {
      continue;
    }
    const id = row?.hermes_session_id;
    if (!isUsableHermesApiSessionId(id)) continue;
    return {
      hermesSessionId: id.trim(),
      commandId: row?.command_id ?? undefined,
    };
  }
  return null;
}

/** True when the scroll container is within `thresholdPx` of the bottom. */
export function isNearBottom(
  el: Pick<HTMLElement, "scrollHeight" | "scrollTop" | "clientHeight"> | null | undefined,
  thresholdPx = 80,
): boolean {
  if (!el) return true;
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
  return distance <= thresholdPx;
}

const PENDING_USER_ID = "local-pending-user";

/**
 * Append a local optimistic user bubble when the server transcript does not
 * already contain the same user text (L3b). Never invents assistant content.
 */
export function mergePendingUserMessage(
  messages: HermesSessionMessage[] | null | undefined,
  pendingText: string | null | undefined,
): HermesSessionMessage[] {
  const base = displayableTranscriptMessages(messages);
  const text = typeof pendingText === "string" ? pendingText.trim() : "";
  if (!text) return base;

  const already = base.some(
    (m) => m.role === "user" && m.content.trim() === text,
  );
  if (already) return base;

  return [
    ...base,
    {
      id: PENDING_USER_ID,
      role: "user",
      content: text,
      timestamp: null,
    },
  ];
}

/** Best-effort clipboard write; returns false when unavailable. */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  const value = text.trim();
  if (!value) return false;
  try {
    if (
      typeof navigator !== "undefined" &&
      navigator.clipboard &&
      typeof navigator.clipboard.writeText === "function"
    ) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // fall through
  }
  try {
    if (typeof document === "undefined") return false;
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
