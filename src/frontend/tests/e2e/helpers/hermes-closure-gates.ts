import { expect, type Page } from "@playwright/test";

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

const SHELL_SELECTOR = "[data-hermes-workbench-a11y]";

/**
 * WCAG 2.1 AA text contrast for every visible text node in the Hermes shell.
 * Normal text requires 4.5:1; large text (24px, or 18.67px bold) requires 3:1.
 * The only contrast exemption is a semantically disabled control.
 */
export async function assertWholeHermesShellWcagAaContrast(page: Page) {
  const offenders = await page.locator(SHELL_SELECTOR).evaluate((root) => {
    type Rgba = [number, number, number, number];

    const parseColor = (raw: string): Rgba | null => {
      if (raw === "transparent") return [0, 0, 0, 0];
      if (!raw.startsWith("rgb")) return null;
      const values = raw.match(/[\d.]+/g)?.map(Number) ?? [];
      if (values.length < 3) return null;
      return [
        values[0],
        values[1],
        values[2],
        values.length >= 4 ? values[3] : 1,
      ];
    };
    const clampAlpha = (value: number) =>
      Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 1;
    const composite = (front: Rgba, back: Rgba): Rgba => {
      const alpha = front[3] + back[3] * (1 - front[3]);
      if (alpha <= 0) return [0, 0, 0, 0];
      return [
        (front[0] * front[3] +
          back[0] * back[3] * (1 - front[3])) /
          alpha,
        (front[1] * front[3] +
          back[1] * back[3] * (1 - front[3])) /
          alpha,
        (front[2] * front[3] +
          back[2] * back[3] * (1 - front[3])) /
          alpha,
        alpha,
      ];
    };
    const channel = (value: number) => {
      const normalized = value / 255;
      return normalized <= 0.04045
        ? normalized / 12.92
        : ((normalized + 0.055) / 1.055) ** 2.4;
    };
    const luminance = (color: Rgba) =>
      0.2126 * channel(color[0]) +
      0.7152 * channel(color[1]) +
      0.0722 * channel(color[2]);
    const ratio = (foreground: Rgba, background: Rgba) => {
      const foregroundLuminance = luminance(foreground);
      const backgroundLuminance = luminance(background);
      return (
        (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) /
        (Math.min(foregroundLuminance, backgroundLuminance) + 0.05)
      );
    };
    const ancestry = (element: Element) => {
      const result: Element[] = [];
      let current: Element | null = element;
      while (current) {
        result.unshift(current);
        current = current.parentElement;
      }
      return result;
    };
    const effectiveOpacity = (element: Element) =>
      ancestry(element).reduce((product, ancestor) => {
        const opacity = Number.parseFloat(
          window.getComputedStyle(ancestor).opacity,
        );
        return product * clampAlpha(opacity);
      }, 1);
    const effectiveBackground = (element: Element) => {
      let result: Rgba = [255, 255, 255, 1];
      let unresolvedImage = false;
      for (const ancestor of ancestry(element)) {
        const style = window.getComputedStyle(ancestor);
        if (style.backgroundImage !== "none") {
          unresolvedImage = true;
        }
        const layer = parseColor(style.backgroundColor);
        if (!layer || layer[3] <= 0) continue;
        const layerOpacity = clampAlpha(
          Number.parseFloat(style.opacity),
        );
        result = composite(
          [layer[0], layer[1], layer[2], layer[3] * layerOpacity],
          result,
        );
      }
      return { color: result, unresolvedImage };
    };
    const textRenderedBy = (element: Element) => {
      const directText = Array.from(element.childNodes)
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent?.trim() ?? "")
        .filter(Boolean)
        .join(" ");
      if (directText) return directText;
      if (
        element instanceof HTMLInputElement ||
        element instanceof HTMLTextAreaElement
      ) {
        return element.value || element.placeholder;
      }
      return "";
    };
    const markerFor = (element: Element) =>
      Array.from(element.attributes).find((attribute) =>
        attribute.name.startsWith("data-hermes"),
      )?.name ?? element.tagName.toLowerCase();

    const failures: string[] = [];
    for (const element of Array.from(root.querySelectorAll("*"))) {
      const html = element as HTMLElement;
      const renderedText = textRenderedBy(element);
      if (!renderedText) continue;
      if (
        html.closest(
          '[aria-hidden="true"], [hidden], nextjs-portal, [data-nextjs-toast], [data-next-mark]',
        )
      ) {
        continue;
      }
      const disabledControl =
        (html.matches(":disabled") ||
          html.getAttribute("aria-disabled") === "true") &&
        (html.matches("button, input, select, textarea, summary, a[href]") ||
          ["button", "link"].includes(html.getAttribute("role") ?? ""));
      if (disabledControl) continue;

      const style = window.getComputedStyle(html);
      const rect = html.getBoundingClientRect();
      const opacity = effectiveOpacity(html);
      if (
        style.display === "none" ||
        style.visibility === "hidden" ||
        style.visibility === "collapse" ||
        opacity <= 0.001 ||
        rect.width <= 0.5 ||
        rect.height <= 0.5
      ) {
        continue;
      }

      const foregroundRaw = parseColor(style.color);
      const background = effectiveBackground(html);
      if (!foregroundRaw) {
        failures.push(
          `${markerFor(html)} "${renderedText.slice(0, 64)}" has an unparsed foreground color`,
        );
        continue;
      }
      if (background.unresolvedImage) {
        failures.push(
          `${markerFor(html)} "${renderedText.slice(0, 64)}" has an unresolved background image`,
        );
        continue;
      }
      const foreground = composite(
        [
          foregroundRaw[0],
          foregroundRaw[1],
          foregroundRaw[2],
          foregroundRaw[3] * opacity,
        ],
        background.color,
      );
      const fontSize = Number.parseFloat(style.fontSize);
      const fontWeight = Number.parseInt(style.fontWeight, 10) || 400;
      const large =
        fontSize >= 24 || (fontSize >= 18.66 && fontWeight >= 700);
      const required = large ? 3 : 4.5;
      const actual = ratio(foreground, background.color);
      if (actual + 0.01 < required) {
        failures.push(
          `${markerFor(html)} "${renderedText.slice(0, 64)}" ${actual.toFixed(2)} < ${required.toFixed(1)} ` +
            `color=${style.color} opacity=${opacity.toFixed(3)} ` +
            `painted=rgb(${foreground.slice(0, 3).map((value) => value.toFixed(1)).join(",")}) ` +
            `background=rgb(${background.color.slice(0, 3).map((value) => value.toFixed(1)).join(",")})`,
        );
      }
    }
    return failures.slice(0, 50);
  });

  expect(
    offenders,
    `WCAG AA text contrast failures: ${offenders.join("; ")}`,
  ).toEqual([]);
}

/**
 * Scroll every visible control into view, require its complete rectangle to
 * fit the viewport and every clipping ancestor, then hit-test a 3x3 point
 * grid so an edge/corner overlay cannot hide behind a center-only check.
 */
export async function assertWholeHermesShellControlsUnclipped(page: Page) {
  const offenders = await page.locator(SHELL_SELECTOR).evaluate(
    async (root, selector) => {
      const failures: string[] = [];
      const controls = Array.from(root.querySelectorAll<HTMLElement>(selector));
      const overflowClips = (value: string) =>
        ["auto", "clip", "hidden", "scroll"].includes(value);
      const visible = (element: HTMLElement) => {
        if (
          element.closest(
            '[aria-hidden="true"], [hidden], nextjs-portal, [data-nextjs-toast], [data-next-mark]',
          )
        ) {
          return false;
        }
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          style.visibility !== "collapse" &&
          Number(style.opacity) > 0.001 &&
          rect.width > 0.5 &&
          rect.height > 0.5
        );
      };
      const nameFor = (element: HTMLElement) =>
        element.getAttribute("aria-label") ||
        element.textContent?.trim().slice(0, 64) ||
        element.getAttribute("href") ||
        element.tagName.toLowerCase();
      const nextFrame = () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        );

      for (const control of controls) {
        if (!visible(control)) continue;
        control.scrollIntoView({
          block: "center",
          inline: "center",
          behavior: "auto",
        });
        await nextFrame();

        const name = nameFor(control);
        const rect = control.getBoundingClientRect();
        if (
          rect.left < -1 ||
          rect.top < -1 ||
          rect.right > window.innerWidth + 1 ||
          rect.bottom > window.innerHeight + 1
        ) {
          failures.push(
            `viewport clipping: ${name} [${rect.left.toFixed(1)},${rect.top.toFixed(1)},${rect.right.toFixed(1)},${rect.bottom.toFixed(1)}]`,
          );
          continue;
        }

        let ancestor = control.parentElement;
        let clippedByAncestor = false;
        while (ancestor && ancestor !== document.documentElement) {
          const style = window.getComputedStyle(ancestor);
          const ancestorRect = ancestor.getBoundingClientRect();
          const clipLeft = ancestorRect.left + ancestor.clientLeft;
          const clipTop = ancestorRect.top + ancestor.clientTop;
          const clipRight = clipLeft + ancestor.clientWidth;
          const clipBottom = clipTop + ancestor.clientHeight;
          if (
            overflowClips(style.overflowX) &&
            (rect.left < clipLeft - 1 || rect.right > clipRight + 1)
          ) {
            failures.push(
              `ancestor horizontal clipping: ${name} by ${ancestor.tagName.toLowerCase()}`,
            );
            clippedByAncestor = true;
            break;
          }
          if (
            overflowClips(style.overflowY) &&
            (rect.top < clipTop - 1 || rect.bottom > clipBottom + 1)
          ) {
            failures.push(
              `ancestor vertical clipping: ${name} by ${ancestor.tagName.toLowerCase()}`,
            );
            clippedByAncestor = true;
            break;
          }
          ancestor = ancestor.parentElement;
        }
        if (clippedByAncestor) continue;

        const controlStyle = window.getComputedStyle(control);
        const edgeInset = Math.min(2, rect.width / 4, rect.height / 4);
        const cornerInset = Math.min(
          Math.max(
            edgeInset,
            ...[
              controlStyle.borderTopLeftRadius,
              controlStyle.borderTopRightRadius,
              controlStyle.borderBottomLeftRadius,
              controlStyle.borderBottomRightRadius,
            ].map((value) => Number.parseFloat(value) + 1 || edgeInset),
          ),
          rect.width / 4,
          rect.height / 4,
        );
        const points = [
          ["center", rect.left + rect.width / 2, rect.top + rect.height / 2],
          ["left edge", rect.left + edgeInset, rect.top + rect.height / 2],
          ["right edge", rect.right - edgeInset, rect.top + rect.height / 2],
          ["top edge", rect.left + rect.width / 2, rect.top + edgeInset],
          ["bottom edge", rect.left + rect.width / 2, rect.bottom - edgeInset],
          ["top left", rect.left + cornerInset, rect.top + cornerInset],
          ["top right", rect.right - cornerInset, rect.top + cornerInset],
          ["bottom left", rect.left + cornerInset, rect.bottom - cornerInset],
          ["bottom right", rect.right - cornerInset, rect.bottom - cornerInset],
        ] as const;
        const coveredPoints: string[] = [];
        for (const [pointName, x, y] of points) {
          const top =
            document
              .elementsFromPoint(x, y)
              .find(
                (candidate) =>
                  !candidate.closest(
                    "nextjs-portal, [data-nextjs-toast], [data-next-mark]",
                  ),
              ) ?? null;
          if (
            top &&
            top !== control &&
            !control.contains(top) &&
            !top.contains(control)
          ) {
            coveredPoints.push(
              `${pointName} by ${(top as HTMLElement).tagName.toLowerCase()}`,
            );
          }
        }
        if (coveredPoints.length > 0) {
          failures.push(`covered: ${name} at ${coveredPoints.join(", ")}`);
        }
      }
      return failures.slice(0, 50);
    },
    INTERACTIVE_SELECTOR,
  );

  expect(
    offenders,
    `clipped or covered Hermes controls: ${offenders.join("; ")}`,
  ).toEqual([]);
}

/**
 * Whole-shell landmark/status gate: one document main, named Hermes nav and
 * main region, and every visible status communicates with nonempty text.
 */
export async function assertWholeHermesShellSemanticStatus(page: Page) {
  await expect(page.locator("main")).toHaveCount(1);
  await expect(
    page.getByRole("navigation", { name: /Hermes workbench|Hermes 工作台/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", {
      name: /Hermes workbench main|Hermes 工作台主区/,
    }),
  ).toBeVisible();

  const textlessStatuses = await page.locator(SHELL_SELECTOR).evaluate((root) =>
    Array.from(root.querySelectorAll<HTMLElement>('[role="status"]'))
      .filter((element) => {
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          Number(style.opacity) > 0.001 &&
          rect.width > 0.5 &&
          rect.height > 0.5 &&
          !(element.textContent ?? "").trim()
        );
      })
      .map((element) => element.outerHTML.slice(0, 160)),
  );
  expect(
    textlessStatuses,
    `visible role=status surfaces need textual status: ${textlessStatuses.join("; ")}`,
  ).toEqual([]);
  await expect(page.getByTestId("global-safety-strip")).not.toHaveText("");
  await expect(page.getByTestId("hermes-today-state")).not.toHaveText("");
}
