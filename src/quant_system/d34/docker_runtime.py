"""Bounded but otherwise open Docker runtime for local D-34 research jobs."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class D34DockerRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class D34DockerConfig:
    image_ref: str
    workspace_root: Path
    platform_root: Path
    hqa_root: Path
    cache_root: Path
    env_file: Path | None = None
    timeout_seconds: int = 3600


@dataclass(frozen=True)
class D34DockerReceipt:
    contract: str
    job_id: str
    image_ref: str
    image_digest: str
    command: tuple[str, ...]
    output: dict[str, Any]
    receipt_digest: str
    repository_changes: tuple[dict[str, Any], ...] = ()


ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class D34DockerRuntime:
    def __init__(
        self,
        config: D34DockerConfig,
        *,
        process_runner: ProcessRunner = subprocess.run,
        repository_runner: ProcessRunner = subprocess.run,
    ) -> None:
        self.config = config
        self._run = process_runner
        self._run_repository = repository_runner

    def _validate(self, *, job_id: str, command: Sequence[str]) -> None:
        roots = (
            self.config.workspace_root,
            self.config.platform_root,
            self.config.hqa_root,
            self.config.cache_root,
        )
        env_file_invalid = False
        if self.config.env_file is not None:
            try:
                metadata = self.config.env_file.lstat()
                env_file_invalid = (
                    stat.S_ISLNK(metadata.st_mode)
                    or not stat.S_ISREG(metadata.st_mode)
                    or stat.S_IMODE(metadata.st_mode) != 0o600
                )
            except OSError:
                env_file_invalid = True
        if (
            not re.fullmatch(r"job-[A-Za-z0-9._:-]{1,200}", job_id)
            or not self.config.image_ref.strip()
            or not command
            or any(not isinstance(value, str) or not value for value in command)
            or not 30 <= self.config.timeout_seconds <= 86400
            or any(not Path(root).resolve().is_dir() for root in roots)
            or env_file_invalid
        ):
            raise D34DockerRuntimeError(
                "d34_docker_validation", "Docker research request is invalid"
            )

    def _image_digest(self) -> str:
        try:
            result = self._run(
                [
                    "docker",
                    "image",
                    "inspect",
                    self.config.image_ref,
                    "--format",
                    "{{.Id}}",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise D34DockerRuntimeError(
                "d34_docker_image_unavailable", "pinned D-34 image is unavailable"
            ) from exc
        digest = result.stdout.strip()
        if _IMAGE_DIGEST_RE.fullmatch(digest) is None:
            raise D34DockerRuntimeError(
                "d34_docker_image_unavailable", "D-34 image identity is invalid"
            )
        return digest

    @staticmethod
    def _process_text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def _cleanup_container(self, name: str, *, stop_first: bool) -> dict[str, object]:
        cleanup: dict[str, object] = {}
        actions = (["stop", "--time", "10", name], ["rm", "--force", name])
        for action in actions[0 if stop_first else 1 :]:
            label = str(action[0])
            try:
                completed = self._run(
                    ["docker", *action],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                cleanup[f"{label}_returncode"] = int(completed.returncode)
            except (OSError, subprocess.SubprocessError) as exc:
                cleanup[f"{label}_error"] = type(exc).__name__
        return cleanup

    def _write_failure_receipt(
        self,
        *,
        job_id: str,
        image_digest: str,
        name: str,
        command: Sequence[str],
        code: str,
        returncode: int | None,
        stdout: str | bytes | None,
        stderr: str | bytes | None,
        cleanup: dict[str, object],
        repository_changes: Sequence[dict[str, Any]],
    ) -> None:
        stdout_text = self._process_text(stdout)
        stderr_text = self._process_text(stderr)
        document = {
            "contract": "hqa.d34_docker_failure/v1",
            "job_id": job_id,
            "image_ref": self.config.image_ref,
            "image_digest": image_digest,
            "container_name": name,
            "command": list(command),
            "code": code,
            "returncode": returncode,
            "stdout_bytes": len(stdout_text.encode("utf-8")),
            "stdout_digest": hashlib.sha256(stdout_text.encode("utf-8")).hexdigest(),
            "stderr_bytes": len(stderr_text.encode("utf-8")),
            "stderr_digest": hashlib.sha256(stderr_text.encode("utf-8")).hexdigest(),
            "cleanup": cleanup,
            "repository_changes": list(repository_changes),
        }
        path = self.config.workspace_root / "jobs" / job_id / "docker_failure.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _repository_snapshot(self, *, repository: str, root: Path) -> dict[str, Any]:
        base = {
            "repository": repository,
        }
        try:
            status = self._run_repository(
                [
                    "git",
                    "-C",
                    str(root.resolve()),
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if status.returncode != 0:
                return {
                    **base,
                    "available": False,
                    "dirty": None,
                    "status": "",
                    "status_digest": _digest(""),
                    "diff": "",
                    "diff_digest": _digest(""),
                    "state_digest": _digest({"available": False}),
                }
            diff = self._run_repository(
                [
                    "git",
                    "-C",
                    str(root.resolve()),
                    "diff",
                    "--no-ext-diff",
                    "--binary",
                    "--no-color",
                    "HEAD",
                    "--",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            status_text = self._process_text(status.stdout)
            diff_text = self._process_text(diff.stdout) if diff.returncode == 0 else ""
            state_document = {
                "available": True,
                "status": status_text,
                "diff": diff_text,
            }
            return {
                **base,
                "available": True,
                "dirty": bool(status_text),
                "status": status_text,
                "status_digest": _digest(status_text),
                "diff": diff_text,
                "diff_digest": _digest(diff_text),
                "state_digest": _digest(state_document),
            }
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                **base,
                "available": False,
                "dirty": None,
                "status": "",
                "status_digest": _digest(""),
                "diff": "",
                "diff_digest": _digest(""),
                "state_digest": _digest(
                    {"available": False, "error": type(exc).__name__}
                ),
            }

    def _repository_snapshots(self) -> tuple[dict[str, Any], ...]:
        return (
            self._repository_snapshot(
                repository="platform", root=self.config.platform_root
            ),
            self._repository_snapshot(repository="hqa", root=self.config.hqa_root),
        )

    @staticmethod
    def _repository_changes(
        before: Sequence[dict[str, Any]], after: Sequence[dict[str, Any]]
    ) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "repository": before_state["repository"],
                "changed_during_job": before_state["state_digest"]
                != after_state["state_digest"],
                "before": before_state,
                "after": after_state,
            }
            for before_state, after_state in zip(before, after, strict=True)
        )

    def _write_repository_anomaly(
        self, *, job_id: str, repository_changes: Sequence[dict[str, Any]]
    ) -> None:
        changed = [
            observation
            for observation in repository_changes
            if observation["changed_during_job"]
        ]
        if not changed:
            return
        document = {
            "contract": "hqa.d34_repository_anomaly/v1",
            "job_id": job_id,
            "repositories": changed,
        }
        path = self.config.workspace_root / "jobs" / job_id / "repository_anomaly.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _json_output(stdout: str) -> dict[str, Any]:
        for line in reversed(stdout.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise D34DockerRuntimeError(
            "d34_docker_output_invalid", "D-34 container emitted no JSON receipt"
        )

    def run(self, *, job_id: str, command: Sequence[str]) -> D34DockerReceipt:
        self._validate(job_id=job_id, command=command)
        image_digest = self._image_digest()
        repositories_before = self._repository_snapshots()
        name = "hqa-d34-" + hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:20]
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--user",
            "0:0",
            "--network",
            "bridge",
            "--add-host",
            "host.docker.internal:host-gateway",
            "--volume",
            f"{self.config.workspace_root.resolve()}:/workspace/d34",
            "--volume",
            f"{self.config.platform_root.resolve()}:/workspace/platform",
            "--volume",
            f"{self.config.hqa_root.resolve()}:/workspace/hqa",
            "--volume",
            f"{self.config.cache_root.resolve()}:/workspace/cache",
            "--volume",
            "/var/run/docker.sock:/var/run/docker.sock",
            "--env",
            f"D34_IMAGE_REF={self.config.image_ref}",
        ]
        if self.config.env_file is not None:
            docker_command.extend(["--env-file", str(self.config.env_file.resolve())])
        docker_command.extend([self.config.image_ref, *command])
        try:
            completed = self._run(
                docker_command,
                capture_output=True,
                text=True,
                check=True,
                timeout=self.config.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            cleanup = self._cleanup_container(name, stop_first=True)
            repository_changes = self._repository_changes(
                repositories_before, self._repository_snapshots()
            )
            self._write_repository_anomaly(
                job_id=job_id, repository_changes=repository_changes
            )
            self._write_failure_receipt(
                job_id=job_id,
                image_digest=image_digest,
                name=name,
                command=command,
                code="d34_docker_timeout",
                returncode=None,
                stdout=exc.output,
                stderr=exc.stderr,
                cleanup=cleanup,
                repository_changes=repository_changes,
            )
            raise D34DockerRuntimeError(
                "d34_docker_timeout", "D-34 container exceeded its configured timeout"
            ) from exc
        except subprocess.CalledProcessError as exc:
            cleanup = self._cleanup_container(name, stop_first=False)
            repository_changes = self._repository_changes(
                repositories_before, self._repository_snapshots()
            )
            self._write_repository_anomaly(
                job_id=job_id, repository_changes=repository_changes
            )
            self._write_failure_receipt(
                job_id=job_id,
                image_digest=image_digest,
                name=name,
                command=command,
                code="d34_docker_failed",
                returncode=int(exc.returncode),
                stdout=exc.stdout,
                stderr=exc.stderr,
                cleanup=cleanup,
                repository_changes=repository_changes,
            )
            raise D34DockerRuntimeError(
                "d34_docker_failed", "D-34 container failed; inspect its failure receipt"
            ) from exc
        except OSError as exc:
            repository_changes = self._repository_changes(
                repositories_before, self._repository_snapshots()
            )
            self._write_repository_anomaly(
                job_id=job_id, repository_changes=repository_changes
            )
            self._write_failure_receipt(
                job_id=job_id,
                image_digest=image_digest,
                name=name,
                command=command,
                code="d34_docker_failed",
                returncode=None,
                stdout=None,
                stderr=None,
                cleanup={"docker_error": type(exc).__name__},
                repository_changes=repository_changes,
            )
            raise D34DockerRuntimeError(
                "d34_docker_failed", "D-34 container failed; inspect its failure receipt"
            ) from exc
        repository_changes = self._repository_changes(
            repositories_before, self._repository_snapshots()
        )
        self._write_repository_anomaly(
            job_id=job_id, repository_changes=repository_changes
        )
        output = self._json_output(completed.stdout)
        document = {
            "contract": "hqa.d34_docker_receipt/v1",
            "job_id": job_id,
            "image_ref": self.config.image_ref,
            "image_digest": image_digest,
            "command": list(command),
            "output": output,
            "repository_changes": list(repository_changes),
        }
        return D34DockerReceipt(
            contract="hqa.d34_docker_receipt/v1",
            job_id=job_id,
            image_ref=self.config.image_ref,
            image_digest=image_digest,
            command=tuple(command),
            output=output,
            receipt_digest=_digest(document),
            repository_changes=repository_changes,
        )


__all__ = [
    "D34DockerConfig",
    "D34DockerReceipt",
    "D34DockerRuntime",
    "D34DockerRuntimeError",
]
