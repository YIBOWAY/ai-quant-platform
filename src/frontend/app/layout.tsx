import type { Metadata } from 'next';
import { Inter, JetBrains_Mono, Noto_Serif_SC, Source_Serif_4 } from 'next/font/google';
import './globals.css';
import { Sidebar } from '@/components/Sidebar';
import { TopBar } from '@/components/TopBar';
import { SafetyStrip } from '@/components/SafetyStrip';
import { Providers } from '@/components/Providers';
import { LocaleProvider } from '@/components/LocaleProvider';
import { hermesFeatureFlags } from '@/lib/hermes/featureFlags';
import { getServerLocale } from '@/lib/serverLocale';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
});

const sourceSerif = Source_Serif_4({
  subsets: ['latin'],
  weight: ['400', '600', '700'],
  style: ['normal', 'italic'],
  variable: '--font-serif',
  display: 'swap',
  fallback: ['Georgia', 'serif'],
});

const notoSerifSC = Noto_Serif_SC({
  subsets: ['latin'],
  weight: ['400', '700'],
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
  const shellEnabled = hermesFeatureFlags().shell;
  return (
    <html
      lang={locale === 'zh' ? 'zh' : 'en'}
      className={`dark ${inter.variable} ${jetbrainsMono.variable} ${sourceSerif.variable} ${notoSerifSC.variable}`}
    >
      <body className="min-h-screen bg-bg-base antialiased selection:bg-info selection:text-bg-base">
        <LocaleProvider locale={locale}>
          <Providers>
            <Sidebar shellEnabled={shellEnabled} />
            <TopBar shellEnabled={shellEnabled} />
            <SafetyStrip />
            {/* h-screen + pt makes the content area a *fixed* height box (viewport
                minus the 100px topbar+safety strip), so child pages using h-full /
                flex-1 can size correctly instead of collapsing to content height. */}
            <main className="ml-0 h-screen overflow-hidden bg-bg-base pt-[100px] lg:ml-[240px]">
              {children}
            </main>
          </Providers>
        </LocaleProvider>
      </body>
    </html>
  );
}
