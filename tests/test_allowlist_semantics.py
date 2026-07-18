"""許可リストの書式と照合の意味論を、gatewayとsandbox-checkの両実装で固定する。

検査がgatewayと異なる解釈をすると、検査のokが境界の状態を保証しなくなる。
そのため同一のケース集合を両方の実装に適用する。
"""

from __future__ import annotations

from types import ModuleType
from typing import cast

import pytest

import sandbox_check
import sni_proxy


@pytest.fixture(params=[sni_proxy, sandbox_check], ids=["gateway", "sandbox-check"])
def impl(request: pytest.FixtureRequest) -> ModuleType:
    return cast(ModuleType, request.param)


def test_comments_and_blank_lines_are_ignored_and_entries_are_lowercased(
    impl: ModuleType,
) -> None:
    text = "# comment\n\ngithub.com\n  *.amazonaws.com  \nCHATGPT.com\n"

    entries = impl.parse_allowlist(text)

    assert entries == ("github.com", "*.amazonaws.com", "chatgpt.com")


@pytest.mark.parametrize(
    "line",
    ["two hosts.com", "foo*bar.com", "*.", "*"],
    ids=["whitespace", "inner-wildcard", "empty-wildcard", "bare-wildcard"],
)
def test_malformed_entry_is_rejected(impl: ModuleType, line: str) -> None:
    with pytest.raises(impl.AllowlistParseError):
        impl.parse_allowlist(line)


@pytest.mark.parametrize(
    ("host", "entry", "expected"),
    [
        ("github.com", "github.com", True),
        ("api.github.com", "github.com", False),
        ("evilgithub.com", "github.com", False),
        ("github.com.evil.com", "github.com", False),
        ("s3.amazonaws.com", "*.amazonaws.com", True),
        ("s3.us-east-1.amazonaws.com", "*.amazonaws.com", True),
        ("amazonaws.com", "*.amazonaws.com", False),
        ("notamazonaws.com", "*.amazonaws.com", False),
        ("GitHub.COM.", "github.com", True),
    ],
)
def test_host_matching_semantics(impl: ModuleType, host: str, entry: str, expected: bool) -> None:
    assert impl.host_matches(host, entry) is expected


def test_empty_allowlist_allows_nothing(impl: ModuleType) -> None:
    assert impl.is_allowed("github.com", ()) is False
