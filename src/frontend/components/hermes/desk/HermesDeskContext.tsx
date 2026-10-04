"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { HermesDeliveryState } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";
import type { DeskLedger } from "./HermesDeskToday";

type DeskContextValue = {
  ledger: DeskLedger;
  setLedger: (ledger: DeskLedger) => void;
  chatOpen: boolean;
  chatRailOpen: boolean;
  setChatRailOpen: (open: boolean) => void;
  isMobile: boolean;
  locale: Locale;
  deliveryState: HermesDeliveryState;
};

const DeskContext = createContext<DeskContextValue | null>(null);

export function HermesDeskProvider({
  children,
  chatOpen = false,
  locale = "zh",
  deliveryState = "blocked_in_this_slice",
}: {
  children: ReactNode;
  chatOpen?: boolean;
  locale?: Locale;
  deliveryState?: HermesDeliveryState;
}) {
  const [ledger, setLedger] = useState<DeskLedger>("duty");
  const [chatRailOpen, setChatRailOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 60rem)");
    const sync = () => setIsMobile(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);
  return (
    <DeskContext.Provider
      value={{
        ledger,
        setLedger,
        chatOpen,
        chatRailOpen,
        setChatRailOpen,
        isMobile,
        locale,
        deliveryState,
      }}
    >
      {children}
    </DeskContext.Provider>
  );
}

export function useHermesDesk(): DeskContextValue {
  const value = useContext(DeskContext);
  const fallback = useState<DeskLedger>("duty");
  if (value) return value;
  return {
    ledger: fallback[0],
    setLedger: fallback[1],
    chatOpen: false,
    chatRailOpen: false,
    setChatRailOpen: () => undefined,
    isMobile: false,
    locale: "zh",
    deliveryState: "blocked_in_this_slice",
  };
}
