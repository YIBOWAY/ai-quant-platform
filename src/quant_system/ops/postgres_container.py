"""Owned, local-image-only disposable PostgreSQL 16 container."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo

from quant_system.ops.common import ReleaseOperationError

POSTGRES_IMAGE = "postgres:16-alpine"


def _docker_environment() -> dict[str, str]:
    return {
        name: os.environ[name]
        for name in ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR", "TZ", "USER")
        if name in os.environ
    }


@dataclass(frozen=True)
class ContainerIdentity:
    name: str
    image: str
    image_id: str
    host: str
    host_port: int
    database: str
    user: str


class DisposablePostgresContainer:
    """Create one random loopback PostgreSQL container and remove it explicitly."""

    def __init__(self) -> None:
        token = uuid4().hex[:12]
        self.name = f"agent-v02-pg-{token}-tmp"
        self.database = f"agent_v02_admin_{token}_tmp"
        self.user = "agent_v02_admin"
        self._password = secrets.token_urlsafe(32)
        self._docker = shutil.which("docker")
        self._started = False
        self._identity: ContainerIdentity | None = None

    def _require_docker(self) -> str:
        if not self._docker:
            raise ReleaseOperationError("docker is unavailable")
        return self._docker

    def start(self) -> ContainerIdentity:
        docker = self._require_docker()
        if self._started:
            raise ReleaseOperationError("disposable PostgreSQL container already started")
        image = subprocess.run(
            [docker, "image", "inspect", "--format", "{{.Id}}", POSTGRES_IMAGE],
            check=False,
            capture_output=True,
            text=True,
            env=_docker_environment(),
        )
        if image.returncode != 0 or not image.stdout.strip().startswith("sha256:"):
            raise ReleaseOperationError(
                "local postgres:16-alpine image is absent; network pull is forbidden"
            )
        env = _docker_environment()
        env.update(
            {
                "POSTGRES_PASSWORD": self._password,
                "POSTGRES_USER": self.user,
                "POSTGRES_DB": self.database,
            }
        )
        run = subprocess.run(
            [
                docker,
                "run",
                "--detach",
                "--pull=never",
                "--name",
                self.name,
                "--publish",
                "127.0.0.1::5432",
                "--env",
                "POSTGRES_PASSWORD",
                "--env",
                "POSTGRES_USER",
                "--env",
                "POSTGRES_DB",
                POSTGRES_IMAGE,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        if run.returncode != 0:
            raise ReleaseOperationError("failed to start disposable PostgreSQL container")
        self._started = True
        port_result = subprocess.run(
            [docker, "port", self.name, "5432/tcp"],
            check=False,
            capture_output=True,
            text=True,
            env=_docker_environment(),
        )
        match = re.fullmatch(r"127\.0\.0\.1:(\d+)\s*", port_result.stdout)
        if port_result.returncode != 0 or match is None:
            self.stop()
            raise ReleaseOperationError("disposable PostgreSQL port is not loopback")
        port = int(match.group(1))
        identity = ContainerIdentity(
            name=self.name,
            image=POSTGRES_IMAGE,
            image_id=image.stdout.strip(),
            host="127.0.0.1",
            host_port=port,
            database=self.database,
            user=self.user,
        )
        self._identity = identity
        deadline = time.monotonic() + 30
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(self.url, connect_timeout=1, autocommit=True) as conn:
                    row = conn.execute(
                        "SELECT current_database(), current_user, version()"
                    ).fetchone()
                    if row is None or row[0] != self.database or row[1] != self.user:
                        raise ReleaseOperationError("disposable PostgreSQL identity mismatch")
                return identity
            except (psycopg.Error, ReleaseOperationError) as exc:
                last_error = exc
                time.sleep(0.25)
        self.stop()
        raise ReleaseOperationError("disposable PostgreSQL did not become ready") from last_error

    @property
    def url(self) -> str:
        identity = self._identity
        if identity is None:
            raise ReleaseOperationError("disposable PostgreSQL container is not started")
        return make_conninfo(
            host=identity.host,
            port=identity.host_port,
            user=identity.user,
            password=self._password,
            dbname=identity.database,
        )

    def stop(self) -> None:
        if not self._started:
            return
        docker = self._require_docker()
        remove = subprocess.run(
            [docker, "rm", "--force", self.name],
            check=False,
            capture_output=True,
            text=True,
            env=_docker_environment(),
        )
        if remove.returncode != 0:
            raise ReleaseOperationError("failed to remove disposable PostgreSQL container")
        remains = subprocess.run(
            [docker, "inspect", self.name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_docker_environment(),
        )
        if remains.returncode == 0:
            raise ReleaseOperationError("disposable PostgreSQL container still exists")
        self._started = False

    def __enter__(self) -> DisposablePostgresContainer:
        self.start()
        return self

    def __exit__(self, _kind, _value, _traceback) -> None:
        self.stop()
