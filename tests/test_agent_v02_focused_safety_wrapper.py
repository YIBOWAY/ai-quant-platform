from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_agent_v02_focused_safety.sh"
SELECTORS = (
    "tests/test_api_safety.py",
    "tests/test_frontend_paper_replay_safety.py",
    "tests/test_hermes_effective_release_gate.py",
    "tests/test_hermes_release_authority.py",
    "tests/test_release_authority_hardening.py",
    "tests/test_release_authority_projection.py",
    "tests/test_command_approval_decide.py",
    "tests/test_approval_release_v7b.py",
    "tests/test_approval_observe_v7d.py",
    "tests/test_production_run_control_saga.py",
    "tests/test_agent_v02_zero_effect_hardening.py",
    "tests/test_agent_v02_restart_live_settings.py",
    "tests/test_agent_v02_restart_release_authority.py",
    "tests/test_gate_surfaces_v7e.py",
    "tests/test_paper_gate_authority.py",
    "tests/test_paper_run_attestation.py",
    "tests/test_api_paper.py",
    "tests/test_hermes_run_control_client.py",
    "tests/test_zero_effect_switch_scope.py",
    "tests/test_zero_effect_switch_independence.py",
)


def _release_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    assert SCRIPT.is_file(), "focused-safety wrapper is absent"
    release = tmp_path / "release"
    scripts = release / "scripts"
    scripts.mkdir(parents=True)
    wrapper = scripts / SCRIPT.name
    shutil.copy2(SCRIPT, wrapper)
    wrapper.chmod(0o755)
    for selector in SELECTORS:
        target = release / selector
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# selector fixture\n", encoding="utf-8")

    capture = tmp_path / "capture.txt"
    python = release / ".venv" / "fresh" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        "{\n"
        '  printf "PWD=%s\\n" "$PWD"\n'
        '  for argument in "$@"; do\n'
        '    printf "ARG=%s\\n" "$argument"\n'
        "  done\n"
        f"}} > {shlex.quote(str(capture))}\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return wrapper, python, capture


def _invoke(
    wrapper: Path,
    python: Path | str,
    basetemp: Path | str,
    *extra_arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            str(wrapper),
            "--python",
            str(python),
            "--basetemp",
            str(basetemp),
            *extra_arguments,
        ),
        check=False,
        capture_output=True,
        text=True,
    )


def test_focused_safety_wrapper_executes_the_exact_closed_selector_set(
    tmp_path: Path,
) -> None:
    wrapper, python, capture = _release_fixture(tmp_path)
    basetemp = tmp_path / "focused-safety-basetemp"

    completed = _invoke(wrapper, python, basetemp)

    assert completed.returncode == 0, completed.stderr
    lines = capture.read_text(encoding="utf-8").splitlines()
    assert lines[0] == f"PWD={wrapper.parents[1]}"
    assert lines[1:] == [
        "ARG=-m",
        "ARG=pytest",
        "ARG=-q",
        f"ARG=--basetemp={basetemp}",
        *(f"ARG={selector}" for selector in SELECTORS),
    ]


def test_focused_safety_wrapper_rejects_selector_and_pytest_passthrough(
    tmp_path: Path,
) -> None:
    substitutions = (
        ("tests/test_api_safety.py::test_substituted_selector",),
        ("-k", "safety"),
        ("--ignore=tests/test_hermes_release_authority.py",),
    )

    for index, extra_arguments in enumerate(substitutions):
        case_root = tmp_path / f"case-{index}"
        wrapper, python, capture = _release_fixture(case_root)
        basetemp = case_root / "focused-safety-basetemp"

        completed = _invoke(
            wrapper,
            python,
            basetemp,
            *extra_arguments,
        )

        assert completed.returncode == 78
        assert "focused_safety_arguments_invalid" in completed.stderr
        assert not capture.exists()


def test_focused_safety_wrapper_rejects_selector_symlink_substitution(
    tmp_path: Path,
) -> None:
    wrapper, python, capture = _release_fixture(tmp_path)
    substituted_selector = wrapper.parents[1] / SELECTORS[0]
    replacement = tmp_path / "replacement-selector.py"
    replacement.write_text("# substituted selector\n", encoding="utf-8")
    substituted_selector.unlink()
    substituted_selector.symlink_to(replacement)

    completed = _invoke(
        wrapper,
        python,
        tmp_path / "focused-safety-basetemp",
    )

    assert completed.returncode == 78
    assert "focused_safety_selector_unsafe" in completed.stderr
    assert not capture.exists()


def test_focused_safety_wrapper_rejects_symlinked_authority_inputs(
    tmp_path: Path,
) -> None:
    cases: list[tuple[str, str]] = []

    wrapper_root = tmp_path / "wrapper"
    wrapper, python, capture = _release_fixture(wrapper_root)
    real_wrapper = wrapper.with_name(f"{wrapper.name}.real")
    wrapper.rename(real_wrapper)
    wrapper.symlink_to(real_wrapper.name)
    completed = _invoke(
        wrapper,
        python,
        wrapper_root / "focused-safety-basetemp",
    )
    cases.append(("wrapper", completed.stderr))
    assert completed.returncode == 78
    assert not capture.exists()

    python_root = tmp_path / "python"
    wrapper, python, capture = _release_fixture(python_root)
    real_python = python_root / "real-python"
    python.rename(real_python)
    python.symlink_to(real_python)
    completed = _invoke(
        wrapper,
        python,
        python_root / "focused-safety-basetemp",
    )
    cases.append(("python", completed.stderr))
    assert completed.returncode == 78
    assert not capture.exists()

    basetemp_root = tmp_path / "basetemp"
    wrapper, python, capture = _release_fixture(basetemp_root)
    real_basetemp = basetemp_root / "real-basetemp"
    real_basetemp.mkdir(mode=0o700)
    basetemp = basetemp_root / "focused-safety-basetemp"
    basetemp.symlink_to(real_basetemp, target_is_directory=True)
    completed = _invoke(wrapper, python, basetemp)
    cases.append(("basetemp", completed.stderr))
    assert completed.returncode == 78
    assert not capture.exists()

    assert {name for name, _ in cases} == {"wrapper", "python", "basetemp"}
    assert all("agent_v02_ops_error=" in stderr for _, stderr in cases)


def test_focused_safety_wrapper_rejects_group_or_world_writable_inputs(
    tmp_path: Path,
) -> None:
    unsafe_cases: list[tuple[Path, Path, Path]] = []

    wrapper_root = tmp_path / "wrapper"
    wrapper, python, capture = _release_fixture(wrapper_root)
    wrapper.chmod(0o775)
    unsafe_cases.append((wrapper, python, capture))

    python_root = tmp_path / "python"
    wrapper, python, capture = _release_fixture(python_root)
    python.chmod(0o775)
    unsafe_cases.append((wrapper, python, capture))

    selector_root = tmp_path / "selector"
    wrapper, python, capture = _release_fixture(selector_root)
    (wrapper.parents[1] / SELECTORS[0]).chmod(0o666)
    unsafe_cases.append((wrapper, python, capture))

    for wrapper, python, capture in unsafe_cases:
        completed = _invoke(
            wrapper,
            python,
            wrapper.parents[2] / "focused-safety-basetemp",
        )
        assert completed.returncode == 78
        assert "unsafe_mode" in completed.stderr
        assert not capture.exists()

    basetemp_root = tmp_path / "basetemp"
    wrapper, python, capture = _release_fixture(basetemp_root)
    basetemp = basetemp_root / "focused-safety-basetemp"
    basetemp.mkdir(mode=0o700)
    basetemp.chmod(0o777)
    completed = _invoke(wrapper, python, basetemp)
    assert completed.returncode == 78
    assert "unsafe_mode" in completed.stderr
    assert not capture.exists()


def test_focused_safety_wrapper_rejects_noncanonical_and_boundary_paths(
    tmp_path: Path,
) -> None:
    python_root = tmp_path / "python"
    wrapper, python, capture = _release_fixture(python_root)
    aliased_python = python.parent / ".." / "bin" / "python"
    completed = _invoke(
        wrapper,
        aliased_python,
        python_root / "focused-safety-basetemp",
    )
    assert completed.returncode == 78
    assert "path_not_canonical" in completed.stderr
    assert not capture.exists()

    outside_python_root = tmp_path / "outside-python"
    wrapper, python, capture = _release_fixture(outside_python_root)
    external_python = outside_python_root / "python"
    shutil.copy2(python, external_python)
    completed = _invoke(
        wrapper,
        external_python,
        outside_python_root / "focused-safety-basetemp",
    )
    assert completed.returncode == 78
    assert "python_must_be_release_local" in completed.stderr
    assert not capture.exists()

    basetemp_root = tmp_path / "basetemp"
    wrapper, python, capture = _release_fixture(basetemp_root)
    completed = _invoke(
        wrapper,
        python,
        wrapper.parents[1] / "inside-release-basetemp",
    )
    assert completed.returncode == 78
    assert "basetemp_must_be_outside_release_checkout" in completed.stderr
    assert not capture.exists()

    relative_root = tmp_path / "relative"
    wrapper, python, capture = _release_fixture(relative_root)
    completed = _invoke(wrapper, python, "relative-basetemp")
    assert completed.returncode == 78
    assert "path_not_canonical" in completed.stderr
    assert not capture.exists()
