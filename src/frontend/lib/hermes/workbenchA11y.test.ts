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
  workbenchContentPadClass,
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

  it("adds composer clearance only where a composer renders", () => {
    // The clearance tracks --spacing-hermes-composer-min, so applying it on a
    // route with no composer leaves that much dead space at the bottom.
    expect(WORKBENCH_CONTENT_PAD_CLASS).not.toContain("pb-[calc(");
    expect(workbenchContentPadClass(false)).toBe(WORKBENCH_CONTENT_PAD_CLASS);
    expect(workbenchContentPadClass(true)).toContain(
      "pb-[calc(var(--spacing-hermes-composer-min)+2rem)]",
    );
    expect(workbenchContentPadClass(true)).toContain(
      "lg:pb-[calc(var(--spacing-hermes-composer-min)+3rem)]",
    );
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
    expect(src).toContain("workbenchContentPadClass");
    expect(src).toContain("data-hermes-workbench-main");
    expect(src).toContain('role="region"');
    expect(src).toContain('aria-label={isZh ? "Hermes 工作台主区"');
    // Root layout already owns document <main>; workbench must not nest another JSX main.
    expect(src).not.toMatch(/<\s*main[\s>]/);
    // Boundary stays free of decide/stop wiring (V7a lives in Approvals panel).
    expect(src).not.toMatch(/decideHermesCommandApproval|stop_command/i);
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
    expect(src).toContain("workbenchContentPadClass");
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
      // Stop stays out of these panels. Activity/Authority never decide.
      expect(src).not.toMatch(/\bstop_command\b/);
    }
    const activity = readFileSync(
      path.join(process.cwd(), "components/hermes/activity/WorkbenchCommandActivityPanel.tsx"),
      "utf8",
    );
    const authority = readFileSync(
      path.join(
        process.cwd(),
        "components/hermes/authority/WorkbenchAuthorityProjectionPanel.tsx",
      ),
      "utf8",
    );
    expect(activity).not.toMatch(
      /\bdecideHermesCommandApproval\b|\bdata-hermes-approval-allow-once\b/,
    );
    expect(authority).not.toMatch(
      /\bdecideHermesCommandApproval\b|\bdata-hermes-approval-allow-once\b/,
    );
    // V7a: Approvals panel owns allow_once|deny only (marker present).
    const approvals = readFileSync(
      path.join(
        process.cwd(),
        "components/hermes/approvals/WorkbenchCommandApprovalsPanel.tsx",
      ),
      "utf8",
    );
    expect(approvals).toContain('data-hermes-approval-decide="v7a-m1"');
    expect(approvals).toContain("decideHermesCommandApproval");
    // Ban real always-allow decision wiring (not "no always-allow" copy).
    expect(approvals).not.toMatch(/["']allow_permanently["']/i);
    expect(approvals).not.toMatch(/["']allow_always["']/i);
    expect(approvals).not.toMatch(/decision:\s*["']always/i);
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
    expect(composer).toContain("aria-label={newSessionLabel}");
    expect(composer).toContain("onStartNewSession");
    expect(composer).toContain("MessageSquarePlus");
    expect(composer).toContain("newSessionButtonRef.current?.focus()");
    expect(composer).toContain("rounded-md bg-bg-base");
    expect(composer).toContain('aria-atomic="true"');
    expect(composer).toContain('role="status"');
    expect(composer).toContain('data-testid="hermes-composer-byte-count"');
    expect(composer).toContain(
      'aria-describedby="hermes-composer-byte-count hermes-composer-status"',
    );
    expect(composer).toContain("draftState.valid");
    expect(composer).toContain("draftResetToken");

    const controller = readFileSync(
      path.join(
        process.cwd(),
        "components/hermes/ComposerSubmitController.tsx",
      ),
      "utf8",
    );
    expect(controller).toContain("managedSessionIsReadyForHermesSession");
    expect(controller).toContain('"read_only"');
    expect(controller).toContain("sessionCanSubmit");
    expect(controller).toContain(
      'const sessionCanSubmit = assessedState === "writable"',
    );
    expect(controller).toContain("focusComposerWhenWritableRef");
    expect(controller).toContain('assessedState === "empty"');
    expect(controller).toContain("freshManagedSessionErrorCopy");
    expect(controller).toContain("setAcceptedDraftToken");

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
