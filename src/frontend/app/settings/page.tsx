import { SettingsThemeSwitcher } from "@/components/SettingsThemeSwitcher";
import { getSettings } from "@/lib/api";

function safeSettingsDump(settings: Record<string, unknown>) {
  const { safety: _safety, apiError: _apiError, ...rest } = settings;
  return JSON.stringify(rest, null, 2);
}

export default async function SettingsPage() {
  const settings = await getSettings();

  return (
    <main className="h-full overflow-y-auto p-container-padding">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <header className="border-b border-border-subtle pb-4">
          <p className="font-label-caps uppercase text-text-secondary">Local Settings</p>
          <h1 className="mt-2 font-headline-xl text-text-primary">Settings</h1>
          <p className="mt-2 max-w-2xl font-body-sm text-text-secondary">
            Read-only view of backend settings. Secret-like fields are masked by the API before
            they reach the browser.
          </p>
        </header>

        {settings.apiError ? (
          <div className="rounded border border-danger/40 bg-danger/10 p-4 font-body-sm text-danger">
            Backend unavailable: {settings.apiError}
          </div>
        ) : null}

        <section className="grid grid-cols-1 gap-6 xl:grid-cols-[320px_1fr]">
          <SettingsThemeSwitcher />

          <div className="rounded border border-border-subtle bg-bg-surface">
            <div className="border-b border-border-subtle px-4 py-3">
              <h2 className="font-headline-lg text-text-primary">Backend Settings Dump</h2>
              <p className="mt-1 font-body-sm text-text-secondary">
                This mirrors <span className="font-data-mono">GET /api/settings</span>.
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
