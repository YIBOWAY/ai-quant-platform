"""Bounded Docker execution for research-only Python factors.

Each invocation gets a fresh container and copies of only its explicit inputs.
There is no host Python fallback, repository mount, credential mount, provider,
database, account, or promotion integration. Docker is a required dependency.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[3]
_RUNNER = _ROOT / "scripts/exploration_sandbox_runner.py"
MAX_BYTES = 8 * 1024 * 1024


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records", date_format="iso", double_precision=15))


def _docker(*args, timeout=15):
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


@dataclass(frozen=True)
class DockerSandbox:
    image: str = "hqa-qlib-evaluation:0.1.0"
    timeout_seconds: float = 20

    def run(self, source: str, ohlcv: pd.DataFrame, context: dict) -> dict:
        if not 0.1 <= self.timeout_seconds <= 120:
            raise ValueError("timeout must be in [0.1, 120] seconds")
        request = {"ohlcv": records(ohlcv), "context": context}
        payload = json.dumps(request, allow_nan=False).encode()
        if len(payload) > MAX_BYTES or len(source.encode()) > 128 * 1024:
            return {"status": "not_evaluated", "reason": "input_size_limit"}
        runner_bytes = _RUNNER.read_bytes()
        identity = {
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "input_digest": digest(request),
            "runner_sha256": hashlib.sha256(runner_bytes).hexdigest(),
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "seed": 1729,
        }
        try:
            image_result = _docker("image", "inspect", self.image, "--format", "{{.Id}}")
            image_id = image_result.stdout.strip()
            if image_result.returncode or not image_id.startswith("sha256:"):
                return {"status": "not_evaluated", "reason": "local_image_unavailable", **identity}
        except (OSError, subprocess.TimeoutExpired):
            return {"status": "not_evaluated", "reason": "docker_unavailable", **identity}
        identity["image_id"] = image_id
        name = "qs-explore-" + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="qs-explore-") as temporary:
            stage = Path(temporary)
            stage.chmod(0o755)
            (stage / "request.json").write_bytes(payload)
            (stage / "factor.py").write_text(source, encoding="utf-8")
            (stage / "runner.py").write_bytes(runner_bytes)
            for path in stage.iterdir():
                path.chmod(0o444)
            args = [
                "docker",
                "run",
                "--name",
                name,
                "--pull",
                "never",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                "65534:65534",
                "--cpus",
                "1",
                "--memory",
                "512m",
                "--memory-swap",
                "512m",
                "--pids-limit",
                "32",
                "--ulimit",
                "nofile=64:64",
                "--ulimit",
                "fsize=8388608:8388608",
                "--log-driver",
                "none",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=32m",
                "--workdir",
                "/tmp",
                "--env",
                "PYTHONHASHSEED=1729",
                "--env",
                "OPENBLAS_NUM_THREADS=1",
                "--env",
                "OMP_NUM_THREADS=1",
                "--env",
                "MKL_NUM_THREADS=1",
                "--mount",
                f"type=bind,src={stage},dst=/input,readonly",
                "--mount",
                f"type=bind,src={stage / 'runner.py'},dst=/runner.py,readonly",
                "--entrypoint",
                "/usr/bin/env",
                image_id,
                "-i",
                "PATH=/usr/local/bin:/usr/bin:/bin",
                "PYTHONHASHSEED=1729",
                "OPENBLAS_NUM_THREADS=1",
                "OMP_NUM_THREADS=1",
                "MKL_NUM_THREADS=1",
                "python",
                "-B",
                "/runner.py",
            ]
            try:
                with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
                    proc = subprocess.Popen(args, stdout=out, stderr=err)
                    deadline = time.monotonic() + self.timeout_seconds
                    reason = None
                    while proc.poll() is None:
                        if time.monotonic() >= deadline:
                            reason = "timeout"
                            break
                        if max(out.tell(), err.tell()) > MAX_BYTES:
                            reason = "output_size_limit"
                            break
                        time.sleep(0.025)
                    if reason:
                        _docker("rm", "-f", name)
                        proc.kill()
                        proc.wait(timeout=5)
                        return {"status": "error", "reason": reason, **identity}
                    inspected = _docker("inspect", name)
                    if inspected.returncode:
                        return {
                            "status": "not_evaluated",
                            "reason": "isolation_not_attested",
                            **identity,
                        }
                    container = json.loads(inspected.stdout)[0]
                    host = container["HostConfig"]
                    isolation = {
                        "network_mode": host["NetworkMode"],
                        "readonly_rootfs": host["ReadonlyRootfs"],
                        "input_readonly": all(
                            not item["RW"]
                            for item in container["Mounts"]
                            if item["Destination"] in ("/input", "/runner.py")
                        ),
                        "memory_bytes": host["Memory"],
                        "pids_limit": host["PidsLimit"],
                        "nano_cpus": host["NanoCpus"],
                        "user": container["Config"]["User"],
                        "cap_drop": host["CapDrop"],
                        "security_opt": host["SecurityOpt"],
                        "bind_destinations": sorted(
                            item["Destination"]
                            for item in container["Mounts"]
                            if item["Type"] == "bind"
                        ),
                    }
                    expected = (
                        isolation["network_mode"] == "none"
                        and isolation["readonly_rootfs"]
                        and isolation["input_readonly"]
                        and isolation["memory_bytes"] == 512 * 1024 * 1024
                        and isolation["pids_limit"] == 32
                        and isolation["nano_cpus"] == 1_000_000_000
                        and isolation["user"] == "65534:65534"
                        and "ALL" in isolation["cap_drop"]
                        and "no-new-privileges" in isolation["security_opt"]
                        and isolation["bind_destinations"] == ["/input", "/runner.py"]
                    )
                    if not expected:
                        return {
                            "status": "not_evaluated",
                            "reason": "isolation_mismatch",
                            **identity,
                        }
                    identity["isolation"] = isolation
                    if proc.returncode:
                        return {
                            "status": "error",
                            "reason": "container_failed",
                            "exit_code": proc.returncode,
                            **identity,
                        }
                    out.seek(0)
                    raw = out.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        return {"status": "error", "reason": "output_size_limit", **identity}
                    response = json.loads(raw)
                    # Container output cannot override host-measured identities or isolation.
                    if response.get("status") == "ok" and isinstance(response.get("scores"), list):
                        return {"status": "ok", "scores": response["scores"], **identity}
                    return {
                        "status": "error",
                        "reason": "factor_exception",
                        "error_type": str(response.get("error_type", "unknown"))[:80],
                        **identity,
                    }
            except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
                return {"status": "not_evaluated", "reason": "sandbox_protocol_failure", **identity}
            finally:
                with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                    _docker("rm", "-f", name)
