import type { Metadata } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';
import { Sidebar } from '@/components/Sidebar';
import { TopBar } from '@/components/TopBar';
import { SafetyStrip } from '@/components/SafetyStrip';

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

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="antialiased overflow-hidden selection:bg-accent-success selection:text-bg-base">
        <Sidebar />
        <TopBar />
        <SafetyStrip />
        <main className="fixed top-[100px] left-[240px] right-0 bottom-0 bg-bg-base flex flex-col overflow-hidden">
          {children}
        </main>
      </body>
    </html>
  );
}
