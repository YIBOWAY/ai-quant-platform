"""Owned, local-image-only disposable PostgreSQL 16 container."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo

from quant_system.ops.common import ReleaseOperationError, ensure_private_directory

POSTGRES_IMAGE = "postgres:16-alpine"
POSTGRES_PGDATA = "/var/lib/postgresql/data"
OWNER_LABEL = "com.yiboway.agent-v02.owner"
CONTAINER_LABEL = "com.yiboway.agent-v02.container"
VOLUME_LABEL = "com.yiboway.agent-v02.volume"
OWNER_LABEL_VALUE = "v0.2.2-hardening"


class ReleaseOperationInterrupted(Exception):
    """Catchable operator termination deferred until exact PG cleanup finishes."""

    def __init__(self, signum: int) -> None:
        super().__init__(f"release operation interrupted by signal {signum}")
        self.signum = signum


def _inspect_proves_absence(
    completed: subprocess.CompletedProcess[str],
    *,
    resource_kind: str,
    resource_name: str,
) -> bool:
    """Accept only an exact, name-bound Docker not-found observation."""

    expected_errors = {
        "container": (
            f"Error: No such object: {resource_name}\n",
            f"error: no such object: {resource_name}\n",
        ),
        "volume": (
            f"Error response from daemon: get {resource_name}: no such volume\n",
            f"Error: No such volume: {resource_name}\n",
        ),
    }
    errors = expected_errors.get(resource_kind)
    if errors is None:
        raise ReleaseOperationError("Docker inspect resource kind is invalid")
    if completed.returncode == 1 and completed.stdout == "[]\n" and completed.stderr in errors:
        return True
    raise ReleaseOperationError(
        f"{resource_kind} inspect failed without exact name-bound absence proof"
    )


def owned_process_environment(
    root: Path,
    *,
    docker_host: str | None = None,
) -> dict[str, str]:
    """Return a minimal environment whose writable paths are evidence-owned."""

    process_root = ensure_private_directory(root)
    paths = {
        "HOME": process_root / "home",
        "TMPDIR": process_root / "tmp",
        "TMP": process_root / "tmp",
        "TEMP": process_root / "tmp",
        "XDG_CACHE_HOME": process_root / "cache" / "xdg",
        "PIP_CACHE_DIR": process_root / "cache" / "pip",
        "UV_CACHE_DIR": process_root / "cache" / "uv",
        "PYTHONPYCACHEPREFIX": process_root / "cache" / "python",
    }
    env = {
        name: os.environ[name] for name in ("LANG", "LC_ALL", "TZ", "USER") if name in os.environ
    }
    env["PATH"] = os.environ.get("PATH", os.defpath)
    for name, path in paths.items():
        env[name] = str(ensure_private_directory(path))
    if docker_host is not None:
        if not docker_host.startswith("unix:///") or "\n" in docker_host:
            raise ReleaseOperationError("Docker host must be an absolute local unix socket")
        env["DOCKER_HOST"] = docker_host
    return env


def _configured_docker_endpoint() -> tuple[str, str]:
    explicit_host = os.environ.get("DOCKER_HOST")
    if explicit_host:
        return "environment:DOCKER_HOST", explicit_host
    home = os.environ.get("HOME")
    docker_config = os.environ.get("DOCKER_CONFIG")
    if docker_config:
        config_root = Path(docker_config)
    elif home:
        config_root = Path(home) / ".docker"
    else:
        raise ReleaseOperationError("Docker configuration root is unavailable")
    context_name = os.environ.get("DOCKER_CONTEXT")
    if not context_name:
        config_path = config_root / "config.json"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseOperationError("Docker configuration is unreadable") from exc
        configured = config.get("currentContext", "default")
        if not isinstance(configured, str):
            raise ReleaseOperationError("Docker current context is malformed")
        context_name = configured or "default"
    if context_name == "default":
        return context_name, "unix:///var/run/docker.sock"
    metadata_path = (
        config_root
        / "contexts"
        / "meta"
        / hashlib.sha256(context_name.encode("utf-8")).hexdigest()
        / "meta.json"
    )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        endpoint = metadata["Endpoints"]["docker"]["Host"]
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise ReleaseOperationError("Docker context endpoint is unreadable") from exc
    if not isinstance(endpoint, str):
        raise ReleaseOperationError("Docker context endpoint is malformed")
    return context_name, endpoint


@dataclass(frozen=True)
class DockerDaemonIdentity:
    context: str
    endpoint: str
    socket_path: str
    socket_device: int
    socket_inode: int
    daemon_id: str
    server_version: str
    operating_system: str


def resolve_local_docker_daemon(
    *,
    docker: str,
    process_root: Path,
) -> tuple[DockerDaemonIdentity, dict[str, str]]:
    """Bind Docker commands to one verified local unix socket and daemon."""

    context, configured_endpoint = _configured_docker_endpoint()
    if (
        not configured_endpoint.startswith("unix:///")
        or "\n" in configured_endpoint
        or "\r" in configured_endpoint
    ):
        raise ReleaseOperationError("Docker daemon must use a local unix socket")
    configured_socket = Path(configured_endpoint.removeprefix("unix://"))
    try:
        socket_path = configured_socket.resolve(strict=True)
        socket_info = socket_path.stat()
    except OSError as exc:
        raise ReleaseOperationError("Docker unix socket is unavailable") from exc
    if not stat.S_ISSOCK(socket_info.st_mode):
        raise ReleaseOperationError("Docker daemon endpoint is not a unix socket")
    endpoint = f"unix://{socket_path}"
    env = owned_process_environment(process_root, docker_host=endpoint)
    info = subprocess.run(
        [
            docker,
            "info",
            "--format",
            "{{json .ID}}|{{json .ServerVersion}}|{{json .OperatingSystem}}",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if info.returncode != 0:
        raise ReleaseOperationError("bound local Docker daemon is unavailable")
    try:
        parts = [json.loads(value) for value in info.stdout.strip().split("|")]
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("Docker daemon identity is malformed") from exc
    if len(parts) != 3 or not all(isinstance(value, str) and value for value in parts):
        raise ReleaseOperationError("Docker daemon identity is incomplete")
    identity = DockerDaemonIdentity(
        context=context,
        endpoint=endpoint,
        socket_path=str(socket_path),
        socket_device=socket_info.st_dev,
        socket_inode=socket_info.st_ino,
        daemon_id=parts[0],
        server_version=parts[1],
        operating_system=parts[2],
    )
    return identity, env


@dataclass(frozen=True)
class ContainerIdentity:
    name: str
    image: str
    image_id: str
    host: str
    host_port: int
    database: str
    user: str
    volume_name: str
    volume_driver: str
    volume_labels: dict[str, str]
    pgdata_mount: dict[str, object]
    anonymous_volume_count: int
    docker_daemon: DockerDaemonIdentity


class DisposablePostgresContainer:
    """Create one random loopback PostgreSQL container and remove it explicitly."""

    def __init__(self, *, process_root: Path) -> None:
        token = uuid4().hex[:12]
        self.name = f"agent-v02-pg-{token}-tmp"
        self.volume_name = f"{self.name}-data"
        self.database = f"agent_v02_admin_{token}_tmp"
        self.user = "agent_v02_admin"
        self._password = secrets.token_urlsafe(32)
        self._docker = shutil.which("docker")
        self._process_root = ensure_private_directory(process_root)
        self._docker_env: dict[str, str] | None = None
        self._daemon_identity: DockerDaemonIdentity | None = None
        self._started = False
        self._image_id: str | None = None
        self._identity: ContainerIdentity | None = None
        self._cleanup_facts: dict[str, object] | None = None

    def _require_docker(self) -> str:
        if not self._docker:
            raise ReleaseOperationError("docker is unavailable")
        return self._docker

    def _expected_volume_labels(self) -> dict[str, str]:
        return {
            OWNER_LABEL: OWNER_LABEL_VALUE,
            CONTAINER_LABEL: self.name,
        }

    def _expected_container_labels(self) -> dict[str, str]:
        return {
            OWNER_LABEL: OWNER_LABEL_VALUE,
            VOLUME_LABEL: self.volume_name,
        }

    def _inspect_owned_volume(self) -> bool:
        docker = self._require_docker()
        if self._docker_env is None:
            raise ReleaseOperationError("Docker daemon identity is unresolved")
        inspected = subprocess.run(
            [docker, "volume", "inspect", self.volume_name],
            check=False,
            capture_output=True,
            text=True,
            env=self._docker_env,
        )
        if inspected.returncode != 0:
            _inspect_proves_absence(
                inspected,
                resource_kind="volume",
                resource_name=self.volume_name,
            )
            return False
        if inspected.stderr:
            raise ReleaseOperationError("owned PostgreSQL data volume inspect wrote stderr")
        try:
            document = json.loads(inspected.stdout)
            volume = document[0]
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ReleaseOperationError(
                "owned PostgreSQL data volume identity is malformed"
            ) from exc
        if (
            not isinstance(volume, dict)
            or volume.get("Name") != self.volume_name
            or volume.get("Driver") != "local"
            or volume.get("Labels") != self._expected_volume_labels()
            or volume.get("Scope") not in (None, "local")
        ):
            raise ReleaseOperationError("owned PostgreSQL data volume identity mismatch")
        return True

    def _inspect_owned_container(
        self,
        *,
        require_exact_pgdata_mount: bool,
    ) -> dict[str, object] | None:
        docker = self._require_docker()
        if self._docker_env is None:
            raise ReleaseOperationError("Docker daemon identity is unresolved")
        inspected = subprocess.run(
            [docker, "inspect", self.name],
            check=False,
            capture_output=True,
            text=True,
            env=self._docker_env,
        )
        if inspected.returncode != 0:
            _inspect_proves_absence(
                inspected,
                resource_kind="container",
                resource_name=self.name,
            )
            return None
        if inspected.stderr:
            raise ReleaseOperationError("disposable PostgreSQL container inspect wrote stderr")
        try:
            document = json.loads(inspected.stdout)
            container = document[0]
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ReleaseOperationError(
                "disposable PostgreSQL container identity is malformed"
            ) from exc
        if not isinstance(container, dict):
            raise ReleaseOperationError("disposable PostgreSQL container identity is malformed")
        config = container.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        expected_labels = self._expected_container_labels()
        if (
            container.get("Name") != f"/{self.name}"
            or (self._image_id is not None and container.get("Image") != self._image_id)
            or not isinstance(labels, dict)
            or any(labels.get(key) != value for key, value in expected_labels.items())
        ):
            raise ReleaseOperationError("disposable PostgreSQL container ownership mismatch")
        if not require_exact_pgdata_mount:
            return {}
        mounts = container.get("Mounts")
        if not isinstance(mounts, list):
            raise ReleaseOperationError("disposable PostgreSQL container mounts are malformed")
        expected_mount = {
            "Type": "volume",
            "Name": self.volume_name,
            "Driver": "local",
            "Destination": POSTGRES_PGDATA,
            "RW": True,
        }
        if any(not isinstance(mount, dict) for mount in mounts):
            raise ReleaseOperationError("disposable PostgreSQL container mounts are malformed")
        normalized_mounts = [
            {
                "Type": mount.get("Type"),
                "Name": mount.get("Name"),
                "Driver": mount.get("Driver"),
                "Destination": mount.get("Destination"),
                "RW": mount.get("RW"),
            }
            for mount in mounts
        ]
        if require_exact_pgdata_mount and normalized_mounts != [expected_mount]:
            raise ReleaseOperationError(
                "disposable PostgreSQL container does not have the exact named PGDATA mount"
            )
        return expected_mount

    def start(self) -> ContainerIdentity:
        """Acquire the disposable cluster and unwind any partial acquisition."""

        try:
            return self._start()
        except BaseException:
            if self._docker_env is not None:
                try:
                    self.stop()
                except ReleaseOperationInterrupted:
                    raise
                except BaseException as cleanup_error:
                    raise ReleaseOperationError(
                        "failed to clean up partial disposable PostgreSQL acquisition"
                    ) from cleanup_error
            raise

    def _start(self) -> ContainerIdentity:
        docker = self._require_docker()
        if self._started:
            raise ReleaseOperationError("disposable PostgreSQL container already started")
        daemon_identity, docker_env = resolve_local_docker_daemon(
            docker=docker,
            process_root=self._process_root,
        )
        self._daemon_identity = daemon_identity
        self._docker_env = docker_env
        volume_labels = self._expected_volume_labels()
        volume_create = subprocess.run(
            [
                docker,
                "volume",
                "create",
                "--driver",
                "local",
                "--label",
                f"{OWNER_LABEL}={OWNER_LABEL_VALUE}",
                "--label",
                f"{CONTAINER_LABEL}={self.name}",
                self.volume_name,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=docker_env,
        )
        if volume_create.returncode != 0 or volume_create.stdout.strip() != self.volume_name:
            raise ReleaseOperationError("failed to create owned PostgreSQL data volume")
        volume_inspect = subprocess.run(
            [docker, "volume", "inspect", self.volume_name],
            check=False,
            capture_output=True,
            text=True,
            env=docker_env,
        )
        try:
            volume_document = json.loads(volume_inspect.stdout)
            volume = volume_document[0]
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self.stop()
            raise ReleaseOperationError(
                "owned PostgreSQL data volume identity is malformed"
            ) from exc
        if (
            not isinstance(volume, dict)
            or volume_inspect.returncode != 0
            or volume.get("Name") != self.volume_name
            or volume.get("Driver") != "local"
            or volume.get("Labels") != volume_labels
            or volume.get("Scope") not in (None, "local")
        ):
            self.stop()
            raise ReleaseOperationError("owned PostgreSQL data volume identity mismatch")
        image = subprocess.run(
            [docker, "image", "inspect", "--format", "{{.Id}}", POSTGRES_IMAGE],
            check=False,
            capture_output=True,
            text=True,
            env=docker_env,
        )
        if image.returncode != 0 or not image.stdout.strip().startswith("sha256:"):
            raise ReleaseOperationError(
                "local postgres:16-alpine image is absent; network pull is forbidden"
            )
        self._image_id = image.stdout.strip()
        env = dict(docker_env)
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
                "--label",
                f"{OWNER_LABEL}={OWNER_LABEL_VALUE}",
                "--label",
                f"{VOLUME_LABEL}={self.volume_name}",
                "--mount",
                f"type=volume,source={self.volume_name},target={POSTGRES_PGDATA}",
                "--publish",
                "127.0.0.1::5432",
                "--env",
                "POSTGRES_PASSWORD",
                "--env",
                "POSTGRES_USER",
                "--env",
                "POSTGRES_DB",
                self._image_id,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        if run.returncode != 0:
            raise ReleaseOperationError("failed to start disposable PostgreSQL container")
        self._started = True
        pgdata_mount = self._inspect_owned_container(require_exact_pgdata_mount=True)
        if pgdata_mount is None:
            raise ReleaseOperationError("disposable PostgreSQL container disappeared after start")
        port_result = subprocess.run(
            [docker, "port", self.name, "5432/tcp"],
            check=False,
            capture_output=True,
            text=True,
            env=docker_env,
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
            volume_name=self.volume_name,
            volume_driver="local",
            volume_labels=volume_labels,
            pgdata_mount=pgdata_mount,
            anonymous_volume_count=0,
            docker_daemon=daemon_identity,
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

    @property
    def docker_environment(self) -> dict[str, str]:
        if self._docker_env is None:
            raise ReleaseOperationError("Docker daemon identity is unresolved")
        return dict(self._docker_env)

    @property
    def cleanup_facts(self) -> dict[str, object]:
        if self._cleanup_facts is None:
            raise ReleaseOperationError("disposable PostgreSQL cleanup is not proven")
        return dict(self._cleanup_facts)

    def stop(self) -> None:
        """Remove exact owned resources, deferring one caught signal until done."""

        try:
            self._stop_once()
        except ReleaseOperationInterrupted as interrupted:
            try:
                self._stop_once()
            except BaseException as cleanup_error:
                raise ReleaseOperationError(
                    "disposable PostgreSQL cleanup failed after signal interruption"
                ) from cleanup_error
            raise interrupted

    def _stop_once(self) -> None:
        if self._cleanup_facts is not None:
            return
        if self._docker_env is None:
            return
        docker = self._require_docker()

        container_present = (
            self._inspect_owned_container(require_exact_pgdata_mount=False) is not None
        )
        container_remove_attempted = False
        container_remove_exit: int | None = None
        if container_present:
            container_remove_attempted = True
            container_remove = subprocess.run(
                [docker, "rm", "--force", "--volumes", self.name],
                check=False,
                capture_output=True,
                text=True,
                env=self._docker_env,
            )
            container_remove_exit = container_remove.returncode
        container_absent = self._inspect_owned_container(require_exact_pgdata_mount=False) is None
        container_removed = container_absent and (
            not container_remove_attempted or container_remove_exit == 0
        )

        volume_present = self._inspect_owned_volume()
        volume_remove_attempted = False
        volume_remove_exit: int | None = None
        if volume_present and container_absent:
            volume_remove_attempted = True
            volume_remove = subprocess.run(
                [docker, "volume", "rm", self.volume_name],
                check=False,
                capture_output=True,
                text=True,
                env=self._docker_env,
            )
            volume_remove_exit = volume_remove.returncode
        volume_absent = not self._inspect_owned_volume()
        volume_removed = volume_absent and (not volume_remove_attempted or volume_remove_exit == 0)

        if not container_removed:
            raise ReleaseOperationError("failed to remove disposable PostgreSQL container")
        if not volume_removed:
            raise ReleaseOperationError("failed to remove owned PostgreSQL data volume")
        self._started = False
        self._cleanup_facts = {
            "container_name": self.name,
            "container_removed": True,
            "container_absent_after_remove": True,
            "container_remove_included_volumes": container_remove_attempted,
            "volume_name": self.volume_name,
            "volume_removed": True,
            "volume_absent_after_remove": True,
        }

    def __enter__(self) -> DisposablePostgresContainer:
        self.start()
        return self

    def __exit__(self, _kind, _value, _traceback) -> None:
        self.stop()
