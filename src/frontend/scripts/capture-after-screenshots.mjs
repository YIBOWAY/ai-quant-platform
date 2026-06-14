// One-shot screenshot sweep for the 2026-06-11 frontend refactor delivery doc.
// Usage: node scripts/capture-after-screenshots.mjs [baseUrl] [outDir]
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const baseUrl = process.argv[2] ?? "http://127.0.0.1:3001";
const outDir = process.argv[3] ?? path.resolve(process.cwd(), "../../output/ui-audit/after-2026-06-11");

const pages = [
  ["home", "/"],
  ["data-explorer", "/data-explorer"],
  ["backtest", "/backtest"],
  ["factor-lab", "/factor-lab"],
  ["experiments", "/experiments"],
  ["replications", "/replications"],
  ["paper-trading", "/paper-trading"],
  ["position-map", "/position-map"],
  ["options-screener", "/options-screener"],
  ["options-buyside", "/options-buyside"],
  ["options-tools", "/options-tools"],
  ["options-radar", "/options-radar"],
  ["order-book", "/order-book"],
  ["agent-studio", "/agent-studio"],
  ["settings", "/settings"],
  ["zh-home", "/zh"],
  ["zh-factor-lab", "/zh/factor-lab"],
  ["zh-paper-trading", "/zh/paper-trading"],
];

fs.mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();

for (const [name, route] of pages) {
  try {
    await page.goto(`${baseUrl}${route}`, { waitUntil: "networkidle", timeout: 45_000 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(outDir, `${name}.png`) });
    console.log(`ok ${name}`);
  } catch (error) {
    console.error(`fail ${name}: ${error.message}`);
  }
}

// Mobile spot-checks for the two redesigned mobile-critical pages.
await page.setViewportSize({ width: 390, height: 844 });
for (const [name, route] of [
  ["position-map-mobile", "/position-map"],
  ["paper-trading-mobile", "/paper-trading"],
]) {
  try {
    await page.goto(`${baseUrl}${route}`, { waitUntil: "networkidle", timeout: 45_000 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(outDir, `${name}.png`) });
    console.log(`ok ${name}`);
  } catch (error) {
    console.error(`fail ${name}: ${error.message}`);
  }
}

await browser.close();
console.log(`done -> ${outDir}`);
