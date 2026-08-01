"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { hermesRouteHref } from "@/lib/hermes/routes";
import type { Locale } from "@/lib/locale";
import { splitLocalePath } from "@/lib/locale";

export type HermesInternalNavProps = {
  locale: Locale;
};

type NavEntry = {
  id: "today" | "sessions" | "tasks" | "approvals" | "results";
  kind: "link";
  label: string;
  href: string;
};

export function HermesInternalNav({ locale }: HermesInternalNavProps) {
  const pathname = usePathname();
  const activePath = splitLocalePath(pathname).pathname;
  const text = hermesWorkbenchCopy(locale);

  // UI-2: tab switches land at the top of the internal scroll region so the
  // user never stays mid-page wondering whether anything changed. The tab row
  // itself already stays visible (scroll happens inside the region below it).
  useEffect(() => {
    document
      .querySelectorAll<HTMLElement>("[data-page-scroll-region]")
      .forEach((node) => {
        node.scrollTop = 0;
      });
  }, [activePath]);

  const entries: NavEntry[] = [
    {
      id: "today",
      kind: "link",
      label: text.nav.today,
      href: hermesRouteHref("today", locale),
    },
    {
      id: "sessions",
      kind: "link",
      label: text.nav.sessions,
      href: hermesRouteHref("sessions", locale),
    },
    {
      id: "tasks",
      kind: "link",
      label: text.nav.tasks,
      href: hermesRouteHref("tasks", locale),
    },
    {
      id: "approvals",
      kind: "link",
      label: text.nav.approvals,
      href: hermesRouteHref("approvals", locale),
    },
    {
      id: "results",
      kind: "link",
      label: text.nav.results,
      href: hermesRouteHref("results", locale),
    },
  ];

  return (
    <nav
      aria-label={text.nav.landmark}
      // The dock rail is fixed to the right edge and overlays this row while
      // chat is active, so the last tab needs a rail-width gutter to stay
      // clickable.
      className="shrink-0 border-b border-border-subtle bg-bg-surface pl-3 pr-[var(--spacing-dock-rail)]"
    >
      <ul className="mx-auto flex w-full max-w-[var(--spacing-hermes-content-max)] flex-wrap gap-6">
        {entries.map((entry) => {
          const barePath = splitLocalePath(entry.href).pathname;
          const isActive =
            barePath === "/hermes"
              ? activePath === "/hermes"
              : activePath === barePath || activePath.startsWith(`${barePath}/`);

          return (
            <li key={entry.id}>
              <Link
                aria-current={isActive ? "page" : undefined}
                className={`app-touch-target -mb-px inline-flex items-center justify-center border-b-2 font-body-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info ${
                  isActive
                    ? "border-[var(--color-hermes)] text-text-primary"
                    : "border-transparent text-text-secondary hover:text-text-primary"
                }`}
                href={entry.href}
                prefetch={false}
              >
                {entry.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
