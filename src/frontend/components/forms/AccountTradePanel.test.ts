import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  path.join(process.cwd(), "components/forms/AccountTradePanel.tsx"),
  "utf8",
);

describe("AccountTradePanel browser state", () => {
  it("applies the returned freeze state before refreshing server data", () => {
    expect(source).toContain("freezeOverride?.source === killSwitch");
    expect(source).toContain(
      "setFreezeOverride({ source: killSwitch, value: payload.kill_switch })",
    );
    expect(source).toContain("freezeMutation.mutate(!accountFrozen)");
    expect(source).toContain("disabled={!isHydrated || accountFrozen");
  });

  it("does not expose the backend pending-order reason in a toast", () => {
    expect(source).toContain("toast.warning(text.orderPending())");
    expect(source).not.toContain(
      'toast.warning(text.orderPending(payload.order.rejected_reason ?? ""))',
    );
  });
});
