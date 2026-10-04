"""Stable Docker resolution matching scripts/local_mac_stack.sh.

LaunchAgents do not inherit an interactive shell PATH. The local stack's
explicit override and installation paths are the research runtime contract too.
"""

import os

DOCKER_PATHS = ("/usr/local/bin/docker", "/opt/homebrew/bin/docker")


class StudyRuntimeError(RuntimeError):
    """A safe operational description; never contains provider output or context."""


def resolve_docker_executable() -> str:
    for candidate in (os.environ.get("QS_LOCAL_DOCKER_BIN", ""), *DOCKER_PATHS):
        if not candidate or not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
            continue
        if any(part in candidate for part in ("/.codex/", "/.claude/", "/ChatGPT.app/")):
            continue
        return candidate
    raise StudyRuntimeError(
        "找不到 Docker 可执行文件；已检查 QS_LOCAL_DOCKER_BIN、"
        "/usr/local/bin/docker 和 /opt/homebrew/bin/docker"
    )
