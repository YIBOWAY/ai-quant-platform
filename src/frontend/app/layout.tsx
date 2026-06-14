import type { Metadata } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';
import { Sidebar } from '@/components/Sidebar';
import { TopBar } from '@/components/TopBar';
import { SafetyStrip } from '@/components/SafetyStrip';
import { Providers } from '@/components/Providers';
import { LocaleProvider } from '@/components/LocaleProvider';
import { getServerLocale } from '@/lib/serverLocale';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
});

export const metadata: Metadata = {
  title: 'QUANTUM_CORE',
  description: 'AI Quant Platform',
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getServerLocale();
  return (
    <html lang={locale === 'zh' ? 'zh' : 'en'} className={`dark ${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="min-h-screen bg-bg-base antialiased selection:bg-accent-success selection:text-bg-base">
        <LocaleProvider locale={locale}>
          <Providers>
            <Sidebar />
            <TopBar />
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
