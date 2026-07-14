"use client";

import Link from "next/link";
import { useState } from "react";
import type { BriefArchivePayload, BriefSourceWatermark } from "@/lib/briefArchive";
import { createBriefArchive } from "@/lib/briefArchiveSave";
import { localizePath } from "@/lib/locale";

type Props = {
  disabledReason?: string | null;
  initialPublicId: string | null;
  locale: "en" | "zh";
  payload: BriefArchivePayload;
  sourceWatermark: BriefSourceWatermark;
};

export function BriefArchiveControl({
  disabledReason,
  initialPublicId,
  locale,
  payload,
  sourceWatermark,
}: Props) {
  const [publicId, setPublicId] = useState(initialPublicId);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState("");
  const isZh = locale === "zh";

  async function saveSnapshot() {
    if (disabledReason) {
      return;
    }
    setState("saving");
    setError("");
    try {
      const envelope = await createBriefArchive(payload, sourceWatermark);
      setPublicId(envelope.issue.public_id);
      setState("saved");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : isZh ? "归档保存失败" : "Archive save failed");
      setState("error");
    }
  }

  return (
    <div className="mt-4 flex flex-wrap items-center justify-center gap-3 font-data-mono text-xs">
      <button
        className="border border-editorial-accent px-3 py-2 text-editorial-accent transition-colors hover:bg-editorial-accent hover:text-paper-ink disabled:cursor-wait disabled:opacity-60"
        disabled={state === "saving" || Boolean(disabledReason)}
        onClick={saveSnapshot}
        type="button"
      >
        {state === "saving"
          ? isZh ? "正在保存…" : "Saving…"
          : publicId
            ? isZh ? "更新今日归档" : "Update today's archive"
            : isZh ? "保存今日归档" : "Save today's archive"}
      </button>
      {disabledReason ? (
        <span className="max-w-xl text-warning" role="status">{disabledReason}</span>
      ) : null}
      {publicId ? (
        <Link
          className="text-ink-secondary underline decoration-editorial-rule underline-offset-4 hover:text-ink"
          href={localizePath(`/brief/${publicId}`, locale)}
        >
          {isZh ? "查看已保存版本" : "Open saved issue"}
        </Link>
      ) : null}
      {state === "saved" ? <span className="text-editorial-up">{isZh ? "已写入数据库" : "Saved to database"}</span> : null}
      {state === "error" ? <span className="max-w-xl text-danger" role="alert">{error}</span> : null}
    </div>
  );
}
