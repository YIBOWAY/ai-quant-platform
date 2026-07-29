from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "verify_backend_non_postgres.sh"
HELPER = ROOT / "scripts" / "backend_non_postgres_gate.py"


def _gate_helper():
    spec = importlib.util.spec_from_file_location("backend_non_postgres_gate_repairs", HELPER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_runner_binds_node_as_a_helper_only_runtime(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    scripts = release_root / "scripts"
    scripts.mkdir(parents=True)
    wrapper = scripts / RUNNER.name
    shutil.copy2(RUNNER, wrapper)
    wrapper.chmod(0o755)
    helper = scripts / "backend_non_postgres_gate.py"
    helper.write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        ["bash", str(wrapper), "--describe"],
        cwd=release_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    helper_argv = json.loads(completed.stdout)
    node_index = helper_argv.index("--node")
    public_boundary = helper_argv.index("--public-argv")
    expected_node = shutil.which("node")
    assert expected_node is not None
    assert Path(helper_argv[node_index + 1]).resolve() == Path(expected_node).resolve()
    assert node_index < helper_argv.index("--public-entrypoint") < public_boundary


def test_public_runner_rejects_user_supplied_node_runtime() -> None:
    completed = subprocess.run(
        ["bash", str(RUNNER), "--describe", "--node", "/tmp/untrusted-node"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 78
    assert "backend_non_postgres_error=public_argument_forbidden" in completed.stderr
    assert completed.stdout == ""


def test_gate_test_environment_exposes_only_the_bound_node_parent(
    tmp_path: Path,
) -> None:
    helper = _gate_helper()
    runtime_root = tmp_path / "runtime"
    transient_paths = helper._transient_paths(runtime_root)
    uv = tmp_path / "uv-bin" / "uv"
    node = tmp_path / "node-bin" / "node"

    environment = helper._test_environment(transient_paths, uv, node)

    assert environment["PATH"].split(":") == [
        str(node.parent),
        str(transient_paths["venv"] / "bin"),
        str(uv.parent),
        "/usr/bin",
        "/bin",
    ]


def test_gate_receipt_binds_the_node_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    helper = _gate_helper()
    root = tmp_path / "repository"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    for name in (HELPER.name, RUNNER.name):
        (scripts / name).write_text(f"# {name}\n", encoding="utf-8")
    fake_uv = root / "fake-uv"
    fake_uv.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_uv.chmod(0o700)
    fake_node = root / "fake-node"
    fake_node.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_node.chmod(0o700)
    evidence_parent = tmp_path / "evidence"
    evidence_parent.mkdir(mode=0o700)
    output = evidence_parent / "gate2"
    commit = "a" * 40
    repository_identity = {
        "branch": "codex/agent-v0-2-release",
        "clean": True,
        "commit": commit,
        "git_toplevel": str(root),
        "publication_remote": "github",
        "publication_remote_url": "https://github.com/YIBOWAY/ai-quant-platform.git",
        "root": str(root),
        "tracked_tree": {},
        "tree": "b" * 40,
    }

    monkeypatch.setattr(
        helper,
        "_require_expected_commit",
        lambda _root, _commit: repository_identity,
    )
    monkeypatch.setattr(helper, "_git_identity", lambda _root: repository_identity)
    monkeypatch.setattr(helper, "_require_sandbox_exec", lambda: fake_uv)
    monkeypatch.setattr(
        helper,
        "_validate_import_probe",
        lambda document, **_kwargs: document,
    )

    def fake_run_logged(*, argv, env, name, output, **_kwargs):
        stdout = b""
        if name == "uv-version":
            stdout = b"uv 0.test\n"
        elif name == "node-version":
            stdout = b"v22.test\n"
        elif name == "uv-sync":
            python = Path(env["UV_PROJECT_ENVIRONMENT"]) / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\n", encoding="utf-8")
            python.chmod(0o700)
        elif name == "dependency-inventory":
            stdout = b"quant-system==0.1.0\n"
        elif name == "pytest-backend-non-postgres":
            stdout = b"1 passed\n"
            (output / "pytest-backend-non-postgres.junit.xml").write_bytes(
                b'<testsuite tests="1" failures="0" errors="0" skipped="0">'
                b'<testcase classname="tests.test_gate" name="test_pass"/>'
                b"</testsuite>"
            )
        return (
            subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b""),
            {"argv": list(argv), "exit_code": 0},
        )

    def fake_json_probe(*, argv, **_kwargs):
        return (
            subprocess.CompletedProcess(argv, 0, stdout=b"{}", stderr=b""),
            {"argv": list(argv), "exit_code": 0},
        )

    monkeypatch.setattr(helper, "_run_logged", fake_run_logged)
    monkeypatch.setattr(helper, "_run_json_probe", fake_json_probe)
    public_entrypoint = str(root / "scripts" / RUNNER.name)

    result = helper.run_gate(
        root=root,
        output_argument=output,
        expected_commit=commit,
        uv_argument=fake_uv,
        node_argument=fake_node,
        marker_expression="not pg and not futu_opend and not provider and not network",
        expected_skip_node_ids=(),
        public_entrypoint=public_entrypoint,
        public_argv=(
            f"--expected-commit={commit}",
            "--output-dir",
            str(output),
        ),
    )

    receipt = json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))
    assert receipt["node"]["argument"] == str(fake_node)
    assert receipt["node"]["realpath"] == str(fake_node.resolve())
    assert receipt["node"]["sha256"] == helper._sha256_file(fake_node.resolve())
    assert receipt["node"]["version"]["exit_code"] == 0
    assert str(fake_node.resolve().parent) in receipt["environment"]["tests"]["PATH"].split(
        ":"
    )
