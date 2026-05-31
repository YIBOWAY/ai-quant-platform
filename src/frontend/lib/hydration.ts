'use client';

import { useSyncExternalStore } from "react";

const emptySubscribe = () => () => undefined;

export function useIsHydrated() {
  return useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false,
  );
}
