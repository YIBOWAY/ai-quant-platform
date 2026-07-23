import Link from "next/link";
import { HermesSessionForkController } from "@/components/hermes/sessions/HermesSessionForkController";
import { HermesSessionLatestAnchor } from "@/components/hermes/sessions/HermesSessionLatestAnchor";
import { Card } from "@/components/ui/primitives";
import { getHermesSessionDetail, getHermesSessionMessages } from "@/lib/api";
import { displayableTranscriptMessages } from "@/lib/hermes/transcriptHelpers";
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
  const displayMessages = displayableTranscriptMessages(history.messages);

  return (
    <section
      className="space-y-4"
      data-hermes-session-detail={sessionId}
      aria-labelledby="hermes-session-detail-title"
    >
      <header
        className="sticky top-0 z-20 -mx-2 space-y-2 border-b border-border-subtle bg-[var(--color-hermes-canvas)] px-2 pb-3 pt-1 shadow-[0_8px_16px_rgba(0,0,0,0.18)]"
        data-hermes-session-context
      >
        <Link
          className="app-touch-target inline-flex items-center font-body-sm text-info underline-offset-2 hover:underline"
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
      ) : (
        <>
          <HermesSessionForkController
            emptyHint={
              isZh
                ? "此会话没有可展示的用户/助手消息。"
                : "No displayable user/assistant messages."
            }
            forkEligible={detail.fork_context.eligible === true}
            forkReasonCode={detail.fork_context.reason_code}
            hermesSessionId={sessionId}
            isZh={isZh}
            locale={locale}
            messages={displayMessages}
            omittedCount={history.omitted_message_count}
          />
          {displayMessages.length > 0 ? <HermesSessionLatestAnchor /> : null}
        </>
      )}
    </section>
  );
}
