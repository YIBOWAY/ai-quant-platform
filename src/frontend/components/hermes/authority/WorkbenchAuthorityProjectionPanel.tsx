'use client';

import { useMemo, useState } from "react";

import { Panel } from "@/components/ui/Panel";
import {
  COLLAPSE_TOGGLE_CLASS,
  displayId,
  LONG_ID_CLASS,
} from "@/lib/hermes/workbenchA11y";
import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import { resultIdsFromProjection } from "@/lib/hermes/workspaceFollowSpine";
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
 * L5b-Authority-Projection-M1: read-only Task / Attempt / Run / result-ref slots (ids only; typed body lives in Typed results panel)
 * from the shared follow spine snapshot. Empty is honest — never invent HQA
 * rows from conversation commands. This projection has no mutation controls.
 * L5c: shared collapse/long-id a11y contracts.
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
        ids: resultIdsFromProjection(follow.results as never),
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
    <Panel
      data-hermes-authority-projection=""
      data-hermes-authority-observe="l5b-m1"
      headerExtra={
        <div className="flex items-center gap-2">
          <span
            className="font-body-sm text-text-secondary"
            data-hermes-authority-count
          >
            {isZh
              ? `${totalIds} 条引用 · 只读`
              : `${totalIds} ref${totalIds === 1 ? "" : "s"} · read-only`}
          </span>
          <button
            aria-controls="hermes-authority-projection-body"
            aria-expanded={open}
            className={COLLAPSE_TOGGLE_CLASS}
            data-hermes-authority-toggle
            onClick={() => setOpen((v) => !v)}
            type="button"
          >
            {open ? (isZh ? "收起" : "Hide") : isZh ? "展开" : "Show"}
          </button>
        </div>
      }
      title={isZh ? "关联记录" : "Linked records"}
    >
      <div
        className="min-w-0"
        data-hermes-authority-projection-body
        id="hermes-authority-projection-body"
      >
        <p className="font-body-sm text-text-secondary break-words">
          {isZh
            ? "用于核对任务、执行与结果是否对应。这里只展示已保存的编号，缺少的记录保持空白。"
            : "Match saved task, execution and result IDs. Missing records remain empty."}
        </p>

        {!spineReady ? (
          <p className="mt-2 font-body-sm text-text-secondary">
            {isZh ? "正在读取记录…" : "Loading records…"}
          </p>
        ) : null}

        {spineReady && !open && totalIds ? (
          <p className="mt-2 font-body-sm text-text-secondary">
            {isZh ? `${totalIds} 项已折叠` : `${totalIds} hidden`}
          </p>
        ) : null}

        {spineReady && open ? (
          <ul
            aria-live="polite"
            className="mt-2 divide-y divide-border-subtle border-t border-border-subtle"
            data-hermes-authority-slots
          >
            {slots.map((slot) => (
              <li
                className="min-w-0 py-2"
                data-hermes-authority-slot={slot.key}
                data-hermes-authority-health={slot.health}
                key={slot.key}
              >
                <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
                  <p className="min-w-0 font-body-sm font-semibold text-text-primary">
                    {isZh ? slot.labelZh : slot.labelEn}
                    <span className="ml-2 font-data-mono text-[11px] font-normal text-text-secondary">
                      {slot.ids.length}
                    </span>
                  </p>
                  <p
                    className="shrink-0 font-data-mono text-[11px] text-text-secondary"
                    data-hermes-authority-health-label
                  >
                    {slot.health}
                  </p>
                </div>
                {slot.ids.length === 0 ? (
                  <p
                    className="mt-1 break-words font-body-sm text-text-secondary"
                    data-hermes-authority-empty={slot.key}
                  >
                    {isZh
                      ? "暂无对应记录。"
                      : "No linked records."}
                  </p>
                ) : (
                  <ul className="mt-1 min-w-0 space-y-0.5">
                    {slot.ids.map((id) => (
                      <li className={LONG_ID_CLASS} key={id} title={id}>
                        {displayId(id, { head: 16, tail: 6 })}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Panel>
  );
}
