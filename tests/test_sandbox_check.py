"""sandbox-checkの結果の集約と、検査に使うホストの選び方を固定する。"""

from __future__ import annotations

import sandbox_check
from sandbox_check import Result


def test_all_ok_results_exit_with_zero() -> None:
    results = [Result("a", "ok", ""), Result("b", "ok", "")]

    assert sandbox_check.exit_code(results) == 0


def test_any_violation_exits_with_one_even_when_others_are_unknown() -> None:
    results = [Result("a", "ok", ""), Result("b", "unknown", ""), Result("c", "ng", "")]

    assert sandbox_check.exit_code(results) == 1


def test_unfinished_observation_without_violation_exits_with_two() -> None:
    results = [Result("a", "ok", ""), Result("b", "unknown", "")]

    assert sandbox_check.exit_code(results) == 2


def test_canary_is_a_host_the_allowlist_does_not_allow() -> None:
    assert sandbox_check.pick_canary(("example.com", "github.com")) == "example.org"


def test_no_canary_is_available_when_the_allowlist_covers_them_all() -> None:
    assert sandbox_check.pick_canary(("example.com", "example.org", "example.net")) is None


def test_reachability_probe_uses_the_first_exact_entry() -> None:
    assert (
        sandbox_check.pick_probe_host(("*.github.com", "api.anthropic.com")) == "api.anthropic.com"
    )


def test_no_probe_host_is_available_from_wildcards_only() -> None:
    assert sandbox_check.pick_probe_host(("*.github.com",)) is None
