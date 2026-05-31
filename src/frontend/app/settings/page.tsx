import { ErrorBanner } from "@/components/ErrorBanner";
import { SettingsThemeSwitcher } from "@/components/SettingsThemeSwitcher";
import { getSettings } from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    eyebrow: "Local Settings",
    title: "Settings",
    intro:
      "Read-only view of backend settings. Secret-like fields are masked by the API before they reach the browser.",
    dumpTitle: "Backend Settings Dump",
    dumpMirrorsPrefix: "This mirrors ",
    dumpMirrorsSuffix: ".",
  },
  zh: {
    eyebrow: "本地设置",
    title: "设置",
    intro:
      "后端设置的只读视图。类似密钥的字段会由 API 在到达浏览器前进行脱敏处理。",
    dumpTitle: "后端设置导出",
    dumpMirrorsPrefix: "此处镜像 ",
    dumpMirrorsSuffix: " 的返回结果。",
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

  return (
    <main className="h-full overflow-y-auto p-container-padding">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <header className="border-b border-border-subtle pb-4">
          <p className="font-label-caps uppercase text-text-secondary">{text.eyebrow}</p>
          <h1 className="mt-2 font-headline-xl text-text-primary">{text.title}</h1>
          <p className="mt-2 max-w-2xl font-body-sm text-text-secondary">
            {text.intro}
          </p>
        </header>

        <ErrorBanner messages={[settings.apiError]} />

        <section className="grid grid-cols-1 gap-6 xl:grid-cols-[320px_1fr]">
          <SettingsThemeSwitcher locale={locale} />

          <div className="rounded border border-border-subtle bg-bg-surface">
            <div className="border-b border-border-subtle px-4 py-3">
              <h2 className="font-headline-lg text-text-primary">{text.dumpTitle}</h2>
              <p className="mt-1 font-body-sm text-text-secondary">
                {text.dumpMirrorsPrefix}
                <span className="font-data-mono">GET /api/settings</span>
                {text.dumpMirrorsSuffix}
              </p>
            </div>
            <pre className="max-h-[70vh] overflow-auto p-4 font-data-mono text-[12px] leading-relaxed text-text-primary">
              {safeSettingsDump(settings)}
            </pre>
          </div>
        </section>
      </div>
    </main>
  );
}
