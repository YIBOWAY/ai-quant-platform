'use client';

import { useEffect } from "react";

import { useOptionalActiveHermesSession } from "@/lib/hermes/activeSession";
import { isUsableHermesApiSessionId } from "@/lib/hermes/transcriptHelpers";

/**
 * Rehydrates the ready child selected by the server-validated `/hermes`
 * query into the shared active-session context. Transcript and composer read
 * that same context, so refresh does not fall back to a different lineage.
 */
export function HermesSessionDeepLinkBinder({
  hermesSessionId,
}: {
  hermesSessionId: string;
}) {
  const activeSession = useOptionalActiveHermesSession();
  const bindSession = activeSession?.setActiveHermesSession;
  const activeSessionId = activeSession?.hermesSessionId;

  useEffect(() => {
    if (!isUsableHermesApiSessionId(hermesSessionId)) return;
    if (activeSessionId === hermesSessionId) return;
    bindSession?.({ hermesSessionId });
  }, [activeSessionId, bindSession, hermesSessionId]);

  if (!isUsableHermesApiSessionId(hermesSessionId)) {
    return null;
  }
  return (
    <span
      aria-hidden
      className="sr-only"
      data-hermes-session-deep-link
      data-hermes-session-id={hermesSessionId}
    />
  );
}
