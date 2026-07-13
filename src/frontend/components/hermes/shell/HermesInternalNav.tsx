"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { hermesRouteHref } from "@/lib/hermes/routes";
import type { Locale } from "@/lib/locale";
import { splitLocalePath } from "@/lib/locale";

export type HermesInternalNavProps = {
  locale: Locale;
};

type NavEntry =
  | {
      id: "today" | "tasks" | "approvals" | "results";
      kind: "link";
      label: string;
      href: string;
    }
  | {
      id: "conversation";
      kind: "unavailable";
      label: string;
      unavailableLabel: string;
    };

export function HermesInternalNav({ locale }: HermesInternalNavProps) {
  const pathname = usePathname();
  const activePath = splitLocalePath(pathname).pathname;
  const text = hermesWorkbenchCopy(locale);

  const entries: NavEntry[] = [
    {
      id: "today",
      kind: "link",
      label: text.nav.today,
      href: hermesRouteHref("today", locale),
    },
    {
      id: "conversation",
      kind: "unavailable",
      label: text.nav.conversation,
      unavailableLabel: text.nav.conversationUnavailable,
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
      className="shrink-0 border-b border-border-subtle bg-bg-surface px-3 py-2"
    >
      <ul className="mx-auto flex w-full max-w-[var(--spacing-hermes-content-max)] flex-wrap gap-2">
        {entries.map((entry) => {
          if (entry.kind === "unavailable") {
            return (
              <li key={entry.id}>
                <span
                  aria-disabled="true"
                  className="app-touch-target inline-flex items-center justify-center rounded-lg border border-border-subtle px-3 font-body-sm text-text-secondary opacity-60"
                  title={entry.unavailableLabel}
                >
                  {entry.label}
                </span>
              </li>
            );
          }

          const barePath = splitLocalePath(entry.href).pathname;
          const isActive =
            barePath === "/hermes"
              ? activePath === "/hermes"
              : activePath === barePath || activePath.startsWith(`${barePath}/`);

          return (
            <li key={entry.id}>
              <Link
                aria-current={isActive ? "page" : undefined}
                className={`app-touch-target inline-flex items-center justify-center rounded-lg border px-3 font-body-sm transition-colors ${
                  isActive
                    ? "border-info/40 bg-info/10 text-text-primary"
                    : "border-border-subtle text-text-secondary hover:bg-bg-surface-muted hover:text-text-primary"
                }`}
                href={entry.href}
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
