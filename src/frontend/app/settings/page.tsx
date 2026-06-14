import { Languages, Lock, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { ErrorBanner } from "@/components/ErrorBanner";
import { LocaleToggle } from "@/components/LocaleToggle";
import { Card, PageHeader, SectionTitle, StatusPill } from "@/components/ui/primitives";
import { getSettings } from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    eyebrow: "Local Settings",
    title: "Settings",
    intro:
      "Read-only view of backend settings. Secret-like fields are masked by the API before they reach the browser.",
    readOnly: "read-only",
    safetyTitle: "Safety Flags",
    safetyHint: "Live mirror of the backend safety footer. This view cannot change them.",
    flagDryRun: "dry_run",
    flagPaper: "paper_trading",
    flagLive: "live_trading",
    flagKill: "kill_switch",
    flagBind: "bind_address",
    on: "on",
    off: "off",
    enabled: "enabled",
    disabled: "disabled",
    armed: "armed",
    dumpTitle: "Backend Settings Dump",
    dumpMirrorsPrefix: "Mirrors ",
    dumpMirrorsSuffix: ". Masked values stay masked (********).",
    interfaceTitle: "Interface",
    interfaceHint: "The only interface preference is the display language. It is stored in a cookie on this machine.",
    languageLabel: "Display language",
  },
  zh: {
    eyebrow: "本地设置",
    title: "设置",
    intro:
      "后端设置的只读视图。类似密钥的字段会由 API 在到达浏览器前进行脱敏处理。",
    readOnly: "只读",
    safetyTitle: "安全开关",
    safetyHint: "后端安全标记的实时镜像。此视图无法修改它们。",
    flagDryRun: "dry_run",
    flagPaper: "paper_trading",
    flagLive: "live_trading",
    flagKill: "kill_switch",
    flagBind: "bind_address",
    on: "开",
    off: "关",
    enabled: "已启用",
    disabled: "已禁用",
    armed: "已布防",
    dumpTitle: "后端设置导出",
    dumpMirrorsPrefix: "镜像 ",
    dumpMirrorsSuffix: " 的返回结果。脱敏字段保持脱敏（********）。",
    interfaceTitle: "界面",
    interfaceHint: "界面偏好仅有显示语言一项，保存在本机 Cookie 中。",
    languageLabel: "显示语言",
  },
} as const;

function safeSettingsDump(settings: Record<string, unknown>) {
  const { safety: _safety, apiError: _apiError, ...rest } = settings;
  return JSON.stringify(rest, null, 2);
}

export default async function SettingsPage() {
  const locale = await getServerLocale();
  const text = copy[locale];
  const settings = await getSettings();
  const safety = settings.safety;

  return (
    <main className="h-full overflow-y-auto p-container-padding">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <PageHeader
          eyebrow={text.eyebrow}
          title={text.title}
          subtitle={text.intro}
          icon={<SlidersHorizontal size={18} className="text-accent-success" />}
          actions={
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-bg-surface px-2 py-1 font-label-caps uppercase text-text-secondary">
              <Lock size={12} />
              {text.readOnly}
            </span>
          }
        />

        <ErrorBanner messages={[settings.apiError]} />

        <Card>
          <SectionTitle
            title={text.safetyTitle}
            hint={text.safetyHint}
            right={<ShieldCheck size={18} className="text-warning" />}
          />
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill
              label={text.flagDryRun}
              value={safety?.dry_run ? text.on : text.off}
              tone={safety?.dry_run ? "success" : "warning"}
            />
            <StatusPill
              label={text.flagPaper}
              value={safety?.paper_trading ? text.on : text.off}
              tone={safety?.paper_trading ? "success" : "warning"}
            />
            <StatusPill
              label={text.flagLive}
              value={safety?.live_trading_enabled ? text.enabled : text.disabled}
              tone={safety?.live_trading_enabled ? "danger" : "success"}
            />
            <StatusPill
              label={text.flagKill}
              value={safety?.kill_switch ? text.armed : text.off}
              tone={safety?.kill_switch ? "info" : "neutral"}
            />
            {safety?.bind_address ? (
              <StatusPill label={text.flagBind} value={safety.bind_address} tone="neutral" />
            ) : null}
          </div>
        </Card>

        <section className="grid grid-cols-1 gap-6 xl:grid-cols-[320px_1fr]">
          <Card padded className="flex h-fit flex-col gap-3">
            <SectionTitle
              title={text.interfaceTitle}
              hint={text.interfaceHint}
              right={<Languages size={18} className="text-text-secondary" />}
            />
            <div className="flex items-center justify-between gap-3">
              <span className="font-body-sm text-text-primary">{text.languageLabel}</span>
              <LocaleToggle />
            </div>
          </Card>

          <Card padded={false} className="flex min-w-0 flex-col">
            <div className="border-b border-border-subtle px-4 py-3">
              <h2 className="font-label-caps text-text-primary">{text.dumpTitle}</h2>
              <p className="mt-1 font-body-sm text-text-secondary">
                {text.dumpMirrorsPrefix}
                <span className="font-data-mono">GET /api/settings</span>
                {text.dumpMirrorsSuffix}
              </p>
            </div>
            <pre className="max-h-[60vh] overflow-auto p-4 font-data-mono text-[12px] leading-relaxed text-text-primary">
              {safeSettingsDump(settings)}
            </pre>
          </Card>
        </section>
      </div>
    </main>
  );
}
