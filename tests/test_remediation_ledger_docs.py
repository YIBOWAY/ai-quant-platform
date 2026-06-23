from pathlib import Path


def test_remediation_ledger_is_linked_from_current_doc_entrypoints() -> None:
    ledger = Path("docs/audits/remediation_ledger_2026-06-23.md")
    assert ledger.exists()

    index = Path("docs/INDEX.md").read_text(encoding="utf-8")
    audits_readme = Path("docs/audits/README.md").read_text(encoding="utf-8")

    assert "audits/remediation_ledger_2026-06-23.md" in index
    assert "remediation_ledger_2026-06-23.md" in audits_readme


def test_remediation_ledger_records_user_decisions_and_package_queue() -> None:
    ledger = Path("docs/audits/remediation_ledger_2026-06-23.md").read_text(
        encoding="utf-8"
    )

    for required in (
        ".understand-anything/` 保留为项目资产",
        "`/replications` 可改为 `/strategies`",
        "前端 API 类型可以从 FastAPI OpenAPI schema 生成",
        "前端继续双语",
        "Remediation Package A: Result Credibility Baseline",
        "Remediation Package B: Contract Drift Baseline",
    ):
        assert required in ledger


def test_understand_anything_asset_policy_ignores_local_trash_only() -> None:
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    gitignore_lines = set(gitignore.splitlines())

    assert ".understand-anything/" not in gitignore_lines
    assert ".understand-anything/.trash-*/" in gitignore_lines
    assert ".DS_Store" in gitignore_lines
    assert Path(".DS_Store").match(".DS_Store")
    assert Path("docs/.DS_Store").match(".DS_Store")
    for graph_asset in (
        ".understand-anything/.understandignore",
        ".understand-anything/config.json",
        ".understand-anything/fingerprints.json",
        ".understand-anything/intermediate/scan-result.json",
        ".understand-anything/knowledge-graph.json",
        ".understand-anything/meta.json",
    ):
        assert Path(graph_asset).exists()
