import { expect, type Page } from "@playwright/test";

export type DockPanelId =
  | "approvals"
  | "activity"
  | "runs"
  | "results"
  | "gates"
  | "authority";

/**
 * Workbench panels live in on-demand dock drawers, so any assertion about their
 * rows must open the owning drawer first. Idempotent: clicking an already-open
 * panel would close it, so this only clicks when the drawer is not showing.
 */
export async function openDock(page: Page, panel: DockPanelId): Promise<void> {
  const button = page.locator(`[data-hermes-dock-rail-button="${panel}"]`);
  await expect(button).toBeVisible();
  if ((await button.getAttribute("aria-pressed")) !== "true") {
    await button.click();
  }
  await expect(page.locator("[data-hermes-dock-drawer]")).toBeVisible();
  await expect(button).toHaveAttribute("aria-pressed", "true");
}

/** Close the dock drawer if one is open (scrim/Escape both work; use Escape). */
export async function closeDock(page: Page): Promise<void> {
  const drawer = page.locator("[data-hermes-dock-drawer]");
  if ((await drawer.count()) > 0) {
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
  }
}
