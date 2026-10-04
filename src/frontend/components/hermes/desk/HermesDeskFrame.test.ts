import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  path.join(process.cwd(), "components/hermes/desk/HermesDeskFrame.tsx"),
  "utf8",
);
const today = readFileSync(
  path.join(process.cwd(), "components/hermes/desk/HermesDeskToday.tsx"),
  "utf8",
);
const rail = readFileSync(
  path.join(process.cwd(), "components/hermes/desk/HermesDeskChatRail.tsx"),
  "utf8",
);
const css = readFileSync(
  path.join(process.cwd(), "components/hermes/desk/hermes-desk.css"),
  "utf8",
);

describe("Hermes desk responsive and tab contracts", () => {
  it("binds the mobile overlay selectors and exposes one explicit chat toggle", () => {
    expect(source).toContain('data-surface="hermes"');
    expect(source).toContain('aria-controls="hermes-chat-rail"');
    expect(source).toContain("aria-expanded={chatRailOpen}");
    expect(source).toContain("mobileDrawerOpen");
    expect(source).toContain("inert={mobileDrawerOpen ? true : undefined}");
    expect(source).toContain("aria-hidden={mobileDrawerOpen ? true : undefined}");
    expect(source).not.toContain("setAttribute(\"inert\"");
    expect(source).not.toContain("removeAttribute(\"inert\"");
    expect(source).toContain('closeButton?.focus()');
    expect(source).toContain('chatToggleRef.current?.focus()');
    expect(today).toContain("inert={mobileDrawerOpen ? true : undefined}");
    expect(rail).toContain('role={mobileDrawerOpen ? "dialog" : undefined}');
    expect(rail).toContain("aria-modal={mobileDrawerOpen ? true : undefined}");
    expect(rail).toContain('event.key === "Escape"');
    expect(rail).toContain('event.key !== "Tab"');
    expect(css).toContain('.dp[data-hermes-desk] .dp-rail[data-open="true"]');
    expect(css).toMatch(
      /max-width: 60rem[\s\S]*?\.dp\[data-hermes-desk\] \.dp-rail\[data-open="false"\][\s\S]*?translateX\(calc\(100% \+ 1px\)\)[\s\S]*?visibility: hidden/,
    );
    expect(css).toMatch(/max-width: 40rem[\s\S]*?width: 100%/);
    expect(css).toContain(".dp-rail-resizer");
    expect(css).toContain(".dp-agent-progress-track");
    expect(css).toContain("@keyframes dp-agent-progress");
    expect(css).toMatch(
      /max-width: 60rem[\s\S]*?\.dp-rail-resizer[\s\S]*?display: none/,
    );
    expect(css).toMatch(
      /prefers-reduced-motion: reduce[\s\S]*?\.dp-agent-progress-bar/,
    );
    expect(css).toMatch(
      /prefers-reduced-motion: reduce[\s\S]*?\.dp\[data-hermes-desk\] \.dp-rail[\s\S]*?transition: none/,
    );
  });

  it("keeps the mobile drawer below the top strip so its escape toggle stays reachable", () => {
    expect(css).toMatch(
      /max-width: 60rem[\s\S]*?\.dp\[data-hermes-desk\] \.dp-rail[\s\S]*?inset: var\(--dp-topstrip\)/,
    );
    expect(css).toMatch(
      /max-width: 60rem[\s\S]*?\.dp\[data-hermes-desk\] \.dp-topstrip[\s\S]*?z-index: 7/,
    );
    const header = source.match(/<header[\s\S]*?>/)![0];
    expect(header).not.toContain("inert");
    expect(header).not.toContain("aria-hidden");
    // The rail itself still gets the "one dialog open" treatment it owns.
    expect(rail).toContain('aria-modal={mobileDrawerOpen ? true : undefined}');
  });

  it("publishes real tabs, a labelled tabpanel and 44px targets", () => {
    expect(source).toContain('role="tab"');
    expect(source).toContain("aria-selected={ledger === item.id}");
    expect(source).toContain('aria-controls="hermes-ledger-panel"');
    expect(source).toContain('event.key === "ArrowRight"');
    expect(today).toContain('role="tabpanel"');
    expect(today).toContain('id="hermes-ledger-panel"');
    expect(css).toMatch(/\.dp-subnav[\s\S]*?min-height: 44px/);
    expect(css).toContain(".dp-subnav button::after");
    expect(css).toMatch(
      /\.dp-subnav button\[data-current="true"\]::after[\s\S]*?transform: scaleX\(1\)/,
    );
  });
});
