import type { HermesSessionMessage } from "@/lib/hermes/workspaceClient";

/**
 * Hermes messages BFF ids are API session ids (often `run_…` / `agent:…`).
 * Platform registry `web_*` and workspace `wm_*` must never hit /messages.
 */
export function isUsableHermesApiSessionId(
  value: string | null | undefined,
): value is string {
  if (typeof value !== "string") return false;
  const id = value.trim();
  if (!id) return false;
  if (id.startsWith("web_") || id.startsWith("wm_")) return false;
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
    const id = row?.hermes_session_id;
    if (!isUsableHermesApiSessionId(id)) continue;
    return {
      hermesSessionId: id.trim(),
      commandId: row?.command_id ?? undefined,
    };
  }
  return null;
}
