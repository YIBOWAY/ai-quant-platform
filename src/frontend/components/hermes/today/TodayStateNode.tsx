'use client';

import { useHermesChatActive } from "@/lib/hermes/chatActiveContext";

/**
 * Screen-reader state line for the Today overview, and the single owner of the
 * `hermes-today-state` test id while Today is the visible surface.
 *
 * Under fullscreen chat the Today tree stays mounted but hidden, so this node
 * steps aside and the chat boundary's own state node reports `active`. That
 * keeps exactly one match for Playwright's strict `getByTestId`.
 */
export function TodayStateNode({ state, label }: { state: string; label: string }) {
  const chatActive = useHermesChatActive();
  if (chatActive) return null;

  return (
    <p className="sr-only" data-state={state} data-testid="hermes-today-state">
      {label}
    </p>
  );
}
