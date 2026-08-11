import { expect, test, type Page, type Route } from "@playwright/test";

import { assertNoHorizontalOverflow } from "./helpers/hermes-page-gates";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
  test.skip(
    process.env.PW_HERMES_WORKBENCH_FIXTURE !== "normal",
    "D-34 browser flow uses the normal deterministic Hermes fixture.",
  );
});

async function installD34OwnerFixture(page: Page) {
  const frontendPort = Number(process.env.PW_FRONTEND_PORT ?? "3001");
  await page.context().addCookies([
    {
      name: "qs_aw_csrf",
      value: "d34-browser-csrf",
      url: `http://127.0.0.1:${frontendPort}`,
    },
  ]);

  let mandateVersion = 1;
  let renewal: unknown = null;
  const mandate = () => ({
    contract: "hqa.mandate/v1",
    mandate_id: "mandate-browser-fixture-0001",
    owner_user_id: "00000000-0000-0000-0000-000000000001",
    workspace_id: "default",
    status: "active",
    universe: ["SPY", "QQQ", "IWM", "DIA"],
    hypotheses_per_cycle: 1,
    max_iterations: 3,
    max_experiments_per_iteration: 3,
    max_concurrent_jobs: 1,
    llm_budget_usd: "100.00",
    llm_warning_fraction: "0.80",
    paper_execution_allowed: true,
    policy_digest: "a".repeat(64),
    created_at: "2026-08-11T00:00:00Z",
    starts_at: "2026-08-11T00:00:00Z",
    expires_at: mandateVersion === 1 ? "2026-09-10T00:00:00Z" : "2026-10-10T00:00:00Z",
    updated_at: "2026-08-11T00:00:00Z",
    version: mandateVersion,
  });
  const fulfill = (route: Route, body: unknown) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/api/auth/owner/session", (route) =>
    fulfill(route, {
      session_id: "owner-session-d34-browser",
      mutation_enabled: true,
      security_ready: true,
      csrf_token: "d34-browser-csrf",
      csrf_header: "x-qs-aw-csrf",
    }),
  );
  await page.route("**/api/safety/effective/v2?**", (route) =>
    fulfill(route, {
      contract: "hqa.d34_effective_safety/v2",
      workspace_id: "default",
      paper_execution_enabled: true,
      research_execution_enabled: true,
      research_blockers: [],
      live_execution_enabled: false,
      blockers: [],
      active_mandate: {
        mandate_id: mandate().mandate_id,
        status: "active",
        expires_at: mandate().expires_at,
        remaining_seconds: 2_592_000,
        paper_execution_allowed: true,
      },
      emergency_stop: { active: false, reason: null, created_at: null },
      d33: { mode_enabled: false, auto_land_enabled: false },
      d34: { mandate_active: true, queued_jobs: 0, running_jobs: 0, active_canaries: 1 },
      budget: {
        limit_usd: "100.00",
        spent_usd: "7.25",
        remaining_usd: "92.75",
        warning_fraction: "0.80",
        warning: false,
      },
      quota: { max_new_canaries_per_day: 1, new_canaries_today: 1 },
      canaries: { active_count: 1, allocated_cash: "10000.00" },
      risk: {
        max_sleeve_cash: "10000.00",
        max_sleeve_nav_fraction: 0.01,
        max_total_nav_fraction: 0.1,
        max_symbol_nav_fraction: 0.05,
        max_daily_loss: 0.02,
        max_drawdown: 0.1,
      },
    }),
  );
  await page.route("**/api/hermes/mandates?**", (route) =>
    fulfill(route, { contract: "hqa.mandate_list/v1", items: [mandate()] }),
  );
  await page.route("**/api/hermes/mandates/*/renew", async (route) => {
    renewal = route.request().postDataJSON();
    mandateVersion = 2;
    await fulfill(route, mandate());
  });
  await page.route("**/api/hermes/research/jobs?**", (route) =>
    fulfill(route, {
      contract: "hqa.d34_experiment_job_list/v1",
      items: [
        {
          contract: "hqa.d34_experiment_job/v1",
          job_id: "job-browser-fixture-0001",
          mandate_id: mandate().mandate_id,
          workspace_id: "default",
          job_key: "cycle:2026-08-11:hypothesis:1",
          input_digest: "b".repeat(64),
          state: "succeeded",
          attempt_count: 1,
          max_attempts: 3,
          budget_reserved_usd: "10.00",
          budget_spent_usd: "7.25",
          outcome_code: "artifact_policy_accepted",
          lease_owner: null,
          lease_expires_at: null,
          heartbeat_at: null,
          created_at: "2026-08-11T00:00:00Z",
          updated_at: "2026-08-11T00:15:00Z",
          version: 4,
        },
      ],
    }),
  );
  await page.route("**/api/hermes/d34/artifacts?**", (route) =>
    fulfill(route, {
      contract: "hqa.d34_artifact_list/v1",
      items: [
        {
          contract: "hqa.d34_artifact/v1",
          artifact_id: "artifact-browser-fixture-0001",
          mandate_id: mandate().mandate_id,
          workspace_id: "default",
          status: "qualified",
          qualification_scope: "paper_only",
          policy_decision_id: "policy-browser-fixture-0001",
          policy_digest: "c".repeat(64),
          snapshot_digest: "d".repeat(64),
          candidate_code_digest: "e".repeat(64),
          qlib_config_digest: "f".repeat(64),
          rdagent_commit: "1".repeat(40),
          qlib_commit: "2".repeat(40),
          docker_image_digest: `sha256:${"3".repeat(64)}`,
          qlib_receipt_digest: "4".repeat(64),
          platform_receipt_digest: "5".repeat(64),
          comparison_digest: "6".repeat(64),
          created_at: "2026-08-11T00:15:00Z",
          updated_at: "2026-08-11T00:15:00Z",
          version: 1,
        },
      ],
    }),
  );
  await page.route("**/api/hermes/canaries?**", (route) =>
    fulfill(route, {
      contract: "hqa.d34_canary_list/v1",
      items: [
        {
          contract: "hqa.d34_canary/v1",
          canary_id: "canary-browser-fixture-0001",
          artifact_id: "artifact-browser-fixture-0001",
          mandate_id: mandate().mandate_id,
          workspace_id: "default",
          sleeve_id: "d34-browser-fixture-sleeve",
          status: "running",
          allocated_cash: "10000.00",
          nav_fraction: "0.010000",
          daily_pnl: "25.00",
          drawdown_fraction: "0.002000",
          created_at: "2026-08-11T00:16:00Z",
          updated_at: "2026-08-11T00:16:00Z",
          version: 1,
        },
      ],
    }),
  );

  return { renewal: () => renewal };
}

test("D-34 workbench shows the durable paper-only cycle and renews its Mandate", async ({
  page,
}) => {
  const fixture = await installD34OwnerFixture(page);
  await page.goto("/zh/hermes", { waitUntil: "networkidle" });

  await expect(page.getByRole("heading", { name: "Mandate 驱动的双引擎研究" })).toBeVisible();
  await expect(page.getByText("READY", { exact: true })).toBeVisible();
  await expect(page.getByText("live = false", { exact: true })).toBeVisible();
  await expect(page.getByText("artifact-b…xture-0001", { exact: true })).toBeVisible();
  await expect(page.getByText("canary-bro…xture-0001", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "立即停止" })).toBeVisible();
  await expect(page.getByRole("button", { name: /live/i })).toHaveCount(0);

  await page.getByRole("button", { name: "续期 30 天" }).click();
  await expect.poll(fixture.renewal).toEqual({
    duration_days: 30,
    expected_version: 1,
    reason: "owner renewed 30-day cycle from local workbench",
  });
  await assertNoHorizontalOverflow(page, page.viewportSize()!.width);
});
