'use client';

import { useState } from "react";
import { EmptyState } from "@/components/EmptyState";

const TABS = ["Overview", "Agent summary"] as const;

export function ExperimentTabs() {
  const [active, setActive] = useState<(typeof TABS)[number]>("Overview");

  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-4">
      <div className="mb-4 flex gap-2">
        {TABS.map((tab) => (
          <button
            key={tab}
            className={`rounded border px-3 py-2 font-body-sm ${
              active === tab
                ? "border-primary bg-primary/10 text-primary"
                : "border-border-subtle text-text-secondary"
            }`}
            onClick={() => setActive(tab)}
            type="button"
          >
            {tab}
          </button>
        ))}
      </div>
      <EmptyState
        title={`${active} not selected`}
        description="Experiment detail payloads are displayed here after a concrete experiment is opened."
      />
    </div>
  );
}
