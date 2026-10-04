import { execFileSync } from "node:child_process";
import net from "node:net";
import path from "node:path";
import { expect, test } from "@playwright/test";

let sentinel: net.Server;
let futuConnections = 0;
let dataRoot = "";
const repoRoot = path.resolve(process.cwd(), "../..");
let seed: {
  candidate_id: string;
  source_digest: string;
};

test.describe("candidate library real file-account flow", () => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");

  test.beforeAll(async ({}, testInfo) => {
    const run = testInfo.config.metadata.e2eRun as
      | { dataRoot?: unknown }
      | undefined;
    if (!run || typeof run.dataRoot !== "string" || !run.dataRoot.trim()) {
      throw new Error("Playwright e2eRun.dataRoot metadata is required");
    }
    dataRoot = run.dataRoot;
    const python = process.env.PW_PYTHON;
    if (!python) throw new Error("PW_PYTHON is required");
    const fixture = path.resolve(
      repoRoot,
      "tests/support/library_fullstack_fixture.py",
    );
    seed = JSON.parse(
      execFileSync(python, [fixture, "seed", dataRoot], {
        encoding: "utf-8",
        env: {
          ...process.env,
          PYTHONPATH: `${path.join(repoRoot, "src")}:${repoRoot}`,
        },
      }),
    );
    const sentinelPort = Number(process.env.PW_FUTU_SENTINEL_PORT ?? "19891");
    sentinel = net.createServer((socket) => {
      futuConnections += 1;
      socket.destroy();
    });
    await new Promise<void>((resolve, reject) => {
      sentinel.once("error", reject);
      sentinel.listen(sentinelPort, "127.0.0.1", resolve);
    });
  });

  test.afterAll(async () => {
    if (sentinel) {
      await new Promise<void>((resolve) => sentinel.close(() => resolve()));
    }
  });

  test("browser to FastAPI hangs exact digest zero-one-one with no Futu", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/en/library");
    const ownerSession = await page.evaluate(async () => {
      const response = await fetch("/api/auth/owner/session", {
        credentials: "same-origin",
      });
      return { status: response.status, text: await response.text() };
    });
    expect(ownerSession.status, ownerSession.text).toBe(200);

    const before = await page.request.get("/api/assistant/remote/book");
    expect(before.status()).toBe(200);
    expect((await before.json()).hung_count).toBe(0);

    const candidate = page.locator(".min-h-64").filter({ has: page.getByText(seed.candidate_id, { exact: true }) });
    const button = candidate.getByRole("button", { name: /^Enable simulated running:/ });
    await expect(button).toBeVisible();
    futuConnections = 0;
    await button.focus();
    const firstResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/assistant/remote/hang") &&
        response.request().method() === "POST",
    );
    await page.keyboard.press("Enter");
    const first = await firstResponse;
    expect(first.status()).toBe(200);
    const firstBody = await first.json();
    expect(firstBody.already_hung).toBe(false);
    await expect(page.locator('[data-hang-state="hung"]')).toBeVisible();
    const csrf = await page.evaluate(() => {
      const row = document.cookie
        .split(";")
        .map((value) => value.trim())
        .find((value) => value.startsWith("qs_aw_csrf="));
      return row ? decodeURIComponent(row.split("=", 2)[1]) : "";
    });
    expect(csrf).not.toBe("");

    const replay = await page.evaluate(
      async ({ candidateId, sourceDigest, csrfToken }) => {
        const response = await fetch("/api/assistant/remote/hang", {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "content-type": "application/json",
            "X-CSRF-Token": csrfToken,
          },
          body: JSON.stringify({
            candidate_id: candidateId,
            expected_source_digest: sourceDigest,
          }),
        });
        return { status: response.status, body: await response.json() };
      },
      {
        candidateId: seed.candidate_id,
        sourceDigest: seed.source_digest,
        csrfToken: csrf,
      },
    );
    expect(replay.status).toBe(200);
    const replayBody = replay.body;
    expect(replayBody.already_hung).toBe(true);
    expect(replayBody.sleeve_id).toBe(firstBody.sleeve_id);

    const after = await page.request.get("/api/assistant/remote/book");
    expect(after.status()).toBe(200);
    expect((await after.json()).hung_count).toBe(1);
    const python = process.env.PW_PYTHON as string;
    const fixture = path.resolve(
      repoRoot,
      "tests/support/library_fullstack_fixture.py",
    );
    const persisted = JSON.parse(
      execFileSync(python, [fixture, "inspect", dataRoot], {
        encoding: "utf-8",
        env: {
          ...process.env,
          PYTHONPATH: `${path.join(repoRoot, "src")}:${repoRoot}`,
        },
      }),
    );
    expect(persisted).toEqual({
      allocation_count: 1,
      allocated_cash: 10_000,
      sleeve_count: 1,
    });
    expect(futuConnections).toBe(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
});
