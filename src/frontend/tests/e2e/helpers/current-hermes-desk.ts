import { expect, type Page } from "@playwright/test";

/** Actual current desk contract: three ledgers plus source-bound read state.
 * The retired Today aggregate score/data-state is not a current product API. */
export async function assertCurrentHermesDesk(page: Page) {
  await expect(page.locator("[data-hermes-desk]")).toBeVisible();
  await expect(page.locator("#hermes-ledger-panel")).toBeVisible();
  await expect(page.getByRole("tablist", { name: /研究与运行|Research & simulation/ })).toBeVisible();
  await expect(page.getByRole("tab")).toHaveCount(3);
  await expect(page.locator(".dp-hero-title")).toHaveText(/研究与运行|Research & simulation/);
  const scenario = process.env.PW_HERMES_WORKBENCH_FIXTURE;
  const description = scenario === "offline" ? /暂时无法读取研究与模拟状态|Research and simulation status is unavailable/
    : scenario === "empty" ? /发起一次研究|Start a research task/
      : scenario === "degraded" ? /有 1 条模拟运行中|1 running in simulation/
        : /1 条已验证候选|1 verified candidate/;
  await expect(page.locator(".dp-hero-description")).toHaveText(description);
  const clippedCardContent = await page.locator('.dp-blotter[data-ledger="duty"] .dp-strat-name, .dp-blotter[data-ledger="duty"] .dp-status').evaluateAll(nodes => nodes.flatMap(node => {
    const rect = node.getBoundingClientRect();
    const frame = node.closest(".dp-blotter")!.getBoundingClientRect();
    const row = node.closest(".dp-row")!.getBoundingClientRect();
    return rect.left < frame.left - 1 || rect.right > frame.right + 1 || rect.top < row.top - 1 || rect.bottom > row.bottom + 1
      ? [node.textContent] : [];
  }));
  expect(clippedCardContent, "strategy titles and status badges must fit inside their visible card").toEqual([]);
  if (scenario === "offline") {
    await expect(page.locator('[data-book-read-status="unavailable"]')).toContainText("策略与研究记录暂时无法读取");
    await expect(page.locator(".dp-sechead .count")).toHaveText("记录未知");
    await expect(page.getByText("还没有研究记录。可以在对话中发送策略或论文。", { exact: true })).toHaveCount(0);
    expect((await page.locator("body").innerText()).replaceAll(/\s+/g, "")).not.toContain("模拟运行中0·候选0");
  }
  if (scenario === "degraded") await expect(page.locator('[data-observation-yesterday="data_unavailable"]')).toBeVisible();
  if (scenario === "long-content") {
    const title = page.locator(".dp-strat-name").filter({ hasText: "测试长文研究：跨市场动量" });
    await expect(title).toHaveText("测试长文研究：跨市场动量与换仓成本的逐期对照及缺失数据边界检查");
    const geometry = await title.evaluate(node => {
      const range = document.createRange(); range.selectNodeContents(node);
      const frame = node.closest(".dp-blotter")!.getBoundingClientRect();
      const own = node.getBoundingClientRect();
      return { overflow: node.scrollWidth - node.clientWidth,
        clippedLines: [...range.getClientRects()].filter(rect => rect.left < frame.left - 1 || rect.right > frame.right + 1 || rect.top < own.top - 1 || rect.bottom > own.bottom + 1).length };
    });
    expect(geometry.overflow).toBeLessThanOrEqual(1); expect(geometry.clippedLines).toBe(0);
  }
  if (page.viewportSize()!.width > 960) await expect(page.locator("[data-hermes-chat-connection]")).toHaveAttribute("data-hermes-chat-connection", scenario === "offline" ? "unavailable" : "read_only");
  await expect(page.getByTestId("hermes-capability-notice")).toHaveAttribute("data-read-state", scenario === "offline" ? "unavailable" : "available");
}
