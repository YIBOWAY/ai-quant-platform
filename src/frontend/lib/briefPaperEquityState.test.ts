import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  PaperEquityFigureState,
  resolvePaperEquityAvailability,
} from "@/components/brief/PaperEquityFigureState";

describe("brief paper-equity figure truth state", () => {
  it("replaces fallback chart facts when either paper source is unavailable", () => {
    const html = renderToStaticMarkup(
      createElement(
        PaperEquityFigureState,
        {
          unavailableReason: "503: equity curve unavailable",
          unavailableLabel: "Paper account equity data unavailable.",
        },
        createElement(
          "div",
          null,
          "default · $1,000,000.00 · 24 points · ▲ 0.00%",
        ),
      ),
    );

    expect(html).toContain("data-brief-paper-equity-unavailable");
    expect(html).toContain("Paper account equity data unavailable.");
    expect(html).toContain("503: equity curve unavailable");
    expect(html).not.toContain("$1,000,000.00");
    expect(html).not.toContain("24 points");
    expect(html).not.toContain("▲ 0.00%");
  });

  it("keeps factual chart content when both paper sources are available", () => {
    const html = renderToStaticMarkup(
      createElement(
        PaperEquityFigureState,
        { unavailableReason: null, unavailableLabel: "unavailable" },
        createElement("div", { "data-factual-chart": true }, "factual curve"),
      ),
    );

    expect(html).toContain("data-factual-chart");
    expect(html).not.toContain("data-brief-paper-equity-unavailable");
  });

  it("blocks factual archive persistence when only the equity-curve API fails", () => {
    expect(
      resolvePaperEquityAvailability({
        accountApiError: undefined,
        curveApiError: "503: equity curve unavailable",
        accountBlockedLabel: "Paper account unavailable.",
        curveBlockedLabel: "Paper equity curve unavailable; archive is blocked.",
      }),
    ).toEqual({
      unavailableReason: "503: equity curve unavailable",
      blockedReason: "Paper equity curve unavailable; archive is blocked.",
    });
  });
});
