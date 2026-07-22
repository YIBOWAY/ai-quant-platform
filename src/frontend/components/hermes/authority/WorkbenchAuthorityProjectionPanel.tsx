'use client';

import { useMemo, useState } from "react";

import { shortId } from "@/lib/hermes/commandActivity";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import type { Locale } from "@/lib/locale";

export type WorkbenchAuthorityProjectionPanelProps = {
  locale: Locale;
};

type AuthoritySlot = {
  key: "task" | "attempt" | "run" | "result";
  labelEn: string;
  labelZh: string;
  ids: string[];
  health: string;
};

/**
 * L5b-Authority-Projection-M1: read-only Task / Attempt / Run / result-ref slots
 * from the shared follow spine snapshot. Empty is honest — never invent HQA
 * rows from conversation commands. ≠ /hermes/tasks research page; no mutation.
 */
export function WorkbenchAuthorityProjectionPanel({
  locale,
}: WorkbenchAuthorityProjectionPanelProps) {
  const isZh = locale === "zh";
  const [open, setOpen] = useState(true);
  const { state: follow } = useWorkspaceFollow();

  const slots: AuthoritySlot[] = useMemo(() => {
    const health = follow.authorityHealth ?? {};
    return [
      {
        key: "task",
        labelEn: "Tasks",
        labelZh: "任务",
        ids: Array.isArray(follow.tasks) ? follow.tasks : [],
        health: health.task ?? "unavailable",
      },
      {
        key: "attempt",
        labelEn: "Attempts",
        labelZh: "尝试",
        ids: Array.isArray(follow.attempts) ? follow.attempts : [],
        health: health.attempt ?? "unavailable",
      },
      {
        key: "run",
        labelEn: "Runs",
        labelZh: "运行",
        ids: Array.isArray(follow.runs) ? follow.runs : [],
        health: health.run ?? "unavailable",
      },
      {
        key: "result",
        labelEn: "Results",
        labelZh: "结果",
        ids: Array.isArray(follow.results) ? follow.results : [],
        health: health.result ?? "unavailable",
      },
    ];
  }, [
    follow.tasks,
    follow.attempts,
    follow.runs,
    follow.results,
    follow.authorityHealth,
  ]);

  const totalIds = slots.reduce((n, s) => n + s.ids.length, 0);
  const spineReady =
    follow.snapshotCursor != null || follow.transport !== "idle";

  return (
    <section
      aria-label={isZh ? "权威投影观察" : "Authority projection observe"}
      className="space-y-2"
      data-hermes-authority-projection
      data-hermes-authority-observe="l5b-m1"
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <h2 className="font-headline-sm text-text-primary">
            {isZh ? "权威" : "Authority"}
          </h2>
          <p
            className="font-body-sm text-text-secondary"
            data-hermes-authority-count
          >
            {isZh
              ? `${totalIds} 条引用 · 只读`
              : `${totalIds} ref${totalIds === 1 ? "" : "s"} · read-only`}
          </p>
        </div>
        <button
          aria-controls="hermes-authority-projection-body"
          aria-expanded={open}
          className="app-touch-target rounded border border-border-subtle px-2 py-0.5 font-body-sm text-text-primary hover:bg-bg-surface"
          data-hermes-authority-toggle
          onClick={() => setOpen((v) => !v)}
          type="button"
        >
          {open ? (isZh ? "收起" : "Hide") : isZh ? "展开" : "Show"}
        </button>
      </header>

      {open ? (
        <div
          className="rounded-lg border border-border-subtle bg-bg-surface"
          data-hermes-authority-projection-body
          id="hermes-authority-projection-body"
        >
          <p className="border-b border-border-subtle px-3 py-2 font-body-sm text-text-secondary">
            {isZh
              ? "只读：HQA Task / Attempt / Run / result-ref 槽位。普通 conversation_turn 不会伪造 Attempt。投影未接时诚实为空；≠ /hermes/tasks 研究任务页；无 stop/gate 写端。"
              : "Read-only: HQA Task / Attempt / Run / result-ref slots. Ordinary conversation_turn never invents Attempt rows. Empty is honest until projectors land; not the /hermes/tasks research page; no stop/gate write."}
          </p>

          {!spineReady ? (
            <p className="px-3 py-4 font-body-sm text-text-secondary">
              {isZh ? "follow spine 尚未就绪…" : "Follow spine not ready yet…"}
            </p>
          ) : null}

          {spineReady ? (
            <ul
              className="divide-y divide-border-subtle"
              data-hermes-authority-slots
            >
              {slots.map((slot) => (
                <li
                  className="px-3 py-2"
                  data-hermes-authority-slot={slot.key}
                  data-hermes-authority-health={slot.health}
                  key={slot.key}
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <p className="font-body-sm font-semibold text-text-primary">
                      {isZh ? slot.labelZh : slot.labelEn}
                      <span className="ml-2 font-data-mono text-[11px] font-normal text-text-secondary">
                        {slot.ids.length}
                      </span>
                    </p>
                    <p
                      className="font-data-mono text-[11px] text-text-secondary"
                      data-hermes-authority-health-label
                    >
                      {slot.health}
                    </p>
                  </div>
                  {slot.ids.length === 0 ? (
                    <p
                      className="mt-1 font-body-sm text-text-secondary"
                      data-hermes-authority-empty={slot.key}
                    >
                      {isZh
                        ? "无权威行（不从 commands 伪造）。"
                        : "No authority rows (none invented from commands)."}
                    </p>
                  ) : (
                    <ul className="mt-1 space-y-0.5 font-data-mono text-[11px] text-text-secondary">
                      {slot.ids.map((id) => (
                        <li key={id} title={id}>
                          {shortId(id, 16)}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
