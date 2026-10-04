from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_retired_product_sources_are_absent() -> None:
    retired = (
        "src/quant_system/api/routes/d34.py",
        "src/quant_system/api/schemas/d34.py",
        "src/quant_system/d34/final_acceptance.py",
        "src/quant_system/d34/research_routing.py",
        "src/quant_system/execution/d34_canary_activation.py",
        "src/quant_system/execution/d34_canary_control.py",
        "src/quant_system/execution/d34_canary_monitor.py",
        "src/quant_system/execution/factor_automation_activation.py",
        "src/quant_system/execution/factor_automation_authority.py",
        "src/quant_system/execution/factor_automation_demote.py",
        "src/quant_system/execution/factor_automation_safety.py",
        "src/quant_system/hermes/gate_observe.py",
        "src/quant_system/hermes/d34_mandate_authority.py",
        "src/quant_system/hermes/gate_surface_authority.py",
        "src/quant_system/hermes/paper_gate_authority.py",
        "src/quant_system/hermes/paper_gate_cli.py",
        "src/quant_system/hermes/paper_gate_port.py",
        "src/quant_system/hermes/paper_gate_source_evidence.py",
        "scripts/install_factor_automation_launchagent.sh",
        "scripts/coo_unify_seed_mandate.py",
        "scripts/run_factor_automation_driver.sh",
        "scripts/launchd/com.aiquant.factor-automation.plist.template",
        "docs/runbooks/d34-autonomous-paper.md",
    )

    assert [relative for relative in retired if (REPO / relative).exists()] == []


def test_current_product_wire_has_no_retired_action_kind() -> None:
    paths = (
        "src/quant_system/hermes/agent_workspace_actions.py",
        "src/quant_system/hermes/submission_saga.py",
        "src/quant_system/api/routes/workspace.py",
        "src/quant_system/api/schemas/workspace.py",
    )
    forbidden = (
        "research.start",
        "research.continue",
        "research.plan.confirm",
        "gate1.",
        "gate2.",
        "gate3.",
        "vertical.factor_b",
    )
    matches = []
    for relative in paths:
        source = (REPO / relative).read_text(encoding="utf-8")
        matches.extend(f"{relative}:{term}" for term in forbidden if term in source)

    assert matches == []


def test_connector_cli_has_no_retired_workflow_binding_commands() -> None:
    source = (REPO / "src/quant_system/hermes/connector_cli.py").read_text(encoding="utf-8")

    assert "workflow-binding" not in source
    assert "ensure_bound_command" not in source
    assert "iter_workflow_binding_inventory" not in source
