"""gatewayの接続先ホスト名の読み取り、遮断応答、許可リストの読み込みを固定する。"""

from __future__ import annotations

from pathlib import Path

import pytest

import sni_proxy


def client_hello(server_name: str | None, *, name_type: int = 0x00) -> bytes:
    """SNI拡張を持つ(または持たない)TLS ClientHelloのレコードペイロードを組み立てる。"""

    extensions = b""
    if server_name is not None:
        name = server_name.encode("ascii")
        entry = bytes([name_type]) + len(name).to_bytes(2, "big") + name
        name_list = len(entry).to_bytes(2, "big") + entry
        extensions = b"\x00\x00" + len(name_list).to_bytes(2, "big") + name_list
    body = (
        b"\x03\x03"
        + bytes(32)  # random
        + b"\x00"  # session id長0
        + b"\x00\x02\x13\x01"  # cipher suites
        + b"\x01\x00"  # compression methods
        + len(extensions).to_bytes(2, "big")
        + extensions
    )
    return b"\x01" + len(body).to_bytes(3, "big") + body


def test_sni_hostname_is_extracted_from_client_hello() -> None:
    assert sni_proxy.extract_sni(client_hello("api.github.com")) == "api.github.com"


def test_client_hello_without_sni_yields_no_hostname() -> None:
    assert sni_proxy.extract_sni(client_hello(None)) is None


def test_non_hostname_server_name_type_is_ignored() -> None:
    assert sni_proxy.extract_sni(client_hello("github.com", name_type=0x01)) is None


def test_non_client_hello_handshake_yields_no_hostname() -> None:
    payload = b"\x02" + client_hello("github.com")[1:]

    assert sni_proxy.extract_sni(payload) is None


def test_truncated_client_hello_yields_no_hostname() -> None:
    assert sni_proxy.extract_sni(client_hello("github.com")[:20]) is None


def test_garbage_payload_yields_no_hostname() -> None:
    assert sni_proxy.extract_sni(bytes(64)) is None


def test_host_header_is_extracted_without_port() -> None:
    head = b"GET / HTTP/1.1\r\nUser-Agent: curl\r\nHost: Example.com:8080\r\n\r\n"

    assert sni_proxy.parse_http_host(head) == "Example.com"


def test_request_without_host_header_yields_no_hostname() -> None:
    head = b"GET / HTTP/1.1\r\nUser-Agent: curl\r\n\r\n"

    assert sni_proxy.parse_http_host(head) is None


def test_ipv6_literal_host_yields_no_hostname() -> None:
    head = b"GET / HTTP/1.1\r\nHost: [::1]:80\r\n\r\n"

    assert sni_proxy.parse_http_host(head) is None


def test_blocked_response_is_a_403_with_marker_header_and_reason() -> None:
    response = sni_proxy.blocked_http_response("evil.example")

    head, _, body = response.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 403 ")
    assert b"X-Sandbox-Blocked: policy" in head
    assert f"Content-Length: {len(body)}".encode("ascii") in head
    assert b"evil.example" in body
    assert b"sandbox-check" in body


def test_allowlist_is_loaded_from_file(tmp_path: Path) -> None:
    path = tmp_path / "allowed-domains.conf"
    path.write_text("github.com\n*.anthropic.com\n", encoding="utf-8")

    assert sni_proxy.load_allowlist(path) == ("github.com", "*.anthropic.com")


def test_broken_allowlist_at_startup_refuses_to_serve(tmp_path: Path) -> None:
    path = tmp_path / "allowed-domains.conf"
    path.write_text("broken entry with spaces\n", encoding="utf-8")

    with pytest.raises(sni_proxy.AllowlistParseError):
        sni_proxy.load_allowlist(path)
