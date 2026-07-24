import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { resolvePaperAccountAvailableCash } from "@/lib/paperAccountState";

// The panel is a heavy client component (react-query mutations + hydration
// gate) whose cash metric only renders after hydration, so SSR markup is not a
// reliable oracle. The fail-closed branch itself is fully covered by the
// resolver unit tests below; the panel/page wiring is pinned by source checks
// (the same approach as lib/optionsProvenance.test.ts).

describe("paper account available-cash fail-closed (V1.6c)", () => {
  it("returns null when the account envelope carries an apiError", () => {
    // The $1M FALLBACK_ACCOUNT is tagged with apiError when the API is down.
    expect(
      resolvePaperAccountAvailableCash({
        apiError: "503: paper account unavailable",
        available_cash: 1_000_000,
      }),
    ).toBeNull();
  });

  it("returns the real number when there is no apiError", () => {
    expect(
      resolvePaperAccountAvailableCash({ available_cash: 250_000 }),
    ).toBe(250_000);
  });

  it("returns null for a missing account or non-finite cash", () => {
    expect(resolvePaperAccountAvailableCash(null)).toBeNull();
    expect(resolvePaperAccountAvailableCash(undefined)).toBeNull();
    expect(
      resolvePaperAccountAvailableCash({ available_cash: Number.NaN }),
    ).toBeNull();
  });

  it("panel treats null available-cash exactly like accountDown (fail-closed)", () => {
    const src = readFileSync(
      path.join(
        process.cwd(),
        "components/forms/PaperStrategySleevesPanel.tsx",
      ),
      "utf8",
    );
    // Null cash folds into a single cashUnavailable flag...
    expect(src).toContain("accountAvailableCash: number | null");
    expect(src).toContain("accountDown || accountAvailableCash === null");
    // ...which gates the cash metric to "--" and blocks cash-mode creation.
    expect(src).toContain('cashUnavailable ? "--" : formatMoney(accountAvailableCash)');
    expect(src).toContain("!cashUnavailable && allocatedCash > 0");
  });

  it("paper-trading page wires the fail-closed resolver into the panel", () => {
    const src = readFileSync(
      path.join(process.cwd(), "app/paper-trading/page.tsx"),
      "utf8",
    );
    expect(src).toContain('from "@/lib/paperAccountState"');
    expect(src).toContain(
      "accountAvailableCash={resolvePaperAccountAvailableCash(account)}",
    );
    // The panel no longer receives the raw (possibly-fallback) cash figure.
    expect(src).not.toContain("accountAvailableCash={account.available_cash}");
  });
});
