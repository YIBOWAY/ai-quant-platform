'use client';

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { isUsableHermesApiSessionId } from "@/lib/hermes/transcriptHelpers";

export type SetActiveHermesSessionInput = {
  hermesSessionId: string | null | undefined;
  commandId?: string | null;
  /**
   * When true, only bind if no session is active yet.
   * Snapshot bootstrap uses this so a late response cannot clobber a
   * fresher deliver-time bind (L3a race nit).
   */
  onlyIfEmpty?: boolean;
};

export type ActiveHermesSessionValue = {
  /** Hermes API session id (often `run_…`); never registry `web_` / workspace `wm_`. */
  hermesSessionId: string | null;
  /** Last command id that bound this session (debug/status only). */
  boundCommandId: string | null;
  setActiveHermesSession: (next: SetActiveHermesSessionInput) => void;
  /** Bump to force transcript reload without changing session id. */
  transcriptEpoch: number;
  bumpTranscript: () => void;
};

const ActiveHermesSessionContext =
  createContext<ActiveHermesSessionValue | null>(null);

export function ActiveHermesSessionProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [hermesSessionId, setHermesSessionId] = useState<string | null>(null);
  const [boundCommandId, setBoundCommandId] = useState<string | null>(null);
  const [transcriptEpoch, setTranscriptEpoch] = useState(0);
  // Synchronous mirror so onlyIfEmpty / same-id checks do not race setState.
  const hermesSessionIdRef = useRef<string | null>(null);

  const setActiveHermesSession = useCallback(
    (next: SetActiveHermesSessionInput) => {
      if (!isUsableHermesApiSessionId(next.hermesSessionId)) {
        return;
      }
      const id = next.hermesSessionId.trim();
      const prev = hermesSessionIdRef.current;
      if (next.onlyIfEmpty && prev != null) {
        return;
      }
      const idChanged = prev !== id;
      if (idChanged) {
        hermesSessionIdRef.current = id;
        setHermesSessionId(id);
      }
      if (next.commandId) {
        setBoundCommandId(next.commandId);
      }
      // Bump on every successful bind so post-deliver same-id reload works.
      setTranscriptEpoch((n) => n + 1);
    },
    [],
  );

  const bumpTranscript = useCallback(() => {
    setTranscriptEpoch((n) => n + 1);
  }, []);

  const value = useMemo(
    () => ({
      hermesSessionId,
      boundCommandId,
      setActiveHermesSession,
      transcriptEpoch,
      bumpTranscript,
    }),
    [
      hermesSessionId,
      boundCommandId,
      setActiveHermesSession,
      transcriptEpoch,
      bumpTranscript,
    ],
  );

  return (
    <ActiveHermesSessionContext.Provider value={value}>
      {children}
    </ActiveHermesSessionContext.Provider>
  );
}

export function useActiveHermesSession(): ActiveHermesSessionValue {
  const ctx = useContext(ActiveHermesSessionContext);
  if (!ctx) {
    throw new Error(
      "useActiveHermesSession requires ActiveHermesSessionProvider",
    );
  }
  return ctx;
}

/** Optional hook when the tree may render outside the provider (read-only shell). */
export function useOptionalActiveHermesSession(): ActiveHermesSessionValue | null {
  return useContext(ActiveHermesSessionContext);
}
