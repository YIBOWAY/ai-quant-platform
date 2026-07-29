from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def initialize_repository(path: Path, *, hqa: bool = False) -> Path:
    path.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "codex/agent-v0-2-release"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "release-ops@example.invalid"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Release Ops Test"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "remote", "add", "github", f"https://example.invalid/{path.name}.git"],
        cwd=path,
        check=True,
    )
    if hqa:
        (path / "hqa").mkdir()
        (path / "hqa" / "__init__.py").write_text(
            '"""fixture."""\n',
            encoding="utf-8",
        )
    return path


def install_fake_release_status_cli(
    repository: Path,
) -> None:
    exclude = repository / ".git" / "info" / "exclude"
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write(".venv/\n")
    bin_dir = repository / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python3"
    python.symlink_to(Path(sys._base_executable).resolve())
    cli = bin_dir / "quant-system"
    cli.write_text(
        f"#!{python}\n"
        "# -*- coding: utf-8 -*-\n"
        "import sys\n"
        "from quant_system.cli import app\n"
        'if __name__ == "__main__":\n'
        '    if sys.argv[0].endswith("-script.pyw"):\n'
        "        sys.argv[0] = sys.argv[0][:-11]\n"
        '    elif sys.argv[0].endswith(".exe"):\n'
        "        sys.argv[0] = sys.argv[0][:-4]\n"
        "    sys.exit(app())\n",
        encoding="utf-8",
    )
    cli.chmod(0o755)


def materialize_platform_repository(
    path: Path,
    *,
    mutate_on_postflight: Path | str | None = None,
) -> Path:
    repository = initialize_repository(path)
    source = repository / "src" / "quant_system"
    shutil.copytree(
        ROOT / "src" / "quant_system",
        source,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (repository / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    payload = {
        "contract": "agent-v0.2-release-cli/v1",
        "decision": {
            "release_authorized": False,
            "public_write_authorized": False,
            "chat_write_ready": False,
            "ready": False,
            "blockers": ["release_missing"],
        },
    }
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    mutation = os.fspath(mutate_on_postflight) if mutate_on_postflight else None
    (source / "cli.py").write_text(
        "import sys\n"
        "from pathlib import Path\n"
        f"PAYLOAD = {rendered!r}\n"
        f"MUTATION = {mutation!r}\n"
        "def app():\n"
        "    if sys.argv[1:] != ['hermes', 'release', 'status']:\n"
        "        raise SystemExit(64)\n"
        "    counter = Path(sys.argv[0]).with_name('status-call-count')\n"
        "    calls = int(counter.read_text() or '0') + 1 if counter.exists() else 1\n"
        "    counter.write_text(str(calls))\n"
        "    if calls == 2 and MUTATION:\n"
        "        target = Path(sys.argv[0]) if MUTATION == '__SELF__' else Path(MUTATION)\n"
        "        target.write_text(target.read_text() + '\\n# postflight drift\\n')\n"
        "    print(PAYLOAD)\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "platform fixture"], cwd=repository, check=True)
    install_fake_release_status_cli(repository)
    return repository


def materialize_hqa_repository(path: Path) -> Path:
    repository = initialize_repository(path, hqa=True)
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "HQA fixture"], cwd=repository, check=True)
    return repository


def fixture_environment(platform: Path) -> dict[str, str]:
    keep = {
        name: os.environ[name]
        for name in (
            "HOME",
            "LANG",
            "LC_ALL",
            "PATH",
            "PYTHONPYCACHEPREFIX",
            "TEMP",
            "TMP",
            "TMPDIR",
            "XDG_CACHE_HOME",
        )
        if name in os.environ
    }
    return {
        **keep,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(platform / "src"),
        "PYTHONNOUSERSITE": "1",
        "QS_DATABASE_AUTO_MIGRATE": "false",
        "QS_KILL_SWITCH": "true",
        "QS_LIVE_TRADING_ENABLED": "false",
    }


def run_fixture_script(
    platform: Path,
    script: str,
    *,
    extra_env: dict[str, str] | None = None,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    environment = fixture_environment(platform)
    if extra_env:
        environment.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=platform,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
