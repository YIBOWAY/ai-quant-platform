from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_terminal_palette_uses_readable_info_accent() -> None:
    globals_css = read("src/frontend/app/globals.css")

    assert "--color-info: #5EA2FF;" in globals_css
    assert "--color-secondary: #5EA2FF;" in globals_css
    assert "--color-info: #2962FF" not in globals_css


def test_terminal_primitives_expose_focusable_responsive_shell() -> None:
    primitives = read("src/frontend/components/ui/primitives.tsx")

    assert "export function TerminalSplitShell" in primitives
    assert 'data-terminal-split-shell="true"' in primitives
    assert "flex-col overflow-y-auto" in primitives
    assert "lg:flex-row lg:overflow-hidden" in primitives
    assert 'data-terminal-table-scroll="true"' in primitives
    assert "tabIndex={0}" in primitives
    assert "focus-visible:outline" in primitives


def test_locale_toggle_uses_distinct_active_segment() -> None:
    source = read("src/frontend/components/LocaleToggle.tsx")

    assert "rounded-lg border border-border-subtle bg-bg-base p-0.5 font-data-mono" in source
    assert "bg-info/15 text-text-primary ring-1 ring-inset ring-info/45" in source
    assert "bg-bg-surface-muted text-text-primary" not in source


def test_paper_trading_holdings_match_position_map_exposure_language() -> None:
    source = read("src/frontend/app/paper-trading/page.tsx")

    assert "sourceMix" in source
    assert "barWidthPct" in source
    assert "bg-accent-success" in source
    assert "bg-info" in source
    assert "bg-danger" in source
    assert "bg-danger/60" in source
    assert "strategyShare * 100" in source
    assert "manualShare * 100" in source
    assert "Market Value" in source
    assert "市值" in source


def test_split_workbench_pages_use_responsive_terminal_shell() -> None:
    pages = {
        "src/frontend/app/backtest/page.tsx": [
            "flex h-full flex-1 overflow-hidden bg-bg-base",
            "flex h-full w-[320px]",
        ],
        "src/frontend/components/forms/OptionsRadarView.tsx": [
            "grid-cols-[360px_1fr]",
        ],
        "src/frontend/components/forms/StrategyCatalogWorkbench.tsx": [
            "flex h-full min-h-0 bg-bg-base",
            "flex h-full w-[360px] shrink-0",
        ],
        "src/frontend/app/experiments/page.tsx": [
            "flex h-full w-full overflow-hidden bg-bg-base",
            "flex h-full w-[320px] shrink-0",
        ],
        "src/frontend/app/agent-studio/page.tsx": [
            "flex h-full w-full overflow-hidden bg-bg-base",
            "flex h-full w-[300px] shrink-0",
        ],
        "src/frontend/components/forms/OptionsScreenerForm.tsx": [
            "grid h-full min-h-0 grid-cols-[380px_1fr] overflow-hidden",
        ],
    }

    for path, forbidden_fragments in pages.items():
        source = read(path)
        assert "TerminalSplitShell" in source
        assert "<TerminalSplitShell" in source
        for fragment in forbidden_fragments:
            assert fragment not in source


def test_frontend_component_directory_contracts_exist() -> None:
    assert Path("src/frontend/components/editorial/index.ts").is_file()
    assert Path("src/frontend/components/hermes/index.ts").is_file()


def test_hermes_workbench_is_read_only_artifact_shelf() -> None:
    hermes_page = Path("src/frontend/app/hermes/page.tsx")
    assert hermes_page.is_file()

    source = read("src/frontend/app/hermes/page.tsx")
    shell = read(
        "src/frontend/components/hermes/shell/HermesWorkbenchShell.tsx"
    )
    today = read(
        "src/frontend/components/hermes/today/HermesTodayView.tsx"
    )
    copy = read("src/frontend/lib/hermes/copy.ts")
    hermes_index = read("src/frontend/components/hermes/index.ts")
    composer = read("src/frontend/components/hermes/ComposerDock.tsx")

    assert "AgentTaskForm" not in source
    assert "/api/agent/tasks" not in source
    assert "apiPost" not in source
    assert "getAgentLlmConfig" not in source
    assert "HermesTodayView" in source
    assert "ComposerDock" in shell
    assert "allowSubmit={false}" in shell
    assert "disabled" in shell
    assert "ArtifactFeed" in today
    assert "getAgentCandidates" in source
    assert "getHermesArtifacts" in source
    assert "Promise.all" in source
    assert "hermesWorkbenchCopy" in today
    assert (
        "Read-only research desk prioritizing action, exceptions, and conclusions. "
        "Submit remains disabled."
    ) in copy
    assert "以行动、异常与结论为先的只读研究工作台。提交仍保持禁用。" in copy
    assert "Read-only skeleton" not in source
    assert "只读骨架" not in source
    assert "streamPlaceholderA" not in source
    assert "streamPlaceholderB" not in source
    assert "export { ComposerDock }" in hermes_index
    assert "export { ArtifactShelf }" in hermes_index
    assert "apiPost" not in composer
    assert "fetch(" not in composer

    agent_studio = read("src/frontend/app/agent-studio/page.tsx")
    assert "TerminalSplitShell" in agent_studio
    assert "<TerminalSplitShell" in agent_studio
    assert "AgentTaskForm" not in agent_studio
    assert "getAgentLlmConfig" not in agent_studio
    assert (
        "Task submission and approve/reject controls are intentionally unavailable"
        in agent_studio
    )
    assert "任务提交与批准/拒绝控件已明确关闭" in agent_studio
    assert 'href={`/${locale}/hermes`}' in agent_studio


def test_agent_candidate_surfaces_fail_closed_on_missing_contract_or_repository() -> None:
    task_form = read("src/frontend/components/forms/AgentTaskForm.tsx")
    agent_studio = read("src/frontend/app/agent-studio/page.tsx")

    assert 'detail.integrity_state !== "verified"' in task_form
    assert 'detail.approval_binding !== "pending"' in task_form
    assert "candidate.approval_enabled === true" in task_form
    assert "candidate.integrity_state === \"verified\"" in task_form
    assert "candidates.apiError ? (" in agent_studio
    assert "data-agent-candidates-unavailable" in agent_studio
    assert "candidateUnavailableTitle" in agent_studio
    assert "candidateUnavailableDesc" in agent_studio
    assert "AgentTaskForm" not in agent_studio
    assert "/api/agent/tasks" not in agent_studio


def test_hermes_approvals_remain_read_only_until_hqa_binding_and_bff_security_land() -> None:
    approvals = read("src/frontend/app/hermes/approvals/page.tsx")
    feature_flags = read("src/frontend/lib/hermes/featureFlags.ts")
    feature_types = read("src/frontend/lib/hermes/types.ts")

    assert "HermesGate2ReviewControls" not in approvals
    assert "listRowShowsGate2Controls" not in approvals
    assert "/api/agent/candidates/" not in approvals
    assert "apiPost" not in approvals
    assert "approvalMutations: false" in feature_flags
    assert "approvalMutations: false" in feature_types
    assert "网页审批写端已安全关闭" in approvals
    assert "HQA Gate 1 exact binding" in approvals


def test_hermes_sessions_are_read_only_through_the_platform_bff() -> None:
    routes = read("src/frontend/lib/hermes/routes.ts")
    api = read("src/frontend/lib/api.ts")
    nav = read("src/frontend/components/hermes/shell/HermesInternalNav.tsx")
    sessions_page = Path("src/frontend/app/hermes/sessions/page.tsx")
    detail_page = Path("src/frontend/app/hermes/sessions/[sessionId]/page.tsx")

    assert sessions_page.is_file()
    assert detail_page.is_file()
    assert 'sessions: "/hermes/sessions"' in routes
    assert "getHermesGatewayStatus" in api
    assert "getHermesSessions" in api
    assert "getHermesSessionMessages" in api
    assert 'id: "sessions"' in nav
    combined = sessions_page.read_text(encoding="utf-8") + detail_page.read_text(
        encoding="utf-8"
    )
    assert "Authorization" not in combined
    assert "API_SERVER_KEY" not in combined
    assert "fetch(" not in combined
    assert "getHermesSessionMessages" in combined
