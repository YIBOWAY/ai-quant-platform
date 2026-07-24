'use client';

import Link from "next/link";
import { useMemo } from "react";
import { formatDateTime } from "@/components/hermes/artifacts/formatters";
import {
  commandStateLabel,
  isInFlightCommandState,
  sortCommandsNewestFirst,
} from "@/lib/hermes/commandActivity";
import { hermesCommandKindTitle, hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { hermesRouteHref } from "@/lib/hermes/routes";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import type { Locale } from "@/lib/locale";

export type TodayRunningProps = {
  locale: Locale;
};

const MAX_ROWS = 5;

/**
 * UI-1 Direction A "Running" lane: chat on + non-terminal commands only,
 * event-state text (no progress percentages, per spec §6.2). Honest absence
 * when chat is off (no spine provider → empty command list → null).
 */
export function TodayRunning({ locale }: TodayRunningProps) {
  const isZh = locale === "zh";
  const copy = hermesWorkbenchCopy(locale).today.running;
  const { state: follow } = useWorkspaceFollow();

  const rows = useMemo(
    () =>
      sortCommandsNewestFirst(follow.commands)
        .filter((command) => isInFlightCommandState(command.state))
        .slice(0, MAX_ROWS),
    [follow.commands],
  );

  if (rows.length === 0) {
    return null;
  }

  return (
    <section aria-labelledby="hermes-running-title" data-hermes-running>
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="font-body-sm font-semibold text-text-primary" id="hermes-running-title">
          {copy.title}
        </h2>
        <span className="font-data-mono text-xs text-text-secondary" data-hermes-running-count>
          {rows.length}
        </span>
        <Link
          className="ml-auto font-body-sm text-text-secondary underline-offset-2 hover:text-info hover:underline"
          href={hermesRouteHref("tasks", locale)}
        >
          {copy.viewAll}
        </Link>
      </div>
      <ol className="mt-1 border-t border-border-subtle">
        {rows.map((row) => {
          const when = row.created_at || row.updated_at || "";
          return (
            <li
              className="flex flex-wrap items-center gap-3 border-b border-border-subtle py-2.5"
              data-hermes-command-id={row.command_id}
              data-hermes-command-state={row.state}
              data-hermes-running-row
              key={row.command_id}
            >
              <span className="inline-flex shrink-0 items-center rounded-lg border border-info/30 bg-info/10 px-2 py-0.5 font-data-mono text-[10.5px] uppercase text-info">
                {commandStateLabel(row.state, isZh)}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate font-body-sm font-medium text-text-primary">
                  {hermesCommandKindTitle(row.kind, locale)}
                </p>
                <p className="font-body-sm text-text-secondary">
                  {row.state === "delivered"
                    ? copy.waitingReceipt
                    : `${isZh ? "事件流" : "event stream"} · ${row.state}`}
                </p>
              </div>
              <span className="shrink-0 font-data-mono text-[11px] text-text-secondary">
                {when ? `${copy.startedPrefix} ${formatDateTime(when, locale)}` : ""}
                {typeof row.attempt_count === "number" && row.attempt_count > 0
                  ? ` · ${copy.attempts(row.attempt_count)}`
                  : ""}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
