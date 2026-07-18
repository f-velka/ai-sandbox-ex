"""実際のコンテナ群で、設計が保証する境界の成立を確かめる統合テスト。

専用のcomposeプロジェクト名とsubnetで起動するため、利用者が起動中のサンドボックスとは
干渉しない。終了時にはテスト用スタックと状態ボリュームを削除する。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / ".devcontainer" / "docker-compose.yml"
ALLOWLIST_PATH = REPO_ROOT / ".devcontainer" / "policy" / "allowed-domains.conf"

_COMPOSE_ENV = {
    **os.environ,
    "COMPOSE_PROJECT_NAME": "ai-sandbox-ex-test",
    "SANDBOX_SUBNET_PREFIX": "10.254.253",
}
_COMPOSE_BASE = ["docker", "compose", "-f", str(COMPOSE_FILE)]

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")


def _run(args: list[str], timeout: float, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        env=_COMPOSE_ENV,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def agent_exec(command: list[str], timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    return _run([*_COMPOSE_BASE, "exec", "-T", "agent", *command], timeout=timeout, check=False)


def _eventually(condition: Callable[[], bool], timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(2.0)
    return False


@pytest.fixture(scope="session", autouse=True)
def sandbox() -> Iterator[None]:
    _run([*_COMPOSE_BASE, "up", "-d", "--build"], timeout=1800.0)
    yield
    _run([*_COMPOSE_BASE, "down", "-v"], timeout=300.0, check=False)


def test_sandbox_check_reports_every_boundary_as_ok() -> None:
    result = agent_exec(["sandbox-check"])

    assert result.returncode == 0, f"\n{result.stdout}\n{result.stderr}"


def test_blocked_host_gets_a_403_with_the_marker_header() -> None:
    result = agent_exec(["curl", "-s", "-i", "--max-time", "30", "http://example.com/"])

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("HTTP/1.1 403")
    assert "X-Sandbox-Blocked: policy" in result.stdout


def test_allowed_host_is_reachable_over_https_with_a_real_certificate() -> None:
    result = agent_exec(["curl", "-sSI", "--max-time", "30", "https://github.com/"])

    assert result.returncode == 0, result.stderr


def test_allowlist_addition_takes_effect_without_restart() -> None:
    original = ALLOWLIST_PATH.read_text(encoding="utf-8")

    def example_is_reachable() -> bool:
        probe = agent_exec(["curl", "-sI", "--max-time", "10", "https://example.com/"])
        return probe.returncode == 0

    try:
        ALLOWLIST_PATH.write_text(original + "example.com\n", encoding="utf-8")
        assert _eventually(example_is_reachable, timeout_seconds=30.0)
    finally:
        ALLOWLIST_PATH.write_text(original, encoding="utf-8")


def test_allowlist_is_immutable_from_inside_the_agent() -> None:
    result = agent_exec(["sh", "-c", "echo x >> /etc/agent-sandbox/policy/allowed-domains.conf"])

    assert result.returncode != 0
