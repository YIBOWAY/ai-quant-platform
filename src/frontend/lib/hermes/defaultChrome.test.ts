import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { HERMES_DEFAULT_LEDGERS, HERMES_DEFAULT_PRODUCT_TABS } from "./defaultChrome";

const frameSource = readFileSync(
  path.join(process.cwd(), "components/hermes/desk/HermesDeskFrame.tsx"),
  "utf8",
);

describe("Hermes default chrome", () => {
  it("keeps the three ledgers and no operator product tabs", () => {
    expect(HERMES_DEFAULT_LEDGERS.map((item) => item.label)).toEqual([
      "今日",
      "研究",
      "模拟",
    ]);
    expect([...HERMES_DEFAULT_PRODUCT_TABS]).toEqual([]);
  });

  it("ships the desk frame from that chrome, not 会话/任务/审批", () => {
    expect(frameSource).toContain("HERMES_DEFAULT_LEDGERS");
    expect(frameSource).not.toContain("copy.nav.sessions");
    expect(frameSource).not.toContain("copy.nav.tasks");
    expect(frameSource).not.toContain("copy.nav.approvals");
    expect(frameSource).not.toContain('hermesRouteHref("sessions"');
    expect(frameSource).not.toContain('hermesRouteHref("tasks"');
    expect(frameSource).not.toContain('hermesRouteHref("approvals"');
  });
});
