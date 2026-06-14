from pathlib import Path


def test_e2e_specs_do_not_write_to_real_data_dir() -> None:
    e2e_dir = Path("src/frontend/tests/e2e")
    hits: list[str] = []
    for path in e2e_dir.glob("*.ts"):
        text = path.read_text(encoding="utf-8")
        if 'path.join(repoRoot, "data"' in text:
            hits.append(path.as_posix())

    assert hits == []
