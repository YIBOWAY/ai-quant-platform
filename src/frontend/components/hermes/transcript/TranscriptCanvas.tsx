import type { HermesSessionMessage } from "@/lib/hermes/workspaceClient";

export type TranscriptCanvasProps = {
  messages: HermesSessionMessage[];
  /** zh labels when true. */
  isZh?: boolean;
  omittedCount?: number;
  emptyHint?: string;
  className?: string;
  /** Optional session id shown in footer for operator clarity. */
  hermesSessionId?: string | null;
};

/**
 * Presentational user/assistant bubble list.
 * Visual parity with `/hermes/sessions/[id]` detail; no fetch here.
 */
export function TranscriptCanvas({
  messages,
  isZh = false,
  omittedCount = 0,
  emptyHint,
  className = "",
  hermesSessionId = null,
}: TranscriptCanvasProps) {
  const resolvedEmpty =
    emptyHint ??
    (isZh
      ? "此会话还没有可展示的用户/助手消息。"
      : "No displayable user/assistant messages yet.");

  if (!messages.length) {
    return (
      <div
        className={`rounded-lg border border-border-subtle bg-bg-surface px-3 py-4 ${className}`}
        data-hermes-transcript-empty
      >
        <p className="font-body-sm text-text-secondary">{resolvedEmpty}</p>
      </div>
    );
  }

  return (
    <div className={`space-y-3 ${className}`} data-hermes-transcript-canvas>
      <ol className="space-y-3" data-hermes-session-messages>
        {messages.map((message, index) => {
          const isUser = message.role === "user";
          return (
            <li
              className={`flex ${isUser ? "justify-end" : "justify-start"}`}
              key={`${message.id || "msg"}:${index}`}
            >
              <div
                className={`max-w-[88%] rounded-lg border px-3 py-2 shadow-sm ${
                  isUser
                    ? "border-info/30 bg-info/10"
                    : "border-border-subtle bg-bg-surface"
                }`}
              >
                <p className="font-label-caps text-text-secondary">
                  {isUser ? (isZh ? "你" : "You") : "Hermes"}
                </p>
                <p className="mt-2 whitespace-pre-wrap break-words font-body-sm text-text-primary">
                  {message.content}
                </p>
                {message.timestamp ? (
                  <p className="mt-2 font-data-mono text-[11px] text-text-secondary">
                    {message.timestamp}
                  </p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
      {omittedCount > 0 ? (
        <p
          className="font-body-sm text-text-secondary"
          data-hermes-omitted-message-count
        >
          {isZh
            ? `为保护敏感工具内容和控制响应大小，省略了 ${omittedCount} 条系统、工具或较早消息。`
            : `${omittedCount} system, tool, or older messages were omitted for safety and response bounds.`}
        </p>
      ) : null}
      {hermesSessionId ? (
        <p
          className="font-data-mono text-[11px] text-text-secondary"
          data-hermes-transcript-session-id
        >
          {hermesSessionId}
        </p>
      ) : null}
    </div>
  );
}
