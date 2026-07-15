import Link from "next/link";
import { Card } from "@/components/ui/primitives";
import { getHermesSessionDetail, getHermesSessionMessages } from "@/lib/api";
import { localizePath } from "@/lib/locale";
import { getServerLocale } from "@/lib/serverLocale";

type HermesSessionDetailPageProps = {
  params: Promise<{ sessionId: string }>;
};

export default async function HermesSessionDetailPage({
  params,
}: HermesSessionDetailPageProps) {
  const locale = await getServerLocale();
  const isZh = locale === "zh";
  const sessionId = (await params).sessionId;
  const [detail, history] = await Promise.all([
    getHermesSessionDetail(sessionId),
    getHermesSessionMessages(sessionId),
  ]);
  const available =
    detail.read_status === "available" &&
    detail.session !== null &&
    history.read_status === "available";

  return (
    <section
      className="space-y-4"
      data-hermes-session-detail={sessionId}
      aria-labelledby="hermes-session-detail-title"
    >
      <header className="space-y-2">
        <Link
          className="font-body-sm text-info underline-offset-2 hover:underline"
          href={localizePath("/hermes/sessions", locale)}
        >
          {isZh ? "← 返回会话记录" : "← Back to sessions"}
        </Link>
        <h1 className="font-headline-lg text-text-primary" id="hermes-session-detail-title">
          {detail.session?.title || detail.session?.preview || (isZh ? "Hermes 会话" : "Hermes session")}
        </h1>
        <p className="font-data-mono text-xs text-text-secondary">{sessionId}</p>
      </header>

      {!available ? (
        <Card tone="warning" data-hermes-session-history-unavailable>
          <p className="font-body-sm font-semibold text-text-primary">
            {isZh ? "无法读取此会话" : "Unable to read this session"}
          </p>
          {[...detail.warnings, ...history.warnings].map((warning) => (
            <p className="mt-2 font-data-mono text-xs text-warning" key={`${warning.code}:${warning.message}`}>
              {warning.code}
            </p>
          ))}
        </Card>
      ) : history.messages.length === 0 ? (
        <Card data-hermes-session-empty>
          <p className="font-body-sm text-text-secondary">
            {isZh ? "此会话没有可展示的用户/助手消息。" : "No displayable user/assistant messages."}
          </p>
        </Card>
      ) : (
        <ol className="space-y-3" data-hermes-session-messages>
          {history.messages.map((message, index) => (
            <li
              className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
              key={`${message.id}:${index}`}
            >
              <Card
                className={`max-w-[88%] ${
                  message.role === "user" ? "border-info/30 bg-info/10" : "bg-bg-surface"
                }`}
              >
                <p className="font-label-caps text-text-secondary">
                  {message.role === "user" ? (isZh ? "你" : "You") : "Hermes"}
                </p>
                <p className="mt-2 whitespace-pre-wrap break-words font-body-sm text-text-primary">
                  {message.content}
                </p>
                {message.timestamp ? (
                  <p className="mt-2 font-data-mono text-[11px] text-text-secondary">
                    {message.timestamp}
                  </p>
                ) : null}
              </Card>
            </li>
          ))}
        </ol>
      )}

      {history.omitted_message_count > 0 ? (
        <p className="font-body-sm text-text-secondary" data-hermes-omitted-message-count>
          {isZh
            ? `为保护敏感工具内容和控制响应大小，省略了 ${history.omitted_message_count} 条系统、工具或较早消息。`
            : `${history.omitted_message_count} system, tool, or older messages were omitted for safety and response bounds.`}
        </p>
      ) : null}
    </section>
  );
}
