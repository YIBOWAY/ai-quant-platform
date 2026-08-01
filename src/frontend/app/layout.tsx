import type { Metadata } from 'next';
import localFont from 'next/font/local';
import './globals.css';
import { Sidebar } from '@/components/Sidebar';
import { TopBar } from '@/components/TopBar';
import { SafetyBadge } from '@/components/SafetyBadge';
import { Providers } from '@/components/Providers';
import { LocaleProvider } from '@/components/LocaleProvider';
import { hermesFeatureFlags } from '@/lib/hermes/featureFlags';
import { getServerLocale } from '@/lib/serverLocale';

// V1.4: fonts are vendored under ./fonts and loaded via next/font/local so the
// production build is fully offline (next/font/google downloads at build time).
// The four CSS variables (--font-sans/mono/serif/serif-sc) are unchanged, so
// globals.css and every consumer keep working untouched.
const inter = localFont({
  src: './fonts/inter-var.woff2',
  variable: '--font-sans',
  display: 'swap',
  fallback: ['system-ui', 'sans-serif'],
});

const jetbrainsMono = localFont({
  src: './fonts/jetbrains-mono-var.woff2',
  variable: '--font-mono',
  display: 'swap',
  fallback: ['ui-monospace', 'monospace'],
});

const sourceSerif = localFont({
  src: [
    { path: './fonts/source-serif-4-400-normal.woff2', weight: '400', style: 'normal' },
    { path: './fonts/source-serif-4-400-italic.woff2', weight: '400', style: 'italic' },
    { path: './fonts/source-serif-4-600-normal.woff2', weight: '600', style: 'normal' },
    { path: './fonts/source-serif-4-600-italic.woff2', weight: '600', style: 'italic' },
    { path: './fonts/source-serif-4-700-normal.woff2', weight: '700', style: 'normal' },
    { path: './fonts/source-serif-4-700-italic.woff2', weight: '700', style: 'italic' },
  ],
  variable: '--font-serif',
  display: 'swap',
  fallback: ['Georgia', 'serif'],
});

const notoSerifSC = localFont({
  src: [
    { path: './fonts/noto-serif-sc-400.woff2', weight: '400', style: 'normal' },
    { path: './fonts/noto-serif-sc-700.woff2', weight: '700', style: 'normal' },
  ],
  variable: '--font-serif-sc',
  display: 'swap',
  fallback: ['Songti SC', 'serif'],
});

export const metadata: Metadata = {
  title: 'QUANTUM_CORE',
  description: 'AI Quant Platform',
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getServerLocale();
  const flags = hermesFeatureFlags();
  const shellEnabled = flags.shell;
  return (
    <html
      lang={locale === 'zh' ? 'zh' : 'en'}
      className={`dark ${inter.variable} ${jetbrainsMono.variable} ${sourceSerif.variable} ${notoSerifSC.variable}`}
    >
      <body className="min-h-screen bg-bg-base antialiased selection:bg-info selection:text-bg-base">
        <LocaleProvider locale={locale}>
          <Providers>
            <Sidebar
              agentStudioRedirect={flags.agentStudioRedirect}
              shellEnabled={shellEnabled}
            />
            <TopBar
              agentStudioRedirect={flags.agentStudioRedirect}
              safetySlot={<SafetyBadge />}
              shellEnabled={shellEnabled}
            />
            {/* h-screen + pt makes the content area a *fixed* height box (viewport
                minus the topbar), so child pages using h-full / flex-1 can size
                correctly instead of collapsing to content height. */}
            <main className="ml-0 h-screen overflow-hidden bg-bg-base pt-[var(--spacing-topbar-height)] lg:ml-[220px]">
              {children}
            </main>
          </Providers>
        </LocaleProvider>
      </body>
    </html>
  );
}
