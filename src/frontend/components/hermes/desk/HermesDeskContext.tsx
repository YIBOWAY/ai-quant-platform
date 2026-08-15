"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import type { DeskLedger } from "./HermesDeskToday";

type DeskContextValue = {
  ledger: DeskLedger;
  setLedger: (ledger: DeskLedger) => void;
};

const DeskContext = createContext<DeskContextValue | null>(null);

export function HermesDeskProvider({ children }: { children: ReactNode }) {
  const [ledger, setLedger] = useState<DeskLedger>("duty");
  return (
    <DeskContext.Provider value={{ ledger, setLedger }}>{children}</DeskContext.Provider>
  );
}

export function useHermesDesk(): DeskContextValue {
  const value = useContext(DeskContext);
  const fallback = useState<DeskLedger>("duty");
  if (value) return value;
  return { ledger: fallback[0], setLedger: fallback[1] };
}
