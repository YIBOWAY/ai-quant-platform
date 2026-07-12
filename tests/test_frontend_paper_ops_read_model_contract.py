from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_paper_ops_panel_exposes_pending_sleeves_without_promising_get_recovery() -> None:
    api_types = _read("src/frontend/lib/api.ts")
    generated_types = _read("src/frontend/lib/api.generated.ts")
    panel = _read("src/frontend/components/forms/PaperStrategyOpsPanel.tsx")

    assert "pending_sleeve_count: number;" in api_types
    assert "corrupt_journal_count: number;" in api_types
    assert "pending_sleeve_count: number;" in generated_types
    assert "corrupt_journal_count: number;" in generated_types
    assert "status?.pending_sleeve_count" in panel
    assert "status.pending_sleeve_count" in panel
    assert "next status/detail access" not in panel
    assert "下一次状态或详情访问" not in panel
    assert "explicit execution processor" in panel
    assert "显式执行处理器" in panel
    assert "status remains read-only" in panel
    assert "状态仍可只读查看" in panel
    assert "paper strategies recover-pending" in panel
    assert "status?.corrupt_journal_count" in panel
    assert "status.corrupt_journal_count" in panel
