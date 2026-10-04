// Current desk scenarios. All are test-only persisted facts, never live runs.
export function deskFixture(scenario) {
  const offline = scenario === "offline";
  const empty = scenario === "empty";
  const degraded = scenario === "degraded";
  const candidate = { candidate_id: `e2e-desk-${scenario}`, factor_id: "e2e-factor", source_digest: "f".repeat(64),
    objective: "E2E source-bound research fixture", universe: ["AAPL", "MSFT"],
    status: degraded ? "hung" : "verified", sleeve_id: degraded ? "e2e-sleeve-data-gap" : null,
    activation_eligibility: { eligible: false, reason: "fixture_read_only" },
    display_name: "Fixture monthly momentum", display_name_zh: scenario === "long-content" ? "测试长文研究：跨市场动量与换仓成本的逐期对照及缺失数据边界检查" : "测试月度动量",
    summary_zh: scenario === "long-content" ? "仅用于浏览器长文本测试；保留研究说明、数据来源与未完成验证的边界。".repeat(10) : "测试夹具中已保存的研究记录，不是真实回测业绩。",
    fossil: false, official_observation: true };
  return {
    offline,
    book: { contract: "hqa.assistant_remote_book/v1", candidates: empty || offline ? [] : [candidate], requests: [],
      verified_count: !empty && !offline && !degraded ? 1 : 0, hung_count: degraded ? 1 : 0, fossil_count: 0, fossils: [] },
    safety: { owner_user_id: "root", workspace_id: "ws-local-main", global_kill_switch: true,
      canonical_account_count: offline ? null : 1, canonical_account_frozen: offline ? null : true,
      current_paper_authority_epoch: offline ? null : 1, effective: !offline,
      blockers: offline ? ["fixture_source_unavailable"] : [] },
    calendar: { yesterday: { date: "2026-07-28", status: degraded ? "data_unavailable" : "not_scheduled",
      label_zh: degraded ? "昨日已运行，但信号数据不可用" : "昨日无排程", counts_as_observation_day: false,
      is_no_signal: false, reason: degraded ? "fixture_market_data_unavailable" : null },
      expected_nights: degraded ? ["2026-07-28"] : [], recorded_nights: degraded ? ["2026-07-28"] : [], absent_nights: [], pending_nights: [],
      observation_day_count: 0, calendar_run_day_count: degraded ? 1 : 0, data_unavailable_day_count: degraded ? 1 : 0,
      filled_day_count: 0, filled_nights: [] },
  };
}

export function fixtureResults(artifacts, scenario, query) {
  const unavailable = artifacts.read_status === "unavailable";
  const titles = { weekly_review: "测试周报复盘", opportunity_summary: "测试机会复盘", automation_status: "测试自动化状态", market_foresight: "测试市场推演", prediction: "测试预测记录", portfolio_risk: "测试组合风险" };
  const english = { weekly_review: "Fixture weekly review", opportunity_summary: "Fixture opportunity review", automation_status: "Fixture automation", market_foresight: "Fixture market study", prediction: "Fixture prediction", portfolio_risk: "Fixture portfolio risk" };
  const all = artifacts.items.map(artifact => ({ kind: artifact.kind, resource_id: artifact.id,
    display_title: english[artifact.kind] || artifact.id, display_title_zh: titles[artifact.kind] || artifact.id,
    summary: "E2E fixture · Read-only source record", summary_zh: "E2E fixture · 只读来源记录",
    status: artifact.status, occurred_at: artifact.occurred_at, source: "hqa_artifact_feed", authority: "hqa_artifact_manifest",
    freshness: "unknown", read_status: artifact.quality === "available" ? "available" : "degraded",
    detail_href: `/api/hermes/results/${artifact.kind}/${artifact.id}`, original_href: "/api/hermes/artifacts", run_links: [] }));
  const selected = all.filter(item => !query.get("kind") || item.kind === query.get("kind"));
  const limit = Number(query.get("limit") || 20), offset = Number(query.get("offset") || 0);
  return { read_status: unavailable ? "unavailable" : scenario === "degraded" || scenario === "long-content" ? "degraded" : "available",
    items: selected.slice(offset, offset + limit), limit, offset, has_more: selected.length > offset + limit,
    total: unavailable ? null : selected.length, total_is_exact: !unavailable,
    sources: [{ source: "hqa_artifact_feed", read_status: unavailable ? "unavailable" : "available", item_count: all.length }],
    warnings: unavailable ? [{ source: "hqa_artifact_feed", code: "source_unavailable" }] : [] };
}
