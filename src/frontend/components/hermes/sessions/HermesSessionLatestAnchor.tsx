"use client";

import { useEffect, useRef } from "react";

/** Keep a newly opened persisted transcript focused on its latest message. */
export function HermesSessionLatestAnchor() {
  const anchorRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    anchorRef.current?.scrollIntoView({ block: "end" });
  }, []);

  return (
    <span
      aria-hidden="true"
      className="block h-px scroll-mb-3"
      data-hermes-session-latest-anchor
      ref={anchorRef}
    />
  );
}
