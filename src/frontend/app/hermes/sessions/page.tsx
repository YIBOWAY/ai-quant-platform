import Link from "next/link";
import { Card, StatusPill } from "@/components/ui/primitives";
import { getHermesGatewayStatus, getHermesSessions } from "@/lib/api";
import { localizePath } from "@/lib/locale";
import { getServerLocale } from "@/lib/serverLocale";

function formatSessionTime(value: string | null | undefined, locale: string): string {
  if (!value) return "--";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(locale === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  });
}

export default async function HermesSessionsPage() {
  const locale = await getServerLocale();
  const isZh = locale === "zh";
  const [gateway, sessions] = await Promise.all([
    getHermesGatewayStatus(),
    getHermesSessions(),
  ]);
  const available =
    gateway.connected &&
    gateway.session_api_available &&
    sessions.read_status === "available";

  return (
    <section className="space-y-4" data-hermes-sessions aria-labelledby="hermes-sessions-title">
      <header className="space-y-2">
        <p className="font-label-caps uppercase text-text-secondary">
          {isZh ? "Hermes 会话" : "Hermes sessions"}
        </p>
        <h1 className="font-headline-lg text-text-primary" id="hermes-sessions-title">
          {isZh ? "真实会话记录" : "Live session records"}
        </h1>
        <p className="max-w-3xl font-body-sm text-text-secondary">
          {isZh
            ? "通过平台服务端只读连接本机 Hermes 官方 API。这里读取已保存的会话，不会提交提示词，也不会消耗 Codex 或 Grok 额度。"
            : "Read-only access to persisted local Hermes sessions through the platform BFF. This view submits no prompt and consumes no provider quota."}
        </p>
      </header>

      <Card className="flex flex-wrap items-center gap-2" tone={available ? "info" : "warning"}>
        <StatusPill
          label={isZh ? "连接" : "Connection"}
          value={available ? (isZh ? "只读已连接" : "Read connected") : (isZh ? "不可用" : "Unavailable")}
          tone={available ? "info" : "warning"}
        />
        <StatusPill label="Hermes model" value={gateway.model ?? "--"} />
        <StatusPill
          label={isZh ? "本页" : "This page"}
          value={isZh ? "只读记录" : "Read-only records"}
          tone="info"
        />
      </Card>

      {!available ? (
        <Card tone="warning" data-hermes-sessions-unavailable>
          <p className="font-body-sm font-semibold text-text-primary">
            {isZh ? "Hermes 会话源当前不可用" : "Hermes session source unavailable"}
          </p>
          <p className="mt-1 font-body-sm text-text-secondary">
            {isZh
              ? "请启动 8642 API Server，并为平台配置 owner-only API key 文件。页面不会回退到旧 AgentRunner。"
              : "Start the API Server on 8642 and configure an owner-only key file. This page never falls back to the legacy AgentRunner."}
          </p>
          {[...gateway.warnings, ...sessions.warnings].map((warning) => (
            <p className="mt-2 font-data-mono text-xs text-warning" key={`${warning.code}:${warning.message}`}>
              {warning.code}
            </p>
          ))}
        </Card>
      ) : sessions.sessions.length === 0 ? (
        <Card>
          <p className="font-body-sm text-text-secondary">
            {isZh ? "Hermes 当前没有已保存会话。" : "Hermes has no persisted sessions yet."}
          </p>
        </Card>
      ) : (
        <div className="space-y-3">
          <ul className="grid gap-3" data-hermes-session-list>
            {sessions.sessions.map((session) => {
              const cardTitle = session.title || session.preview || session.id;
              // Only render the preview line when it adds information beyond
              // the title (empty titles fall back to the preview above).
              const previewLine =
                session.preview && session.preview !== cardTitle ? session.preview : null;
              return (
              <li
                data-hermes-session-message-count={session.message_count ?? 0}
                key={session.id}
              >
                <Card className="transition-colors hover:border-info/40">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <Link
                        className="app-touch-target inline-flex items-center font-body-sm font-semibold text-text-primary underline-offset-2 hover:text-info hover:underline"
                        href={localizePath(`/hermes/sessions/${encodeURIComponent(session.id)}`, locale)}
                      >
                        {cardTitle}
                      </Link>
                      {previewLine ? (
                        <p className="mt-1 line-clamp-2 font-body-sm text-text-secondary">
                          {previewLine}
                        </p>
                      ) : null}
                    </div>
                    <div className="shrink-0 text-right font-data-mono text-xs text-text-secondary">
                      <p>{session.message_count ?? 0} {isZh ? "条消息" : "messages"}</p>
                      <p className="mt-1">{formatSessionTime(session.last_active, locale)}</p>
                    </div>
                  </div>
                </Card>
              </li>
              );
            })}
          </ul>
          {sessions.has_more ? (
            <p className="font-body-sm text-text-secondary" data-hermes-sessions-has-more>
              {isZh
                ? `当前展示最近 ${sessions.sessions.length} 个会话；更早记录尚未加载。`
                : `Showing the latest ${sessions.sessions.length} sessions; older records are not loaded yet.`}
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}
