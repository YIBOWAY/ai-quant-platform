'use client';

import { createContext, useContext, type ReactNode } from "react";

/**
 * True while fullscreen chat has replaced the Today landing content.
 *
 * Today's page tree stays mounted (hidden) under fullscreen chat so the
 * deep-link binder keeps working, which means two nodes would otherwise claim
 * the `hermes-today-state` test id. Playwright's `getByTestId` is strict and
 * throws on two matches even when one is hidden, so the hidden Today section
 * yields the id to the chat boundary's own state node while chat is active.
 */
const HermesChatActiveContext = createContext(false);

export function HermesChatActiveProvider({
  active,
  children,
}: {
  active: boolean;
  children: ReactNode;
}) {
  return (
    <HermesChatActiveContext.Provider value={active}>
      {children}
    </HermesChatActiveContext.Provider>
  );
}

export function useHermesChatActive(): boolean {
  return useContext(HermesChatActiveContext);
}
