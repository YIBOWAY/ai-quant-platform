import { expect, type Page, type Request } from "@playwright/test";

const INTERACTIVE_SELECTOR = [
  "a[href]",
  "button",
  "input",
  "select",
  "textarea",
  "summary",
  '[role="button"]',
  '[role="link"]',
].join(", ");

function isLoopbackUrl(raw: string): boolean {
  try {
    const url = new URL(raw);
    return url.hostname === "127.0.0.1" || url.hostname === "localhost";
  } catch {
    // data:/blob:/about: etc. are not external network requests
    return (
      raw.startsWith("data:") ||
      raw.startsWith("blob:") ||
      raw.startsWith("about:") ||
      raw.startsWith("file:")
    );
  }
}

/**
 * Fail any browser request that leaves the loopback host.
 * Returns the shared array of blocked external URLs (expected empty).
 */
export async function installLoopbackOnlyGuard(page: Page): Promise<string[]> {
  const externalRequests: string[] = [];

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = request.url();
    if (!isLoopbackUrl(url)) {
      externalRequests.push(url);
      throw new Error(`Non-loopback browser request blocked: ${url}`);
    }
    await route.continue();
  });

  page.on("request", (request: Request) => {
    const url = request.url();
    if (!isLoopbackUrl(url) && !externalRequests.includes(url)) {
      externalRequests.push(url);
    }
  });

  return externalRequests;
}

async function visibleInteractiveElements(page: Page) {
  return page.locator(INTERACTIVE_SELECTOR).evaluateAll((nodes) =>
    nodes
      .map((node) => {
        const el = node as HTMLElement;
        // Ignore Next.js / tooling overlays that are not product chrome.
        const inDevOverlay = Boolean(
          el.closest("nextjs-portal") ||
            el.closest("[data-nextjs-toast]") ||
            el.closest("#__next-build-watcher") ||
            el.closest("[data-next-mark]") ||
            el.closest("[data-nextjs-dev-tools-button]"),
        );
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        const name =
          el.getAttribute("aria-label") ||
          el.textContent?.trim().slice(0, 80) ||
          el.getAttribute("href") ||
          "";
        const isNextDevTool =
          inDevOverlay ||
          /next\.js/i.test(name) ||
          /__next/i.test(el.id) ||
          /__next/i.test(el.className?.toString?.() ?? "");
        const hidden =
          isNextDevTool ||
          style.display === "none" ||
          style.visibility === "hidden" ||
          style.opacity === "0" ||
          rect.width === 0 ||
          rect.height === 0;
        return {
          tag: el.tagName.toLowerCase(),
          role: el.getAttribute("role"),
          name,
          disabled:
            (el as HTMLButtonElement).disabled === true ||
            el.getAttribute("aria-disabled") === "true",
          hidden,
          width: rect.width,
          height: rect.height,
        };
      })
      .filter((item) => !item.hidden),
  );
}

async function assertTargetsAtLeast44(page: Page, context: string) {
  const items = await visibleInteractiveElements(page);
  for (const item of items) {
    expect(
      item.width,
      `${context}: ${item.tag} "${item.name}" width ${item.width} < 44`,
    ).toBeGreaterThanOrEqual(44);
    expect(
      item.height,
      `${context}: ${item.tag} "${item.name}" height ${item.height} < 44`,
    ).toBeGreaterThanOrEqual(44);
  }
}

async function hasVisibleFocusRing(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) {
      return false;
    }
    const style = window.getComputedStyle(el);
    const outlineOk =
      style.outlineStyle !== "none" &&
      style.outlineWidth !== "0px" &&
      style.outlineColor !== "transparent" &&
      !style.outlineColor.includes("rgba(0, 0, 0, 0)");
    const shadowOk =
      style.boxShadow !== "none" &&
      style.boxShadow !== "" &&
      !style.boxShadow.includes("rgba(0, 0, 0, 0)");
    return outlineOk || shadowOk;
  });
}

async function walkFocusableWithTab(page: Page) {
  // Start from the document so Tab walks DOM order.
  await page.locator("body").click({ position: { x: 0, y: 0 }, force: true });
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
  });

  const maxStops = 80;
  const seen = new Set<string>();
  let stopped = 0;

  for (let i = 0; i < maxStops; i += 1) {
    await page.keyboard.press("Tab");
    const identity = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) {
        return null;
      }
      const inDevOverlay = Boolean(
        el.closest("nextjs-portal") ||
          el.closest("[data-nextjs-toast]") ||
          el.closest("#__next-build-watcher") ||
          el.tagName === "NEXTJS-PORTAL" ||
          /next\.js/i.test(el.getAttribute("aria-label") ?? "") ||
          /__next/i.test(el.id),
      );
      if (inDevOverlay) {
        return "dev-overlay-skip";
      }
      const disabled =
        (el as HTMLButtonElement).disabled === true ||
        el.getAttribute("aria-disabled") === "true" ||
        el.getAttribute("tabindex") === "-1";
      if (disabled) {
        return null;
      }
      return [
        el.tagName,
        el.id,
        el.getAttribute("aria-label") ?? "",
        el.getAttribute("href") ?? "",
        el.className?.toString?.() ?? "",
      ].join("|");
    });

    if (!identity || identity === "dev-overlay-skip") {
      continue;
    }
    if (seen.has(identity)) {
      // Cycled through focus order.
      break;
    }
    seen.add(identity);
    stopped += 1;

    const ring = await hasVisibleFocusRing(page);
    expect(ring, `focus-visible ring missing for ${identity}`).toBe(true);
  }

  expect(stopped, "expected at least one keyboard-focusable control").toBeGreaterThan(0);
}

/**
 * Full-page 44×44 target gate + Tab focus-visible walk across shell chrome
 * and Hermes content. At mobile widths, opens/closes mobile navigation.
 */
export async function assertFullPageTargetsAndFocus(page: Page) {
  const viewport = page.viewportSize();
  const width = viewport?.width ?? 1280;
  const isMobile = width < 1024;

  await assertTargetsAtLeast44(page, "initial shell");
  await walkFocusableWithTab(page);

  if (!isMobile) {
    return;
  }

  const menuButton = page.getByRole("button", {
    name: /Open navigation|打开导航/,
  });
  await expect(menuButton).toBeVisible();
  await menuButton.click();
  await expect(page.locator("#mobile-navigation")).toBeVisible();
  await assertTargetsAtLeast44(page, "mobile navigation open");
  await page.keyboard.press("Escape");
  await expect(page.locator("#mobile-navigation")).toHaveCount(0);
  await expect(menuButton).toBeFocused();
}

/**
 * Emulate prefers-reduced-motion and assert durations are effectively zero.
 */
export async function assertReducedMotion(page: Page) {
  await page.emulateMedia({ reducedMotion: "reduce" });

  const offenders = await page.evaluate(() => {
    const nodes = Array.from(document.querySelectorAll("body, body *"));
    const bad: string[] = [];
    for (const node of nodes) {
      const style = window.getComputedStyle(node);
      const parseDuration = (value: string) =>
        value
          .split(",")
          .map((part) => part.trim())
          .filter(Boolean)
          .map((part) => {
            if (part.endsWith("ms")) {
              return Number.parseFloat(part);
            }
            if (part.endsWith("s")) {
              return Number.parseFloat(part) * 1000;
            }
            return 0;
          });

      for (const ms of parseDuration(style.animationDuration)) {
        if (ms > 0.05) {
          bad.push(`animation ${ms}ms on ${node.tagName}`);
        }
      }
      for (const ms of parseDuration(style.transitionDuration)) {
        if (ms > 0.05) {
          bad.push(`transition ${ms}ms on ${node.tagName}`);
        }
      }
    }
    return bad.slice(0, 20);
  });

  expect(offenders, `non-zero motion under reduced-motion: ${offenders.join("; ")}`).toEqual(
    [],
  );
}

/**
 * Document and named page scroll regions must not overflow horizontally.
 */
export async function assertNoHorizontalOverflow(page: Page, viewportWidth: number) {
  const metrics = await page.evaluate(() => {
    const regions = Array.from(
      document.querySelectorAll<HTMLElement>("[data-page-scroll-region]"),
    ).map((node) => ({
      scrollWidth: node.scrollWidth,
      clientWidth: node.clientWidth,
    }));
    return {
      documentScrollWidth: document.documentElement.scrollWidth,
      regions,
    };
  });

  expect(
    metrics.documentScrollWidth,
    `document scrollWidth ${metrics.documentScrollWidth} > viewport ${viewportWidth}`,
  ).toBeLessThanOrEqual(viewportWidth);

  for (const region of metrics.regions) {
    expect(
      region.scrollWidth,
      `scroll region scrollWidth ${region.scrollWidth} > clientWidth ${region.clientWidth}`,
    ).toBeLessThanOrEqual(region.clientWidth + 1);
  }
}

/**
 * Opening/closing an already-visible result <details> must not hijack page scroll.
 * Prefers a currently closed details (page technical feed) over pre-expanded
 * exception rows so the gate measures toggle stability, not collapse of large
 * open blocks. Scrolls that target into the named app scroll region first, then
 * toggles open/closed and asserts scrollTop is stable.
 */
export async function assertTechnicalDetailDoesNotHijackScroll(page: Page) {
  const prepared = await page.evaluate(() => {
    const candidates = Array.from(document.querySelectorAll("details")).filter((node) => {
      const style = window.getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return (
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        rect.width > 0 &&
        rect.height > 0 &&
        Boolean(node.querySelector("summary"))
      );
    });
    if (candidates.length === 0) {
      return null;
    }
    // Prefer closed technical rows; fall back to the first layout-visible details.
    const details =
      candidates.find((node) => !(node as HTMLDetailsElement).open) ?? candidates[0];
    const index = candidates.indexOf(details);
    const scrollRegion =
      details.closest<HTMLElement>("[data-page-scroll-region]") ??
      document.documentElement;
    details.scrollIntoView({ block: "center", inline: "nearest" });
    return {
      index,
      open: (details as HTMLDetailsElement).open,
      scrollTop: scrollRegion.scrollTop,
      hasRegion: Boolean(details.closest("[data-page-scroll-region]")),
    };
  });

  expect(prepared, "expected a visible <details> element for scroll gate").not.toBeNull();
  if (!prepared) {
    return;
  }

  const detailsLocator = page
    .locator("details")
    .filter({ has: page.locator("summary") })
    .nth(prepared.index);
  await expect(detailsLocator).toBeVisible();

  const summary = detailsLocator.locator("summary").first();
  const beforeScroll = await page.evaluate((index) => {
    const candidates = Array.from(document.querySelectorAll("details")).filter((node) => {
      const style = window.getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return (
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        rect.width > 0 &&
        rect.height > 0 &&
        Boolean(node.querySelector("summary"))
      );
    });
    const details = candidates[index] as HTMLDetailsElement | undefined;
    if (!details) {
      return null;
    }
    const scrollRegion =
      details.closest<HTMLElement>("[data-page-scroll-region]") ??
      document.documentElement;
    return { open: details.open, scrollTop: scrollRegion.scrollTop };
  }, prepared.index);
  expect(beforeScroll).not.toBeNull();
  if (!beforeScroll) {
    return;
  }

  await summary.click();
  await summary.click();

  const after = await page.evaluate((index) => {
    const candidates = Array.from(document.querySelectorAll("details")).filter((node) => {
      const style = window.getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return (
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        rect.width > 0 &&
        rect.height > 0 &&
        Boolean(node.querySelector("summary"))
      );
    });
    const details = candidates[index] as HTMLDetailsElement | undefined;
    if (!details) {
      return null;
    }
    const scrollRegion =
      details.closest<HTMLElement>("[data-page-scroll-region]") ??
      document.documentElement;
    return {
      open: details.open,
      scrollTop: scrollRegion.scrollTop,
    };
  }, prepared.index);

  expect(after).not.toBeNull();
  if (!after) {
    return;
  }

  expect(Math.abs(after.scrollTop - beforeScroll.scrollTop)).toBeLessThanOrEqual(1);

  // Restore original open state if toggle left it flipped.
  if (after.open !== beforeScroll.open) {
    await summary.click();
  }
}
