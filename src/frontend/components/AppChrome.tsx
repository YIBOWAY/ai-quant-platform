"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { splitLocalePath } from "@/lib/locale";

export function AppChrome({
  sidebar,
  topbar,
  children,
}: {
  sidebar: ReactNode;
  topbar: ReactNode;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const path = splitLocalePath(pathname).pathname;
  const hermesDesk = path === "/hermes" || path.startsWith("/hermes/");

  if (hermesDesk) {
    return (
      <div className="h-screen overflow-hidden bg-bg-base" data-app-chrome="hermes-desk">
        {children}
      </div>
    );
  }

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
