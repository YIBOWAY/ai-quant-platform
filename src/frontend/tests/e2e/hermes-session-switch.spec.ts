import { writeFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

const OLD_SESSION = `web_${"1".repeat(40)}`;

test("new chat never returns to the old session while route navigation is delayed", async ({ page }, testInfo) => {
  test.skip(process.env.PW_HERMES_LIFECYCLE_FIXTURE !== "1", "Requires an isolated lifecycle fixture");
  await page.goto(`/en/hermes?hermes_session_id=${OLD_SESSION}`);
  const composer = page.getByRole("textbox", { name: "Talk with Hermes" });
  const send = page.getByRole("button", { name: "Send", exact: true });
  await expect(page.getByText("Fixture answer 28:")).toBeVisible();
  await expect(composer).toBeEnabled();
  const oldBaseline = await (await page.request.get(`/api/hermes/sessions/${OLD_SESSION}/messages`)).json();

  let releaseNavigation!: () => void;
  const navigationBarrier = new Promise<void>((resolve) => { releaseNavigation = resolve; });
  let delayedNavigation!: () => void;
  const navigationRequested = new Promise<void>((resolve) => { delayedNavigation = resolve; });
  await page.route(/\/en\/hermes\?/, async (route) => {
    const target = new URL(route.request().url()).searchParams.get("hermes_session_id");
    if (target && target !== OLD_SESSION) {
      delayedNavigation();
      await navigationBarrier;
    }
    await route.continue();
  });
  const createdPromise = page.waitForResponse(async (response) => {
    if (!response.url().endsWith("/api/workspace/ws-local-main/act")) return false;
    return response.request().postDataJSON()?.action?.kind === "managed_session.create";
  });
  await page.getByRole("button", { name: "New chat", exact: true }).click();
  const created = await (await createdPromise).json();
  await navigationRequested;
  try {
    // A slow Next navigation leaves the old page mounted. Its URL binder must
    // not override the explicit fresh-session selection while the user types.
    await expect(page.getByText("Fixture answer 28:")).not.toBeVisible();
    await composer.fill("Message belonging exclusively to the new conversation");
    await expect(send).toBeDisabled();
    await page.screenshot({ path: testInfo.outputPath("new-session-navigation-pending.png") });
  } finally {
    releaseNavigation();
  }
  await expect(page).toHaveURL(new RegExp(`hermes_session_id=${created.hermes_session_id}`));
  await expect(send).toBeEnabled();
  const submitted = page.waitForRequest((request) => request.method() === "POST" && request.url().endsWith("/api/agent/workspace/submit-turn"));
  await send.click();
  const submittedBody = (await submitted).postDataJSON();
  expect(submittedBody).toMatchObject({
    managed_session_ref: created.session_ref,
    prompt: "Message belonging exclusively to the new conversation",
  });
  const oldHistory = await page.request.get(`/api/hermes/sessions/${OLD_SESSION}/messages`);
  expect(await oldHistory.json()).toEqual(oldBaseline);
  const bindingPath = testInfo.outputPath("exact-session-binding.json");
  await writeFile(bindingPath, JSON.stringify({ created, submittedBody, previousSession: OLD_SESSION, previousSessionUnchanged: true }, null, 2));
  await testInfo.attach("exact-session-binding", {
    path: bindingPath,
    contentType: "application/json",
  });
  await page.screenshot({ path: testInfo.outputPath("new-session-submitted.png") });
});
