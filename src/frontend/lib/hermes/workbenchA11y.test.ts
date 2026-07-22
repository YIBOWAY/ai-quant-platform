import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  COLLAPSE_TOGGLE_CLASS,
  displayId,
  LONG_ID_CLASS,
  WORKBENCH_A11Y_BREAKPOINTS,
  WORKBENCH_A11Y_MARKER,
  WORKBENCH_CONTENT_PAD_CLASS,
} from "./workbenchA11y";

describe("workbenchA11y (L5c)", () => {
  it("pins the observe-only a11y marker", () => {
    expect(WORKBENCH_A11Y_MARKER).toBe("l5c-m1");
  });

  it("lists Architect breakpoints 1440/1280/768/390", () => {
    expect(WORKBENCH_A11Y_BREAKPOINTS.map((b) => b.width)).toEqual([
      1440, 1280, 768, 390,
    ]);
  });

  it("displayId middle-ellipsizes long ids and keeps short ones", () => {
    expect(displayId("short")).toBe("short");
    expect(displayId("cmd-abcdefghijklmnopqrstuvwxyz0123456789")).toBe(
      "cmd-abcdef…456789",
    );
    expect(displayId(null)).toBe("");
    expect(displayId("  ")).toBe("");
    expect(
      displayId("sess-abcdefghijklmnopqrstuvwxyz0123456789", {
        head: 20,
        tail: 8,
        max: 36,
      }),
    ).toBe("sess-abcdefghijklmno…23456789");
  });

  it("exports layout classes that prevent long-id overflow traps", () => {
    expect(LONG_ID_CLASS).toContain("break-all");
    expect(LONG_ID_CLASS).toContain("min-w-0");
    expect(COLLAPSE_TOGGLE_CLASS).toContain("app-touch-target");
    expect(COLLAPSE_TOGGLE_CLASS).toContain("focus-visible:outline");
    expect(WORKBENCH_CONTENT_PAD_CLASS).toContain("p-3");
    expect(WORKBENCH_CONTENT_PAD_CLASS).toContain("sm:p-4");
    expect(WORKBENCH_CONTENT_PAD_CLASS).toContain("lg:p-6");
  });

  it("globals keep focus-visible ring + reduced-motion + 44px targets", () => {
    const cssPath = path.join(process.cwd(), "app/globals.css");
    const css = readFileSync(cssPath, "utf8");
    expect(css).toContain(".app-touch-target");
    expect(css).toContain("min-width: 44px");
    expect(css).toContain("min-height: 44px");
    expect(css).toContain(":focus-visible");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    expect(css).toContain("animation-duration: 0.01ms !important");
    expect(css).toContain("transition-duration: 0.01ms !important");
  });

  it("local-chat boundary mounts workbench region landmark (no nested main)", () => {
    const src = readFileSync(
      path.join(
        process.cwd(),
        "components/hermes/shell/HermesLocalChatBoundary.tsx",
      ),
      "utf8",
    );
    expect(src).toContain("data-hermes-workbench-a11y={WORKBENCH_A11Y_MARKER}");
    expect(src).toContain("WORKBENCH_CONTENT_PAD_CLASS");
    expect(src).toContain("data-hermes-workbench-main");
    expect(src).toContain('role="region"');
    expect(src).toContain('aria-label={isZh ? "Hermes 工作台主区"');
    // Root layout already owns document <main>; workbench must not nest another JSX main.
    expect(src).not.toMatch(/<\s*main[\s>]/);
    // No new mutation surfaces in the a11y slice.
    expect(src).not.toMatch(/allow\/deny|decideApproval|stop_command/i);
  });

  it("shell root carries a11y marker for open+closed chat; region not nested main", () => {
    const src = readFileSync(
      path.join(
        process.cwd(),
        "components/hermes/shell/HermesWorkbenchShell.tsx",
      ),
      "utf8",
    );
    expect(src).toContain("data-hermes-workbench-a11y={WORKBENCH_A11Y_MARKER}");
    expect(src).toContain("data-hermes-workbench-main");
    expect(src).toContain("WORKBENCH_CONTENT_PAD_CLASS");
    expect(src).toContain('role="region"');
    expect(src).not.toMatch(/<main[\s>]/);
  });

  it("activity/approvals/authority panels share collapse + long-id contracts", () => {
    for (const rel of [
      "components/hermes/activity/WorkbenchCommandActivityPanel.tsx",
      "components/hermes/approvals/WorkbenchCommandApprovalsPanel.tsx",
      "components/hermes/authority/WorkbenchAuthorityProjectionPanel.tsx",
    ]) {
      const src = readFileSync(path.join(process.cwd(), rel), "utf8");
      expect(src).toContain("COLLAPSE_TOGGLE_CLASS");
      expect(src).toContain("LONG_ID_CLASS");
      expect(src).toContain("displayId");
      expect(src).not.toMatch(/\bshortId\b/);
      // No decision/stop mutation handlers (copy may still say "no allow/deny").
      expect(src).not.toMatch(/\bdecideApproval\b|\bstop_command\b|\bonAllow\b|\bonDeny\b/);
    }
  });

  it("composer and transcript copy chip keep focus-visible + 44px targets", () => {
    const composer = readFileSync(
      path.join(process.cwd(), "components/hermes/ComposerDock.tsx"),
      "utf8",
    );
    expect(composer).toContain("app-touch-target");
    expect(composer).toContain("focus-visible:outline");
    expect(composer).toContain("aria-label={label}");
    expect(composer).toContain("aria-label={sendLabel}");
    expect(composer).toContain('role="status"');

    const canvas = readFileSync(
      path.join(
        process.cwd(),
        "components/hermes/transcript/TranscriptCanvas.tsx",
      ),
      "utf8",
    );
    expect(canvas).toContain("COLLAPSE_TOGGLE_CLASS");
    expect(canvas).toContain("displayId");
    expect(canvas).toContain("break-all");
  });
});
