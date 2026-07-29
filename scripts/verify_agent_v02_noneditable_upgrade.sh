#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "agent_v02_ops_error=python_not_executable" >&2
  exit 78
fi

BOOTSTRAP='
import hashlib
import importlib.util
import json
import os
import runpy
import stat
import subprocess
import sys
import sysconfig
import tarfile
from pathlib import Path, PurePosixPath

SANDBOX = "/usr/bin/sandbox-exec"
SANDBOX_PROFILE = "(version 1) (allow default) (deny network*)"
GIT = "/usr/bin/git"
MAX_BOOTSTRAP_BYTES = 256 * 1024 * 1024


def fail() -> None:
    print("agent_v02_ops_error=commit_bound_bootstrap_failed", file=sys.stderr)
    raise SystemExit(78)


def output_argument(arguments: list[str]) -> Path:
    values: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in {
            "--bootstrap-authority",
            "--bootstrap-authority-sha256",
        } or argument.startswith(
            (
                "--bootstrap-authority=",
                "--bootstrap-authority-sha256=",
            )
        ):
            fail()
        if argument == "--output-dir":
            if index + 1 >= len(arguments):
                fail()
            values.append(arguments[index + 1])
            index += 2
            continue
        if argument.startswith("--output-dir="):
            values.append(argument.split("=", 1)[1])
        index += 1
    if len(values) != 1 or not values[0]:
        fail()
    candidate = Path(os.path.abspath(values[0]))
    if not candidate.is_absolute():
        fail()
    return candidate


def private_directory(path: Path) -> Path:
    candidate = Path(os.path.abspath(os.fspath(path)))
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            fail()
        if current != candidate and not stat.S_ISDIR(info.st_mode):
            fail()
    candidate.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = candidate.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
    ):
        fail()
    candidate.chmod(0o700)
    return candidate


def write_exclusive(path: Path, payload: bytes) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError:
        fail()
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def git_command(root: Path, environment: dict[str, str], *arguments: str) -> bytes:
    completed = subprocess.run(
        [
            SANDBOX,
            "-p",
            SANDBOX_PROFILE,
            GIT,
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "credential.helper=",
            "-C",
            str(root),
            *arguments,
        ],
        check=False,
        capture_output=True,
        env=environment,
    )
    if completed.returncode != 0:
        fail()
    return completed.stdout


def prepare_commit_bound_source() -> tuple[Path, Path, list[str]]:
    if not sys.flags.isolated or not sys.flags.no_site or not sys.flags.ignore_environment:
        fail()
    root = Path(sys.argv[1]).resolve(strict=True)
    arguments = list(sys.argv[2:])
    output_candidate = output_argument(arguments)
    if output_candidate == root or output_candidate.is_relative_to(root):
        fail()
    output = private_directory(output_candidate)
    source_root = output / "bootstrap-source"
    archive_path = output / "bootstrap-source.tar"
    authority_path = output / "bootstrap-source-authority.json"
    if source_root.exists() or archive_path.exists() or authority_path.exists():
        fail()
    source_root.mkdir(mode=0o700)
    bootstrap_home = private_directory(output / "bootstrap-home")
    bootstrap_tmp = private_directory(output / "bootstrap-tmp")
    environment = {
        "HOME": str(bootstrap_home),
        "TMPDIR": str(bootstrap_tmp),
        "TMP": str(bootstrap_tmp),
        "TEMP": str(bootstrap_tmp),
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
    }
    commit = git_command(root, environment, "rev-parse", "--verify", "HEAD").decode(
        "ascii"
    ).strip()
    tree = git_command(
        root,
        environment,
        "rev-parse",
        "--verify",
        f"{commit}^{{tree}}",
    ).decode("ascii").strip()
    listing = git_command(
        root,
        environment,
        "ls-tree",
        "-r",
        "-z",
        commit,
        "--",
        "src/quant_system",
    )
    expected: dict[str, tuple[str, str]] = {}
    for record in listing.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_kind, object_id = metadata.split(b" ", 2)
            relative = raw_path.decode("utf-8", "strict")
        except (UnicodeDecodeError, ValueError):
            fail()
        path = PurePosixPath(relative)
        if (
            object_kind != b"blob"
            or mode not in {b"100644", b"100755"}
            or path.is_absolute()
            or "\\" in relative
            or any(part in {"", ".", ".."} for part in path.parts)
            or not relative.startswith("src/quant_system/")
            or relative in expected
        ):
            fail()
        expected[relative] = (mode.decode("ascii"), object_id.decode("ascii"))
    if not expected:
        fail()
    try:
        archive_descriptor = os.open(
            archive_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError:
        fail()
    try:
        with os.fdopen(archive_descriptor, "wb") as archive_handle:
            archive_descriptor = -1
            completed = subprocess.run(
                [
                    SANDBOX,
                    "-p",
                    SANDBOX_PROFILE,
                    GIT,
                    "--no-replace-objects",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "credential.helper=",
                    "-C",
                    str(root),
                    "archive",
                    "--format=tar",
                    commit,
                    "--",
                    "src/quant_system",
                ],
                check=False,
                stdout=archive_handle,
                stderr=subprocess.PIPE,
                env=environment,
            )
            archive_handle.flush()
            os.fsync(archive_handle.fileno())
        if completed.returncode != 0:
            fail()
    finally:
        if archive_descriptor >= 0:
            os.close(archive_descriptor)
    observed: set[str] = set()
    total_bytes = 0
    with tarfile.open(archive_path, mode="r:") as bundle:
        for member in bundle:
            relative = member.name.rstrip("/")
            path = PurePosixPath(relative)
            if (
                not relative
                or path.is_absolute()
                or "\\" in relative
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                fail()
            target = source_root.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                target.chmod(0o700)
                continue
            if not member.isfile() or relative not in expected or relative in observed:
                fail()
            extracted = bundle.extractfile(member)
            if extracted is None:
                fail()
            payload = extracted.read(MAX_BOOTSTRAP_BYTES + 1)
            total_bytes += len(payload)
            if len(payload) > MAX_BOOTSTRAP_BYTES or total_bytes > MAX_BOOTSTRAP_BYTES:
                fail()
            mode, object_id = expected[relative]
            algorithm = hashlib.sha1 if len(object_id) == 40 else hashlib.sha256
            git_blob = algorithm(
                b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
            ).hexdigest()
            if git_blob != object_id:
                fail()
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.parent.chmod(0o700)
            write_exclusive(target, payload)
            target.chmod(0o700 if mode == "100755" else 0o600)
            observed.add(relative)
    if observed != set(expected):
        fail()
    head_after_archive = git_command(
        root,
        environment,
        "rev-parse",
        "--verify",
        "HEAD",
    ).decode("ascii").strip()
    if head_after_archive != commit:
        fail()
    source = (source_root / "src").resolve(strict=True)
    expected_release = (
        source / "quant_system" / "ops" / "release_ops.py"
    ).resolve(strict=True)
    expected_upgrade = (
        source / "quant_system" / "ops" / "noneditable_upgrade.py"
    ).resolve(strict=True)
    if (
        not expected_release.is_file()
        or not expected_upgrade.is_file()
        or not expected_release.is_relative_to(source)
        or not expected_upgrade.is_relative_to(source)
    ):
        fail()
    archive_digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    source_manifest = [
        {
            "mode": expected[path][0],
            "object_id": expected[path][1],
            "path": path,
        }
        for path in sorted(expected)
    ]
    authority = {
        "archive_sha256": archive_digest,
        "commit": commit,
        "file_count": len(observed),
        "noneditable_upgrade_sha256": hashlib.sha256(
            expected_upgrade.read_bytes()
        ).hexdigest(),
        "release_ops_sha256": hashlib.sha256(expected_release.read_bytes()).hexdigest(),
        "repository_root": str(root),
        "schema_version": "agent-v0.2.2-commit-bound-bootstrap.v2",
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(
                source_manifest,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "source_root": str(source),
        "tree": tree,
    }
    authority_payload = json.dumps(
        authority,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    write_exclusive(
        authority_path,
        authority_payload,
    )
    environment_root = (root / ".venv").resolve(strict=True)
    site_packages = Path(
        sysconfig.get_path(
            "purelib",
            vars={"base": str(environment_root), "platbase": str(environment_root)},
        )
    ).resolve(strict=True)
    if not site_packages.is_dir() or not site_packages.is_relative_to(environment_root):
        fail()
    return (
        source,
        site_packages,
        [
            *arguments,
            "--bootstrap-authority",
            str(authority_path),
            "--bootstrap-authority-sha256",
            hashlib.sha256(authority_payload).hexdigest(),
        ],
    )


try:
    source, site_packages, release_arguments = prepare_commit_bound_source()
except SystemExit:
    raise
except BaseException:
    fail()
expected = (source / "quant_system" / "ops" / "release_ops.py").resolve(strict=True)
sys.path[:0] = [str(source), str(site_packages)]
spec = importlib.util.find_spec("quant_system.ops.release_ops")
if spec is None or spec.origin is None or Path(spec.origin).resolve() != expected:
    fail()
sys.argv = [str(expected), *release_arguments]
runpy.run_module("quant_system.ops.release_ops", run_name="__main__")
'

exec "$PYTHON" "-I" "-S" "-B" -c "$BOOTSTRAP" "$ROOT" noneditable-upgrade \
  "$@" \
  --repository-root "$ROOT"
