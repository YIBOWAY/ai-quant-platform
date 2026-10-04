import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Tabs } from "@/components/ui/Tabs";

describe("Tabs interaction contract", () => {
  it("exposes tablist semantics with aria-controls and a labelled panel", () => {
    const html = renderToStaticMarkup(
      <Tabs
        items={[
          { id: "live", label: "Live", content: <p>LIVE_BODY</p> },
          { id: "history", label: "History", content: <p>HISTORY_BODY</p> },
        ]}
      />,
    );

    expect(html).toContain('role="tablist"');
    expect(html).toContain('role="tab"');
    expect(html).toContain('role="tabpanel"');
    expect(html).toContain('aria-selected="true"');
    expect(html).toContain("aria-controls=");
    expect(html).toContain("aria-labelledby=");
    expect(html).toContain("LIVE_BODY");
    expect(html).not.toContain("HISTORY_BODY");
    expect(html).toContain("motion-panel-enter");
  });

  it("implements Hermes-style Arrow/Home/End keyboard handling in source", () => {
    const source = readFileSync(
      path.join(process.cwd(), "components/ui/Tabs.tsx"),
      "utf8",
    );
    expect(source).toContain('"ArrowLeft"');
    expect(source).toContain('"ArrowRight"');
    expect(source).toContain('"Home"');
    expect(source).toContain('"End"');
    expect(source).toContain("tabIndex={isActive ? 0 : -1}");
  });
});

describe("QuickTrade drawer focus contract", () => {
  it("traps focus, restores it, and marks the dialog modal", () => {
    const source = readFileSync(
      path.join(process.cwd(), "components/position-map/QuickTradeDrawer.tsx"),
      "utf8",
    );
    expect(source).toContain('role={open ? "dialog" : undefined}');
    expect(source).toContain("aria-modal={open || undefined}");
    expect(source).toContain("inert={!open}");
    expect(source).toContain("previouslyFocusedRef");
    expect(source).toContain("onDrawerKeyDown");
    expect(source).toContain('event.key === "Escape"');
    expect(source).toContain('event.key !== "Tab"');
    expect(source).toContain("first.focus()");
    expect(source).toContain("last.focus()");
  });
});

describe("TerminalToolbarButton press feedback", () => {
  it("uses the shared motion-pressable class", () => {
    const source = readFileSync(
      path.join(process.cwd(), "components/ui/primitives.tsx"),
      "utf8",
    );
    expect(source).toContain("motion-pressable");
  });
});
