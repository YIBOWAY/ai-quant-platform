from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_system.ops import postgres_common, release_ops
from quant_system.ops.backup_restore import (
    _assert_archive_unchanged,
    _sanitized_authority_role_dump,
    seed_role_authority_probe,
)
from quant_system.ops.common import (
    ReleaseOperationError,
    canonical_json_bytes,
    sha256_file,
)
from quant_system.ops.postgres_common import (
    database_authority_facts,
    restore_database_authority,
)
from quant_system.ops.postgres_container import (
    DisposablePostgresContainer,
    DockerDaemonIdentity,
    owned_process_environment,
    resolve_local_docker_daemon,
)
from quant_system.ops.postgres_suite import _safe_test_environment


class _Rows:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None


def _missing_container(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        returncode=1,
        stdout="[]\n",
        stderr=f"Error: No such object: {name}\n",
    )


def _missing_volume(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        returncode=1,
        stdout="[]\n",
        stderr=f"Error response from daemon: get {name}: no such volume\n",
    )


class _RoleFactsConnection:
    def __enter__(self) -> _RoleFactsConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str) -> _Rows:
        normalized = " ".join(query.split())
        if "FROM pg_auth_members" in normalized:
            if "!~ '^pg_'" in normalized:
                return _Rows([])
            if not all(
                token in normalized for token in ("grantor", "inherit_option", "set_option")
            ):
                return _Rows([("parent", "member", True)])
            return _Rows(
                [
                    (
                        "pg_read_all_data",
                        "runtime",
                        "agent_v02_admin",
                        False,
                        True,
                        True,
                    )
                ]
            )
        if "FROM pg_roles" in normalized:
            base = (
                "runtime",
                False,
                True,
                False,
                False,
                True,
                False,
                False,
                -1,
                "",
            )
            if "rolconfig" not in normalized:
                return _Rows([base])
            rows = [
                (
                    "pg_read_all_data",
                    False,
                    True,
                    False,
                    False,
                    False,
                    False,
                    False,
                    -1,
                    "",
                    [],
                ),
                (*base, ["statement_timeout=1s", "row_security=on"]),
            ]
            if "!~ '^pg_'" in normalized:
                rows = rows[1:]
            return _Rows(rows)
        raise AssertionError(f"unexpected role-facts query: {normalized}")


class _RoleFactsConnectionContext:
    def __enter__(self) -> _RoleFactsConnection:
        return _RoleFactsConnection()

    def __exit__(self, *_args: object) -> None:
        return None


class _DatabaseAuthorityConnection:
    def __enter__(self) -> _DatabaseAuthorityConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str) -> _Rows:
        normalized = " ".join(query.split())
        if "aclexplode" in normalized:
            return _Rows(
                [
                    ("agent_v02_admin", "agent_v02_admin", "CONNECT", False),
                    ("agent_v02_admin", "quant_readonly", "CONNECT", False),
                ]
            )
        if "FROM pg_db_role_setting" in normalized:
            return _Rows(
                [
                    ("role", "quant_runtime", "statement_timeout=4321ms"),
                ]
            )
        if "FROM pg_database" in normalized:
            return _Rows([("agent_v02_admin", True, -1)])
        raise AssertionError(f"unexpected database-authority query: {normalized}")


class _DatabaseAuthorityConnectionContext:
    def __enter__(self) -> _DatabaseAuthorityConnection:
        return _DatabaseAuthorityConnection()

    def __exit__(self, *_args: object) -> None:
        return None


def test_owned_process_environment_rehomes_all_writable_process_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    external = tmp_path / "external"
    monkeypatch.setenv("HOME", str(external / "home"))
    monkeypatch.setenv("TMPDIR", str(external / "tmpdir"))
    monkeypatch.setenv("TMP", str(external / "tmp"))
    monkeypatch.setenv("TEMP", str(external / "temp"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(external / "cache"))
    output_dir = tmp_path / "evidence"

    env = owned_process_environment(output_dir / "process")

    writable_names = (
        "HOME",
        "TMPDIR",
        "TMP",
        "TEMP",
        "XDG_CACHE_HOME",
        "PIP_CACHE_DIR",
        "UV_CACHE_DIR",
        "PYTHONPYCACHEPREFIX",
    )
    for name in writable_names:
        path = Path(env[name])
        assert path.is_relative_to(output_dir)
        assert path.is_dir()
        assert path.stat().st_mode & 0o777 == 0o700
    assert set(env).isdisjoint({"DOCKER_CONTEXT"})


def test_postgres_suite_pytest_environment_uses_owned_process_root(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    process_root = tmp_path / "evidence" / "pytest-process"

    env = _safe_test_environment(
        repository_root=repository_root,
        database_url=(
            "postgresql://agent_v02_admin:secret@127.0.0.1:55432/agent_v02_suite_fixture_tmp"
        ),
        process_root=process_root,
    )

    for name in ("HOME", "TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME"):
        assert Path(env[name]).is_relative_to(process_root)
    assert env["PYTHONPATH"] == str(repository_root / "src")


def test_role_facts_cover_postgresql_16_role_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        postgres_common.psycopg,
        "connect",
        lambda *_args, **_kwargs: _RoleFactsConnectionContext(),
    )

    facts = postgres_common.role_facts("postgresql://operator:secret@127.0.0.1/agent_v02_test_tmp")

    roles = facts["document"]["roles"]
    memberships = facts["document"]["memberships"]
    assert roles == [
        [
            "pg_read_all_data",
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            -1,
            "",
            [],
        ],
        [
            "runtime",
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            -1,
            "",
            ["row_security=on", "statement_timeout=1s"],
        ],
    ]
    assert memberships == [
        [
            "pg_read_all_data",
            "runtime",
            "agent_v02_admin",
            False,
            True,
            True,
        ]
    ]


def test_database_authority_facts_normalize_owner_acl_and_per_database_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        postgres_common.psycopg,
        "connect",
        lambda *_args, **_kwargs: _DatabaseAuthorityConnectionContext(),
    )

    facts = database_authority_facts(
        "postgresql://agent_v02_admin:secret@127.0.0.1:55432/agent_v02_backup_source_fixture_tmp"
    )

    assert facts["document"] == {
        "database": {
            "owner": "agent_v02_admin",
            "allow_connections": True,
            "connection_limit": -1,
        },
        "acl": [
            ["agent_v02_admin", "agent_v02_admin", "CONNECT", False],
            ["agent_v02_admin", "quant_readonly", "CONNECT", False],
        ],
        "settings": [
            ["role", "quant_runtime", "statement_timeout=4321ms"],
        ],
    }
    assert facts["acl_count"] == 2
    assert facts["setting_count"] == 1
    assert len(str(facts["sha256"])) == 64


def test_restore_database_authority_replays_acl_and_role_in_database_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_document = {
        "database": {
            "owner": "agent_v02_admin",
            "allow_connections": True,
            "connection_limit": -1,
        },
        "acl": [
            ["agent_v02_admin", "agent_v02_admin", "CONNECT", False],
            ["agent_v02_admin", "quant_readonly", "CONNECT", False],
        ],
        "settings": [
            ["role", "quant_runtime", "statement_timeout=4321ms"],
        ],
    }
    source = {
        "acl_count": 2,
        "setting_count": 1,
        "sha256": hashlib.sha256(canonical_json_bytes(source_document)).hexdigest(),
        "document": source_document,
    }
    before_document = {
        "database": {
            "owner": "agent_v02_admin",
            "allow_connections": True,
            "connection_limit": -1,
        },
        "acl": [
            ["agent_v02_admin", "agent_v02_admin", "CONNECT", False],
        ],
        "settings": [],
    }
    before = {
        "acl_count": 1,
        "setting_count": 0,
        "sha256": hashlib.sha256(canonical_json_bytes(before_document)).hexdigest(),
        "document": before_document,
    }
    authority_reads = iter((before, source))
    monkeypatch.setattr(
        postgres_common,
        "database_authority_facts",
        lambda _url: next(authority_reads),
    )
    statements: list[str] = []

    class _RestoreAuthorityConnection:
        def __enter__(self) -> _RestoreAuthorityConnection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, query: object) -> _Rows:
            rendered = str(query)
            statements.append(rendered)
            if rendered == "SELECT current_database(), current_user":
                return _Rows([("agent_v02_restore_fixture_tmp", "agent_v02_admin")])
            return _Rows([])

    monkeypatch.setattr(
        postgres_common.psycopg,
        "connect",
        lambda *_args, **_kwargs: _RestoreAuthorityConnection(),
    )

    restored = restore_database_authority(
        "postgresql://agent_v02_admin:secret@127.0.0.1:55432/agent_v02_restore_fixture_tmp",
        source,
    )

    assert restored["sha256"] == source["sha256"]
    rendered_statements = "\n".join(statements)
    assert "REVOKE" in rendered_statements
    assert "GRANT" in rendered_statements
    assert "ALTER ROLE" in rendered_statements
    assert "statement_timeout" in rendered_statements


def test_seed_and_restore_database_owner_transition_uses_real_authority_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_database = "agent_v02_backup_source_owner_fixture_tmp"
    destination_database = "agent_v02_restore_owner_fixture_tmp"
    source_url = "postgresql://agent_v02_admin:secret@127.0.0.1:55432/" + source_database
    destination_url = "postgresql://agent_v02_admin:secret@127.0.0.1:55432/" + destination_database
    owners = {
        source_database: "agent_v02_admin",
        destination_database: "agent_v02_admin",
    }

    class _OwnerTransitionConnection:
        def __init__(self, database_name: str) -> None:
            self.database_name = database_name

        def __enter__(self) -> _OwnerTransitionConnection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(
            self,
            query: object,
            _parameters: object = None,
        ) -> _Rows:
            rendered = " ".join(str(query).split())
            if rendered == "SELECT current_database(), current_user":
                return _Rows([(self.database_name, "agent_v02_admin")])
            if "aclexplode" in rendered:
                return _Rows([])
            if "FROM pg_db_role_setting" in rendered:
                return _Rows([])
            if "FROM pg_database AS database_row" in rendered:
                return _Rows([(owners[self.database_name], True, -1)])
            if "OWNER TO" in rendered and "quant_migrator" in rendered:
                owners[self.database_name] = "quant_migrator"
            return _Rows([])

    def _connect(url: object, **_kwargs: object) -> _OwnerTransitionConnection:
        text = str(url)
        database_name = next(name for name in owners if name in text)
        return _OwnerTransitionConnection(database_name)

    monkeypatch.setattr(postgres_common.psycopg, "connect", _connect)

    seed_role_authority_probe(source_url)
    source_authority = database_authority_facts(source_url)
    assert source_authority["document"]["database"]["owner"] == "quant_migrator"
    assert owners[destination_database] == "agent_v02_admin"

    restored = restore_database_authority(destination_url, source_authority)

    assert owners[destination_database] == "quant_migrator"
    assert restored["sha256"] == source_authority["sha256"]


def test_disposable_postgres_source_requires_local_image_and_loopback() -> None:
    source = Path(DisposablePostgresContainer.__module__.replace(".", "/"))
    module_text = (
        (Path(__file__).resolve().parents[1] / "src" / source)
        .with_suffix(".py")
        .read_text(encoding="utf-8")
    )
    assert '"--pull=never"' in module_text
    assert '"127.0.0.1::5432"' in module_text
    assert "type=volume,source=" in module_text
    assert '"--volumes"' in module_text
    assert '"volume", "rm"' in module_text
    assert 'POSTGRES_IMAGE = "postgres:16-alpine"' in module_text


def test_docker_daemon_binding_rejects_remote_and_pins_local_unix_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_root = tmp_path / "evidence" / "docker-process"
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.example.invalid:2376")
    with pytest.raises(ReleaseOperationError, match="local unix socket"):
        resolve_local_docker_daemon(
            docker="/usr/local/bin/docker",
            process_root=process_root,
        )

    socket_path = Path("/owned-evidence/docker.sock")
    monkeypatch.setenv("DOCKER_HOST", f"unix://{socket_path}")
    original_resolve = Path.resolve
    original_stat = Path.stat
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda self, **kwargs: (
            socket_path if self == socket_path else original_resolve(self, **kwargs)
        ),
    )
    monkeypatch.setattr(
        Path,
        "stat",
        lambda self, **kwargs: (
            SimpleNamespace(
                st_mode=stat.S_IFSOCK | 0o600,
                st_dev=41,
                st_ino=73,
            )
            if self == socket_path
            else original_stat(self, **kwargs)
        ),
    )

    class _Completed:
        returncode = 0
        stdout = '"daemon-id"|"16.4.0"|"local-test-daemon"\n'
        stderr = ""

    calls: list[tuple[list[str], dict[str, str]]] = []

    def _run(
        argv: list[str],
        **kwargs: object,
    ) -> _Completed:
        calls.append((argv, dict(kwargs["env"])))  # type: ignore[arg-type]
        return _Completed()

    monkeypatch.setattr("quant_system.ops.postgres_container.subprocess.run", _run)
    identity, env = resolve_local_docker_daemon(
        docker="/usr/local/bin/docker",
        process_root=process_root,
    )

    assert identity.endpoint == f"unix://{socket_path.resolve()}"
    assert identity.daemon_id == "daemon-id"
    assert identity.server_version == "16.4.0"
    assert identity.operating_system == "local-test-daemon"
    assert env["DOCKER_HOST"] == identity.endpoint
    assert "DOCKER_CONTEXT" not in env
    assert Path(env["HOME"]).is_relative_to(process_root)
    assert calls == [
        (
            [
                "/usr/local/bin/docker",
                "info",
                "--format",
                "{{json .ID}}|{{json .ServerVersion}}|{{json .OperatingSystem}}",
            ],
            env,
        )
    ]


def test_disposable_postgres_teardown_removes_exact_container_and_owned_volume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = DisposablePostgresContainer(process_root=tmp_path / "process")
    container._docker = "/usr/local/bin/docker"
    container._docker_env = {"PATH": "/usr/bin"}
    container._started = True
    calls: list[list[str]] = []
    container_exists = True
    volume_exists = True

    class _Completed:
        def __init__(self, returncode: int, stdout: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def _run(argv: list[str], **_kwargs: object) -> _Completed:
        nonlocal container_exists, volume_exists
        calls.append(argv)
        operation = argv[1:]
        if operation == ["inspect", container.name]:
            if not container_exists:
                return _missing_container(container.name)
            return _Completed(
                0,
                json.dumps(
                    [
                        {
                            "Name": f"/{container.name}",
                            "Config": {
                                "Labels": {
                                    "com.yiboway.agent-v02.owner": "v0.2.2-hardening",
                                    "com.yiboway.agent-v02.volume": container.volume_name,
                                }
                            },
                            "Mounts": [],
                        }
                    ]
                ),
            )
        if operation[:3] == ["rm", "--force", "--volumes"]:
            container_exists = False
            return _Completed(0)
        if operation == ["volume", "inspect", container.volume_name]:
            if not volume_exists:
                return _missing_volume(container.volume_name)
            return _Completed(
                0,
                json.dumps(
                    [
                        {
                            "Name": container.volume_name,
                            "Driver": "local",
                            "Labels": {
                                "com.yiboway.agent-v02.owner": "v0.2.2-hardening",
                                "com.yiboway.agent-v02.container": container.name,
                            },
                            "Scope": "local",
                        }
                    ]
                ),
            )
        if operation == ["volume", "rm", container.volume_name]:
            volume_exists = False
            return _Completed(0)
        return _Completed(0)

    monkeypatch.setattr("quant_system.ops.postgres_container.subprocess.run", _run)
    container.stop()

    assert calls == [
        ["/usr/local/bin/docker", "inspect", container.name],
        [
            "/usr/local/bin/docker",
            "rm",
            "--force",
            "--volumes",
            container.name,
        ],
        ["/usr/local/bin/docker", "inspect", container.name],
        [
            "/usr/local/bin/docker",
            "volume",
            "inspect",
            container.volume_name,
        ],
        ["/usr/local/bin/docker", "volume", "rm", container.volume_name],
        [
            "/usr/local/bin/docker",
            "volume",
            "inspect",
            container.volume_name,
        ],
    ]
    assert container.cleanup_facts == {
        "container_name": container.name,
        "container_removed": True,
        "container_absent_after_remove": True,
        "container_remove_included_volumes": True,
        "volume_name": container.volume_name,
        "volume_removed": True,
        "volume_absent_after_remove": True,
    }

    leaking = DisposablePostgresContainer(process_root=tmp_path / "leaking-process")
    leaking._docker = "/usr/local/bin/docker"
    leaking._docker_env = {"PATH": "/usr/bin"}
    leaking._started = True
    leaking_container_inspects = 0

    def _leaking_run(argv: list[str], **_kwargs: object) -> _Completed:
        nonlocal leaking_container_inspects
        operation = argv[1:]
        if operation == ["inspect", leaking.name]:
            leaking_container_inspects += 1
            if leaking_container_inspects > 1:
                return _missing_container(leaking.name)
            return _Completed(
                0,
                json.dumps(
                    [
                        {
                            "Name": f"/{leaking.name}",
                            "Config": {
                                "Labels": {
                                    "com.yiboway.agent-v02.owner": "v0.2.2-hardening",
                                    "com.yiboway.agent-v02.volume": leaking.volume_name,
                                }
                            },
                            "Mounts": [],
                        }
                    ]
                ),
            )
        if operation == ["volume", "inspect", leaking.volume_name]:
            return _Completed(
                0,
                json.dumps(
                    [
                        {
                            "Name": leaking.volume_name,
                            "Driver": "local",
                            "Labels": {
                                "com.yiboway.agent-v02.owner": "v0.2.2-hardening",
                                "com.yiboway.agent-v02.container": leaking.name,
                            },
                            "Scope": "local",
                        }
                    ]
                ),
            )
        return _Completed(0)

    monkeypatch.setattr(
        "quant_system.ops.postgres_container.subprocess.run",
        _leaking_run,
    )
    with pytest.raises(ReleaseOperationError, match="data volume"):
        leaking.stop()


def test_disposable_postgres_teardown_accepts_exact_docker29_lowercase_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = DisposablePostgresContainer(process_root=tmp_path / "process")
    container._docker = "/usr/local/bin/docker"
    container._docker_env = {"PATH": "/usr/bin"}
    container._started = True
    calls: list[list[str]] = []
    container_exists = True
    volume_exists = True

    def _run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        nonlocal container_exists, volume_exists
        calls.append(argv)
        operation = argv[1:]
        if operation == ["inspect", container.name]:
            if not container_exists:
                return SimpleNamespace(
                    returncode=1,
                    stdout="[]\n",
                    stderr=f"error: no such object: {container.name}\n",
                )
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "Name": f"/{container.name}",
                            "Config": {
                                "Labels": {
                                    "com.yiboway.agent-v02.owner": "v0.2.2-hardening",
                                    "com.yiboway.agent-v02.volume": container.volume_name,
                                }
                            },
                            "Mounts": [],
                        }
                    ]
                ),
                stderr="",
            )
        if operation[:3] == ["rm", "--force", "--volumes"]:
            container_exists = False
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if operation == ["volume", "inspect", container.volume_name]:
            if not volume_exists:
                return _missing_volume(container.volume_name)
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "Name": container.volume_name,
                            "Driver": "local",
                            "Labels": {
                                "com.yiboway.agent-v02.owner": "v0.2.2-hardening",
                                "com.yiboway.agent-v02.container": container.name,
                            },
                            "Scope": "local",
                        }
                    ]
                ),
                stderr="",
            )
        if operation == ["volume", "rm", container.volume_name]:
            volume_exists = False
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected Docker command: {argv}")

    monkeypatch.setattr("quant_system.ops.postgres_container.subprocess.run", _run)

    container.stop()

    assert calls == [
        ["/usr/local/bin/docker", "inspect", container.name],
        [
            "/usr/local/bin/docker",
            "rm",
            "--force",
            "--volumes",
            container.name,
        ],
        ["/usr/local/bin/docker", "inspect", container.name],
        [
            "/usr/local/bin/docker",
            "volume",
            "inspect",
            container.volume_name,
        ],
        ["/usr/local/bin/docker", "volume", "rm", container.volume_name],
        [
            "/usr/local/bin/docker",
            "volume",
            "inspect",
            container.volume_name,
        ],
    ]
    assert volume_exists is False
    assert container.cleanup_facts["container_absent_after_remove"] is True
    assert container.cleanup_facts["volume_absent_after_remove"] is True


@pytest.mark.parametrize("failure_stage", ["image_inspect", "docker_run_exception"])
def test_disposable_postgres_start_failure_removes_created_owned_volume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    container = DisposablePostgresContainer(process_root=tmp_path / "process")
    container._docker = "/usr/local/bin/docker"
    docker_environment = {"PATH": "/usr/bin", "DOCKER_HOST": "unix:///owned/docker.sock"}
    daemon_identity = DockerDaemonIdentity(
        context="default",
        endpoint=docker_environment["DOCKER_HOST"],
        socket_path="/owned/docker.sock",
        socket_device=41,
        socket_inode=73,
        daemon_id="daemon-id",
        server_version="16.4.0",
        operating_system="local-test-daemon",
    )
    monkeypatch.setattr(
        "quant_system.ops.postgres_container.resolve_local_docker_daemon",
        lambda **_kwargs: (daemon_identity, docker_environment),
    )

    class _Completed:
        def __init__(self, returncode: int, stdout: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    calls: list[list[str]] = []
    volume_exists = False

    def _run(argv: list[str], **_kwargs: object) -> _Completed:
        nonlocal volume_exists
        calls.append(argv)
        operation = argv[1:]
        if operation[:2] == ["volume", "create"]:
            volume_exists = True
            return _Completed(0, f"{container.volume_name}\n")
        if operation == ["volume", "inspect", container.volume_name]:
            if volume_exists:
                return _Completed(
                    0,
                    (
                        '[{"Name":"' + container.volume_name + '","Driver":"local","Labels":{'
                        '"com.yiboway.agent-v02.owner":"v0.2.2-hardening",'
                        '"com.yiboway.agent-v02.container":"'
                        + container.name
                        + '"},"Scope":"local"}]'
                    ),
                )
            return _missing_volume(container.volume_name)
        if operation[:2] == ["image", "inspect"]:
            if failure_stage == "image_inspect":
                return _Completed(1)
            return _Completed(0, "sha256:image-id\n")
        if operation and operation[0] == "run":
            raise OSError("simulated docker run execution failure")
        if operation == ["inspect", container.name]:
            return _missing_container(container.name)
        if operation == ["volume", "rm", container.volume_name]:
            volume_exists = False
            return _Completed(0)
        raise AssertionError(f"unexpected Docker command: {argv}")

    monkeypatch.setattr("quant_system.ops.postgres_container.subprocess.run", _run)
    expected_error = ReleaseOperationError if failure_stage == "image_inspect" else OSError
    with pytest.raises(expected_error):
        container.start()

    assert [
        "/usr/local/bin/docker",
        "volume",
        "rm",
        container.volume_name,
    ] in calls
    assert calls[-1] == [
        "/usr/local/bin/docker",
        "volume",
        "inspect",
        container.volume_name,
    ]
    assert container.cleanup_facts["volume_absent_after_remove"] is True


@pytest.mark.parametrize(
    "failure_stage",
    ["volume_create_exception", "docker_run_exception_after_create"],
)
def test_disposable_postgres_reconciles_unknown_acquisition_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    container = DisposablePostgresContainer(process_root=tmp_path / "process")
    container._docker = "/usr/local/bin/docker"
    docker_environment = {"PATH": "/usr/bin", "DOCKER_HOST": "unix:///owned/docker.sock"}
    daemon_identity = DockerDaemonIdentity(
        context="default",
        endpoint=docker_environment["DOCKER_HOST"],
        socket_path="/owned/docker.sock",
        socket_device=41,
        socket_inode=73,
        daemon_id="daemon-id",
        server_version="16.4.0",
        operating_system="local-test-daemon",
    )
    monkeypatch.setattr(
        "quant_system.ops.postgres_container.resolve_local_docker_daemon",
        lambda **_kwargs: (daemon_identity, docker_environment),
    )

    class _Completed:
        def __init__(self, returncode: int, stdout: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    calls: list[list[str]] = []
    volume_exists = False
    container_exists = False

    def _volume_document() -> str:
        return json.dumps(
            [
                {
                    "Name": container.volume_name,
                    "Driver": "local",
                    "Labels": {
                        "com.yiboway.agent-v02.owner": "v0.2.2-hardening",
                        "com.yiboway.agent-v02.container": container.name,
                    },
                    "Scope": "local",
                }
            ]
        )

    def _container_document() -> str:
        return json.dumps(
            [
                {
                    "Name": f"/{container.name}",
                    "Image": "sha256:image-id",
                    "Config": {
                        "Labels": {
                            "com.yiboway.agent-v02.owner": "v0.2.2-hardening",
                            "com.yiboway.agent-v02.volume": container.volume_name,
                        }
                    },
                    "Mounts": [
                        {
                            "Type": "volume",
                            "Name": container.volume_name,
                            "Driver": "local",
                            "Destination": "/var/lib/postgresql/data",
                            "RW": True,
                        }
                    ],
                }
            ]
        )

    def _run(argv: list[str], **_kwargs: object) -> _Completed:
        nonlocal container_exists, volume_exists
        calls.append(argv)
        operation = argv[1:]
        if operation[:2] == ["volume", "create"]:
            volume_exists = True
            if failure_stage == "volume_create_exception":
                raise OSError("simulated ambiguous volume creation outcome")
            return _Completed(0, f"{container.volume_name}\n")
        if operation == ["volume", "inspect", container.volume_name]:
            return (
                _Completed(0, _volume_document())
                if volume_exists
                else _missing_volume(container.volume_name)
            )
        if operation[:2] == ["image", "inspect"]:
            return _Completed(0, "sha256:image-id\n")
        if operation and operation[0] == "run":
            container_exists = True
            raise OSError("simulated ambiguous container creation outcome")
        if operation == ["inspect", container.name]:
            return (
                _Completed(0, _container_document())
                if container_exists
                else _missing_container(container.name)
            )
        if operation[:3] == ["rm", "--force", "--volumes"]:
            container_exists = False
            return _Completed(0)
        if operation == ["volume", "rm", container.volume_name]:
            if container_exists:
                return _Completed(1)
            volume_exists = False
            return _Completed(0)
        raise AssertionError(f"unexpected Docker command: {argv}")

    monkeypatch.setattr("quant_system.ops.postgres_container.subprocess.run", _run)
    with pytest.raises(OSError):
        container.start()

    assert ["/usr/local/bin/docker", "inspect", container.name] in calls
    if failure_stage == "docker_run_exception_after_create":
        assert [
            "/usr/local/bin/docker",
            "rm",
            "--force",
            "--volumes",
            container.name,
        ] in calls
    assert [
        "/usr/local/bin/docker",
        "volume",
        "rm",
        container.volume_name,
    ] in calls
    assert container.cleanup_facts["container_absent_after_remove"] is True
    assert container.cleanup_facts["volume_absent_after_remove"] is True


@pytest.mark.parametrize("inject_anonymous_volume", [False, True])
def test_disposable_postgres_binds_exact_named_pgdata_mount_without_anonymous_volume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inject_anonymous_volume: bool,
) -> None:
    container = DisposablePostgresContainer(process_root=tmp_path / "process")
    container._docker = "/usr/local/bin/docker"
    docker_environment = {"PATH": "/usr/bin", "DOCKER_HOST": "unix:///owned/docker.sock"}
    daemon_identity = DockerDaemonIdentity(
        context="default",
        endpoint=docker_environment["DOCKER_HOST"],
        socket_path="/owned/docker.sock",
        socket_device=41,
        socket_inode=73,
        daemon_id="daemon-id",
        server_version="16.4.0",
        operating_system="local-test-daemon",
    )
    monkeypatch.setattr(
        "quant_system.ops.postgres_container.resolve_local_docker_daemon",
        lambda **_kwargs: (daemon_identity, docker_environment),
    )

    class _Completed:
        def __init__(self, returncode: int, stdout: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    calls: list[list[str]] = []
    container_exists = False
    volume_exists = False
    expected_mount = {
        "Type": "volume",
        "Name": container.volume_name,
        "Driver": "local",
        "Destination": "/var/lib/postgresql/data",
        "RW": True,
    }
    observed_mounts = [expected_mount]
    if inject_anonymous_volume:
        observed_mounts.append(
            {
                "Type": "volume",
                "Name": "anonymous-volume-regression",
                "Driver": "local",
                "Destination": "/unexpected-anonymous-volume",
                "RW": True,
            }
        )

    def _run(argv: list[str], **_kwargs: object) -> _Completed:
        nonlocal container_exists, volume_exists
        calls.append(argv)
        operation = argv[1:]
        if operation[:2] == ["volume", "create"]:
            volume_exists = True
            return _Completed(0, f"{container.volume_name}\n")
        if operation == ["volume", "inspect", container.volume_name]:
            if volume_exists:
                return _Completed(
                    0,
                    json.dumps(
                        [
                            {
                                "Name": container.volume_name,
                                "Driver": "local",
                                "Labels": {
                                    "com.yiboway.agent-v02.owner": "v0.2.2-hardening",
                                    "com.yiboway.agent-v02.container": container.name,
                                },
                                "Scope": "local",
                            }
                        ]
                    ),
                )
            return _missing_volume(container.volume_name)
        if operation[:2] == ["image", "inspect"]:
            return _Completed(0, "sha256:image-id\n")
        if operation and operation[0] == "run":
            container_exists = True
            return _Completed(0, "container-id\n")
        if operation == ["inspect", container.name]:
            if container_exists:
                return _Completed(
                    0,
                    json.dumps(
                        [
                            {
                                "Name": f"/{container.name}",
                                "Image": "sha256:image-id",
                                "Config": {
                                    "Labels": {
                                        "com.yiboway.agent-v02.owner": "v0.2.2-hardening",
                                        "com.yiboway.agent-v02.volume": container.volume_name,
                                    }
                                },
                                "Mounts": observed_mounts,
                            }
                        ]
                    ),
                )
            return _missing_container(container.name)
        if operation == ["port", container.name, "5432/tcp"]:
            return _Completed(0, "127.0.0.1:55432\n")
        if operation[:3] == ["rm", "--force", "--volumes"]:
            container_exists = False
            return _Completed(0)
        if operation == ["volume", "rm", container.volume_name]:
            volume_exists = False
            return _Completed(0)
        raise AssertionError(f"unexpected Docker command: {argv}")

    class _ReadyConnection:
        def __enter__(self) -> _ReadyConnection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _query: str) -> _Rows:
            return _Rows([(container.database, container.user, "PostgreSQL 16")])

    monkeypatch.setattr("quant_system.ops.postgres_container.subprocess.run", _run)
    monkeypatch.setattr(
        "quant_system.ops.postgres_container.psycopg.connect",
        lambda *_args, **_kwargs: _ReadyConnection(),
    )

    if inject_anonymous_volume:
        with pytest.raises(ReleaseOperationError, match="exact named PGDATA mount"):
            container.start()
        assert container.cleanup_facts["container_absent_after_remove"] is True
        assert container.cleanup_facts["volume_absent_after_remove"] is True
        return

    identity = container.start()
    run_argv = next(argv for argv in calls if argv[1:2] == ["run"])
    mount_index = run_argv.index("--mount")
    assert run_argv[mount_index : mount_index + 2] == [
        "--mount",
        (f"type=volume,source={container.volume_name},target=/var/lib/postgresql/data"),
    ]
    assert identity.pgdata_mount == expected_mount
    assert identity.anonymous_volume_count == 0

    container.stop()
    assert container.cleanup_facts["container_absent_after_remove"] is True
    assert container.cleanup_facts["volume_absent_after_remove"] is True


@pytest.mark.parametrize(
    "failure_stage",
    ("container_pre", "container_post", "volume_pre", "volume_post"),
)
def test_disposable_postgres_inspect_errors_fail_closed_and_allow_cleanup_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    container = DisposablePostgresContainer(process_root=tmp_path / "process")
    container._docker = "/usr/local/bin/docker"
    container._docker_env = {"PATH": "/usr/bin"}
    container._started = True
    container_exists = True
    volume_exists = True
    failure_injected = False

    class _Completed:
        def __init__(
            self,
            returncode: int,
            stdout: str = "",
            stderr: str = "",
        ) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _container_document() -> str:
        return json.dumps(
            [
                {
                    "Name": f"/{container.name}",
                    "Config": {
                        "Labels": {
                            "com.yiboway.agent-v02.owner": "v0.2.2-hardening",
                            "com.yiboway.agent-v02.volume": container.volume_name,
                        }
                    },
                    "Mounts": [],
                }
            ]
        )

    def _volume_document() -> str:
        return json.dumps(
            [
                {
                    "Name": container.volume_name,
                    "Driver": "local",
                    "Labels": {
                        "com.yiboway.agent-v02.owner": "v0.2.2-hardening",
                        "com.yiboway.agent-v02.container": container.name,
                    },
                    "Scope": "local",
                }
            ]
        )

    def _container_absent() -> _Completed:
        return _Completed(
            1,
            "[]\n",
            f"Error: No such object: {container.name}\n",
        )

    def _volume_absent() -> _Completed:
        return _Completed(
            1,
            "[]\n",
            (f"Error response from daemon: get {container.volume_name}: no such volume\n"),
        )

    def _daemon_error() -> _Completed:
        return _Completed(
            1,
            "",
            "Cannot connect to the Docker daemon at unix:///owned/docker.sock\n",
        )

    def _run(argv: list[str], **_kwargs: object) -> _Completed:
        nonlocal container_exists, failure_injected, volume_exists
        operation = argv[1:]
        if operation == ["inspect", container.name]:
            if not failure_injected and (
                (failure_stage == "container_pre" and container_exists)
                or (failure_stage == "container_post" and not container_exists)
            ):
                failure_injected = True
                return _daemon_error()
            return _Completed(0, _container_document()) if container_exists else _container_absent()
        if operation[:3] == ["rm", "--force", "--volumes"]:
            container_exists = False
            return _Completed(0)
        if operation == ["volume", "inspect", container.volume_name]:
            if not failure_injected and (
                (failure_stage == "volume_pre" and volume_exists)
                or (failure_stage == "volume_post" and not volume_exists)
            ):
                failure_injected = True
                return _daemon_error()
            return _Completed(0, _volume_document()) if volume_exists else _volume_absent()
        if operation == ["volume", "rm", container.volume_name]:
            volume_exists = False
            return _Completed(0)
        raise AssertionError(f"unexpected Docker command: {argv}")

    monkeypatch.setattr("quant_system.ops.postgres_container.subprocess.run", _run)

    with pytest.raises(ReleaseOperationError, match="inspect"):
        container.stop()
    assert container._cleanup_facts is None

    container.stop()
    assert failure_injected is True
    assert container.cleanup_facts["container_absent_after_remove"] is True
    assert container.cleanup_facts["volume_absent_after_remove"] is True


@pytest.mark.parametrize("signum", (signal.SIGINT, signal.SIGTERM))
@pytest.mark.parametrize("cleanup_succeeds", (True, False))
def test_release_ops_signal_during_stop_retries_exact_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    signum: signal.Signals,
    cleanup_succeeds: bool,
) -> None:
    container_holder: list[DisposablePostgresContainer] = []
    container_exists = True
    volume_exists = True
    remove_attempts = 0
    shielded_signal = signal.SIGTERM if signum == signal.SIGINT else signal.SIGINT
    previous_handlers = {
        signal.SIGINT: signal.getsignal(signal.SIGINT),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
    }

    class _Completed:
        def __init__(
            self,
            returncode: int,
            stdout: str = "",
            stderr: str = "",
        ) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _interrupted_operation(**_kwargs: object) -> dict[str, object]:
        container = DisposablePostgresContainer(process_root=tmp_path / "process")
        container._docker = "/usr/local/bin/docker"
        container._docker_env = {"PATH": "/usr/bin"}
        container._started = True
        container_holder.append(container)
        container.stop()
        raise AssertionError("the original signal must reach the CLI after cleanup")

    def _run(argv: list[str], **_kwargs: object) -> _Completed:
        nonlocal container_exists, remove_attempts, volume_exists
        container = container_holder[0]
        operation = argv[1:]
        if operation == ["inspect", container.name]:
            if container_exists:
                return _Completed(
                    0,
                    json.dumps(
                        [
                            {
                                "Name": f"/{container.name}",
                                "Config": {
                                    "Labels": {
                                        "com.yiboway.agent-v02.owner": ("v0.2.2-hardening"),
                                        "com.yiboway.agent-v02.volume": (container.volume_name),
                                    }
                                },
                                "Mounts": [],
                            }
                        ]
                    ),
                )
            return _Completed(
                1,
                "[]\n",
                f"Error: No such object: {container.name}\n",
            )
        if operation[:3] == ["rm", "--force", "--volumes"]:
            remove_attempts += 1
            if remove_attempts == 1:
                os.kill(os.getpid(), signum)
                raise AssertionError("the first signal must unwind this stop attempt")
            os.kill(os.getpid(), shielded_signal)
            if not cleanup_succeeds:
                return _Completed(1, "", "simulated cleanup failure\n")
            container_exists = False
            return _Completed(0)
        if operation == ["volume", "inspect", container.volume_name]:
            if volume_exists:
                return _Completed(
                    0,
                    json.dumps(
                        [
                            {
                                "Name": container.volume_name,
                                "Driver": "local",
                                "Labels": {
                                    "com.yiboway.agent-v02.owner": "v0.2.2-hardening",
                                    "com.yiboway.agent-v02.container": container.name,
                                },
                                "Scope": "local",
                            }
                        ]
                    ),
                )
            return _Completed(
                1,
                "[]\n",
                (f"Error response from daemon: get {container.volume_name}: no such volume\n"),
            )
        if operation == ["volume", "rm", container.volume_name]:
            volume_exists = False
            return _Completed(0)
        raise AssertionError(f"unexpected Docker command: {argv}")

    monkeypatch.setattr("quant_system.ops.postgres_container.subprocess.run", _run)
    monkeypatch.setattr(release_ops, "verify_postgres_suite", _interrupted_operation)

    exit_code = release_ops.main(
        [
            "postgres-suite",
            "--repository-root",
            str(tmp_path / "repository"),
            "--output-dir",
            str(tmp_path / "evidence"),
        ]
    )

    error = json.loads(capsys.readouterr().err)
    assert exit_code == 78
    assert remove_attempts == 2
    if cleanup_succeeds:
        assert error["error"] == "interrupted_by_signal"
        assert error["signal"] == signum
        assert container_exists is False
        assert volume_exists is False
        assert container_holder[0].cleanup_facts["container_absent_after_remove"] is True
        assert container_holder[0].cleanup_facts["volume_absent_after_remove"] is True
    else:
        assert error["error"] == ("disposable PostgreSQL cleanup failed after signal interruption")
        assert "signal" not in error
        assert container_exists is True
        assert volume_exists is True
        assert container_holder[0]._cleanup_facts is None
    assert signal.getsignal(signal.SIGINT) is previous_handlers[signal.SIGINT]
    assert signal.getsignal(signal.SIGTERM) is previous_handlers[signal.SIGTERM]


def test_suite_role_cleanup_is_exactly_the_post_baseline_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = {
        "sha256": "baseline",
        "document": {
            "roles": [["agent_v02_admin"], ["quant_runtime"]],
            "memberships": [],
        },
    }
    after_pytest = {
        "sha256": "changed",
        "document": {
            "roles": [
                ["agent_v02_admin"],
                ["aqp_agent_workspace_runtime_test"],
                ["quant_runtime"],
            ],
            "memberships": [],
        },
    }
    role_reads = iter((after_pytest, baseline))
    monkeypatch.setattr(
        postgres_common,
        "role_facts",
        lambda _url: next(role_reads),
    )
    calls: list[tuple[str, str, object]] = []

    class _CleanupConnection:
        def __init__(self, url: str) -> None:
            self.url = url

        def __enter__(self) -> _CleanupConnection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(
            self,
            query: object,
            parameters: object = None,
        ) -> _Rows:
            rendered = str(query)
            calls.append((self.url, rendered, parameters))
            if rendered == "SELECT current_user":
                return _Rows([("agent_v02_admin",)])
            if "FROM pg_database" in rendered:
                return _Rows([("agent_v02_admin_fixture_tmp",), ("postgres",)])
            return _Rows([])

    monkeypatch.setattr(
        postgres_common.psycopg,
        "connect",
        lambda url, **_kwargs: _CleanupConnection(str(url)),
    )

    removed = postgres_common.cleanup_roles_created_since(
        "postgresql://agent_v02_admin:secret@127.0.0.1:55432/agent_v02_admin_fixture_tmp",
        baseline,
    )

    assert removed == ("aqp_agent_workspace_runtime_test",)
    assert any("dbname=postgres" in url for url, _query, _params in calls)
    assert any("DROP OWNED BY" in query for _url, query, _params in calls)
    assert any("DROP ROLE" in query for _url, query, _params in calls)


def test_suite_role_cleanup_rejects_unowned_role_delta_before_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = {
        "sha256": "baseline",
        "document": {
            "roles": [["agent_v02_admin"], ["quant_runtime"]],
            "memberships": [],
        },
    }
    after_pytest = {
        "sha256": "changed",
        "document": {
            "roles": [
                ["agent_v02_admin"],
                ["not_owned_by_the_suite"],
                ["quant_runtime"],
            ],
            "memberships": [],
        },
    }
    monkeypatch.setattr(postgres_common, "role_facts", lambda _url: after_pytest)
    mutation_attempted = False

    def _forbid_connect(*_args: object, **_kwargs: object) -> object:
        nonlocal mutation_attempted
        mutation_attempted = True
        raise AssertionError("cleanup must reject before opening a mutation connection")

    monkeypatch.setattr(postgres_common.psycopg, "connect", _forbid_connect)

    with pytest.raises(ReleaseOperationError, match="not suite-owned"):
        postgres_common.cleanup_roles_created_since(
            "postgresql://agent_v02_admin:secret@127.0.0.1:55432/agent_v02_admin_fixture_tmp",
            baseline,
        )
    assert mutation_attempted is False


@pytest.mark.parametrize(
    ("current_roles", "match"),
    (
        (
            [["agent_v02_admin", True], ["aqp_agent_workspace_runtime_test", False]],
            "missing=quant_runtime",
        ),
        (
            [["agent_v02_admin", True], ["quant_runtime", True]],
            "mutated=quant_runtime",
        ),
    ),
)
def test_suite_role_cleanup_never_deletes_after_baseline_role_rename_or_mutation(
    monkeypatch: pytest.MonkeyPatch,
    current_roles: list[list[object]],
    match: str,
) -> None:
    baseline = {
        "sha256": "baseline",
        "document": {
            "roles": [["agent_v02_admin", True], ["quant_runtime", False]],
            "memberships": [],
        },
    }
    current = {
        "sha256": "changed",
        "document": {"roles": current_roles, "memberships": []},
    }
    monkeypatch.setattr(postgres_common, "role_facts", lambda _url: current)
    mutation_attempted = False

    def _forbid_connect(*_args: object, **_kwargs: object) -> object:
        nonlocal mutation_attempted
        mutation_attempted = True
        raise AssertionError("baseline drift must be rejected before cleanup")

    monkeypatch.setattr(postgres_common.psycopg, "connect", _forbid_connect)

    with pytest.raises(ReleaseOperationError, match=match):
        postgres_common.cleanup_roles_created_since(
            "postgresql://agent_v02_admin:secret@127.0.0.1:55432/agent_v02_admin_fixture_tmp",
            baseline,
        )
    assert mutation_attempted is False


def test_suite_role_cleanup_rejects_system_membership_leak_before_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles = [["agent_v02_admin"], ["pg_read_all_data"], ["quant_runtime"]]
    baseline = {
        "sha256": "baseline",
        "document": {"roles": roles, "memberships": []},
    }
    current = {
        "sha256": "changed",
        "document": {
            "roles": roles,
            "memberships": [
                [
                    "pg_read_all_data",
                    "quant_runtime",
                    "agent_v02_admin",
                    False,
                    True,
                    True,
                ]
            ],
        },
    }
    monkeypatch.setattr(postgres_common, "role_facts", lambda _url: current)
    monkeypatch.setattr(
        postgres_common.psycopg,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("membership drift must be rejected before cleanup")
        ),
    )

    with pytest.raises(ReleaseOperationError, match="memberships changed"):
        postgres_common.cleanup_roles_created_since(
            "postgresql://agent_v02_admin:secret@127.0.0.1:55432/agent_v02_admin_fixture_tmp",
            baseline,
        )


def test_suite_role_cleanup_rejects_baseline_membership_granted_by_introduced_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_roles = [
        ["agent_v02_admin"],
        ["quant_readonly"],
        ["quant_runtime"],
    ]
    baseline = {
        "sha256": "baseline",
        "document": {"roles": baseline_roles, "memberships": []},
    }
    current = {
        "sha256": "changed",
        "document": {
            "roles": [
                ["agent_v02_admin"],
                ["aqp_agent_workspace_runtime_test"],
                ["quant_readonly"],
                ["quant_runtime"],
            ],
            "memberships": [
                [
                    "quant_readonly",
                    "quant_runtime",
                    "aqp_agent_workspace_runtime_test",
                    False,
                    False,
                    True,
                ]
            ],
        },
    }
    monkeypatch.setattr(postgres_common, "role_facts", lambda _url: current)
    mutation_attempted = False

    def _forbid_connect(*_args: object, **_kwargs: object) -> object:
        nonlocal mutation_attempted
        mutation_attempted = True
        raise AssertionError("grantor-only membership drift must fail before cleanup")

    monkeypatch.setattr(postgres_common.psycopg, "connect", _forbid_connect)

    with pytest.raises(ReleaseOperationError, match="memberships changed"):
        postgres_common.cleanup_roles_created_since(
            "postgresql://agent_v02_admin:secret@127.0.0.1:55432/agent_v02_admin_fixture_tmp",
            baseline,
        )
    assert mutation_attempted is False


def test_backup_archive_digest_pin_rejects_one_byte_change(tmp_path: Path) -> None:
    archive = tmp_path / "authority.dump"
    archive.write_bytes(b"authoritative-postgresql-backup")
    expected = sha256_file(archive)
    _assert_archive_unchanged(archive, expected, phase="before restore")

    payload = bytearray(archive.read_bytes())
    payload[len(payload) // 2] ^= 1
    archive.write_bytes(payload)

    with pytest.raises(ReleaseOperationError, match="changed before restore"):
        _assert_archive_unchanged(archive, expected, phase="before restore")


def test_role_dump_keeps_only_admin_as_authority_membership_grantor(
    tmp_path: Path,
) -> None:
    source = tmp_path / "roles.sql"
    destination = tmp_path / "sanitized.sql"
    source.write_text(
        "CREATE ROLE agent_v02_admin;\n"
        "ALTER ROLE agent_v02_admin WITH SUPERUSER LOGIN;\n"
        "CREATE ROLE quant_migrator;\n"
        "ALTER ROLE quant_migrator WITH NOLOGIN;\n"
        "CREATE ROLE quant_readonly;\n"
        "ALTER ROLE quant_readonly WITH NOLOGIN;\n"
        "CREATE ROLE quant_runtime;\n"
        "ALTER ROLE quant_runtime WITH NOLOGIN;\n"
        "ALTER ROLE quant_runtime SET row_security TO 'on';\n"
        "GRANT quant_readonly TO quant_runtime WITH INHERIT FALSE "
        "GRANTED BY agent_v02_admin;\n",
        encoding="utf-8",
    )

    facts = _sanitized_authority_role_dump(
        source=source,
        destination=destination,
        container_admin_role="agent_v02_admin",
    )

    restored = destination.read_text(encoding="utf-8")
    assert "CREATE ROLE agent_v02_admin" not in restored
    assert "ALTER ROLE agent_v02_admin WITH" not in restored
    assert "GRANTED BY agent_v02_admin" in restored
    assert facts["container_admin_lines_removed"] == 2
    assert facts["container_admin_grantor_lines_retained"] == 1

    hostile = tmp_path / "hostile.sql"
    hostile.write_text(
        source.read_text(encoding="utf-8")
        + "ALTER TABLE quant_system.runs OWNER TO agent_v02_admin;\n",
        encoding="utf-8",
    )
    with pytest.raises(ReleaseOperationError, match="outside an authority"):
        _sanitized_authority_role_dump(
            source=hostile,
            destination=tmp_path / "must-not-exist.sql",
            container_admin_role="agent_v02_admin",
        )
