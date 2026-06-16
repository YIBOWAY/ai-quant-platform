from pathlib import Path

SCRIPTS_DIR = Path("scripts")
SCRIPTS_README = SCRIPTS_DIR / "README.md"
INDEXED_SUFFIXES = {".py", ".ps1", ".sh"}


def test_scripts_readme_indexes_top_level_entrypoints() -> None:
    assert SCRIPTS_README.exists()

    readme = SCRIPTS_README.read_text(encoding="utf-8")
    scripts = sorted(
        path.name
        for path in SCRIPTS_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in INDEXED_SUFFIXES
    )

    missing = [script for script in scripts if f"`{script}`" not in readme]
    assert not missing
