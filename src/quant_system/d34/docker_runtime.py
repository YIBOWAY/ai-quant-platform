"""Bounded but otherwise open Docker runtime for local D-34 research jobs."""

from __future__ import annotations

import hashlib
import json
import re
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
    ) -> None:
        self.config = config
        self._run = process_runner

    def _validate(self, *, job_id: str, command: Sequence[str]) -> None:
        roots = (
            self.config.workspace_root,
            self.config.platform_root,
            self.config.hqa_root,
            self.config.cache_root,
        )
        if (
            not re.fullmatch(r"job-[A-Za-z0-9._:-]{1,200}", job_id)
            or not self.config.image_ref.strip()
            or not command
            or any(not isinstance(value, str) or not value for value in command)
            or not 30 <= self.config.timeout_seconds <= 86400
            or any(not Path(root).resolve().is_dir() for root in roots)
            or (
                self.config.env_file is not None
                and not self.config.env_file.resolve().is_file()
            )
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
            subprocess.run(
                ["docker", "stop", "--time", "10", name],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            subprocess.run(
                ["docker", "rm", "--force", name],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            raise D34DockerRuntimeError(
                "d34_docker_timeout", "D-34 container exceeded its configured timeout"
            ) from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            raise D34DockerRuntimeError(
                "d34_docker_failed", "D-34 container failed; inspect job stderr"
            ) from exc
        output = self._json_output(completed.stdout)
        document = {
            "contract": "hqa.d34_docker_receipt/v1",
            "job_id": job_id,
            "image_ref": self.config.image_ref,
            "image_digest": image_digest,
            "command": list(command),
            "output": output,
        }
        return D34DockerReceipt(
            contract="hqa.d34_docker_receipt/v1",
            job_id=job_id,
            image_ref=self.config.image_ref,
            image_digest=image_digest,
            command=tuple(command),
            output=output,
            receipt_digest=_digest(document),
        )


__all__ = [
    "D34DockerConfig",
    "D34DockerReceipt",
    "D34DockerRuntime",
    "D34DockerRuntimeError",
]
