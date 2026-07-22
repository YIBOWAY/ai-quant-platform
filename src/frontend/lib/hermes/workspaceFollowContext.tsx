/**
 * React binding for L4b workspace follow spine.
 * Mount once under ActiveHermesSessionProvider so Activity + bind share one transport.
 */

'use client';

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useActiveHermesSession } from "@/lib/hermes/activeSession";
import { isTerminalCommandState } from "@/lib/hermes/workspaceClient";
import {
  createWorkspaceFollowSpine,
  EMPTY_AUTHORITY_HEALTH,
  type FollowSpineState,
  type WorkspaceFollowSpine,
} from "@/lib/hermes/workspaceFollowSpine";
import { isUsableHermesApiSessionId } from "@/lib/hermes/transcriptHelpers";

export type WorkspaceFollowContextValue = {
  state: FollowSpineState;
  spine: WorkspaceFollowSpine | null;
};

const WorkspaceFollowContext = createContext<WorkspaceFollowContextValue | null>(
  null,
);

export function WorkspaceFollowProvider({
  children,
  enabled = true,
}: {
  children: ReactNode;
  /** When false, spine stays idle (chat closed). */
  enabled?: boolean;
}) {
  const { setActiveHermesSession, bumpTranscript } = useActiveHermesSession();
  const [state, setState] = useState<FollowSpineState>(() => ({
    cursor: 0,
    commands: [],
    approvals: [],
    gates: [],
    tasks: [],
    attempts: [],
    runs: [],
    results: [],
    authorityHealth: { ...EMPTY_AUTHORITY_HEALTH },
    mutationEnabled: false,
    lastEvents: [],
    transport: "idle",
    resyncCount: 0,
    error: null,
  }));
  const spineRef = useRef<WorkspaceFollowSpine | null>(null);
  const seenTerminalRef = useRef<Set<string>>(new Set());

  const spine = useMemo(() => {
    if (typeof window === "undefined") return null;
    return createWorkspaceFollowSpine({
      preferSse: true,
      pollMs: 2_000,
      snapshotReconcileMs: 30_000,
    });
  }, []);

  useEffect(() => {
    spineRef.current = spine;
    if (!spine) return;
    const unsub = spine.subscribe(setState);
    return () => {
      unsub();
    };
  }, [spine]);

  useEffect(() => {
    if (!spine) return;
    if (enabled) {
      spine.start();
    } else {
      spine.stop();
    }
    return () => {
      spine.stop();
    };
  }, [spine, enabled]);

  // Bind / bump transcript only after a replay-backed terminal command fact.
  useEffect(() => {
    for (const event of state.lastEvents) {
      if (!event.command_id) continue;
      const terminal = isTerminalCommandState(event.state);
      if (!terminal) continue;
      const key = `${event.command_id}:${event.state}:${event.event_id ?? ""}`;
      if (seenTerminalRef.current.has(key)) continue;
      seenTerminalRef.current.add(key);
      if (
        event.state === "succeeded" &&
        isUsableHermesApiSessionId(event.hermes_session_id)
      ) {
        setActiveHermesSession({
          hermesSessionId: event.hermes_session_id,
          commandId: event.command_id,
        });
      } else if (event.state === "succeeded") {
        bumpTranscript();
      }
    }
  }, [state.lastEvents, setActiveHermesSession, bumpTranscript]);

  const value = useMemo(
    () => ({
      state,
      spine,
    }),
    [state, spine],
  );

  return (
    <WorkspaceFollowContext.Provider value={value}>
      {children}
    </WorkspaceFollowContext.Provider>
  );
}

export function useWorkspaceFollow(): WorkspaceFollowContextValue {
  const ctx = useContext(WorkspaceFollowContext);
  if (!ctx) {
    return {
      state: {
        cursor: 0,
        commands: [],
        approvals: [],
        gates: [],
        tasks: [],
        attempts: [],
        runs: [],
        results: [],
        authorityHealth: {},
        mutationEnabled: false,
        lastEvents: [],
        transport: "idle",
        resyncCount: 0,
        error: null,
      },
      spine: null,
    };
  }
  return ctx;
}
