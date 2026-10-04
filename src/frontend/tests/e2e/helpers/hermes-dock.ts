import { expect, type Page } from "@playwright/test";

export type DockPanelId =
  | "approvals"
  | "activity"
  | "runs"
  | "results"
  | "authority";

/**
 * The current desk uses inline, explicitly opened Run details. Keep tests on
 * the user interaction, not the removed modal rail or direct DOM open toggles.
 */
export async function openDock(page: Page, panel: DockPanelId): Promise<void> {
  const details = page.locator(`[data-hermes-run-panel="${panel}"]`);
  if (!(await details.getAttribute("open"))) {
    const isOpen = await details.evaluate(node => (node as HTMLDetailsElement).open);
    if (!isOpen) await details.locator(":scope > summary").click();
  }
  await expect(details).toHaveAttribute("open", "");
}

/** Close the dock drawer if one is open (scrim/Escape both work; use Escape). */
export async function closeDock(page: Page): Promise<void> {
  const panels = page.locator("[data-hermes-run-panel][open]");
  while ((await panels.count()) > 0) {
    await panels.first().locator(":scope > summary").click();
  }
}
