"use client";

import type { ReactNode } from "react";

/** Site chrome is always on. Hermes desk embeds in the main pane. */
export function AppChrome({
  sidebar,
  topbar,
  children,
}: {
  sidebar: ReactNode;
  topbar: ReactNode;
  children: ReactNode;
}) {
  return (
    <>
      {sidebar}
      {topbar}
      <main className="ml-0 h-screen overflow-hidden bg-bg-base pt-[var(--spacing-topbar-height)] lg:ml-[220px]">
        {children}
      </main>
    </>
  );
}
