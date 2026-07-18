"""シンクホールDNSの応答を固定する。すべての外部名がgatewayのIPへ解決される。"""

from __future__ import annotations

import socket
import struct

import sinkhole_dns

GATEWAY_IP = "10.20.0.3"


def dns_query(name: str, qtype: int = 1, transaction_id: int = 0xBEEF) -> bytes:
    header = struct.pack(">HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
    question = b""
    for label in name.split("."):
        question += bytes([len(label)]) + label.encode("ascii")
    return header + question + b"\x00" + struct.pack(">HH", qtype, 1)


def test_a_query_for_any_name_is_answered_with_the_gateway_ip() -> None:
    response = sinkhole_dns.handle_query(dns_query("some.external.host"), GATEWAY_IP)

    assert response is not None
    transaction_id, _flags, qdcount, ancount, _, _ = struct.unpack_from(">HHHHHH", response, 0)
    assert (transaction_id, qdcount, ancount) == (0xBEEF, 1, 1)
    assert response.endswith(socket.inet_aton(GATEWAY_IP))


def test_query_name_matching_is_case_insensitive() -> None:
    question = sinkhole_dns.parse_query(dns_query("API.GitHub.COM"))

    assert question.qname == "api.github.com"


def test_non_a_query_gets_an_empty_answer() -> None:
    response = sinkhole_dns.handle_query(dns_query("some.external.host", qtype=28), GATEWAY_IP)

    assert response is not None
    ancount = struct.unpack_from(">HHHHHH", response, 0)[3]
    assert ancount == 0


def test_truncated_packet_gets_no_response() -> None:
    assert sinkhole_dns.handle_query(b"\x12\x34\x00", GATEWAY_IP) is None


def test_compressed_question_name_gets_no_response() -> None:
    packet = dns_query("github.com")
    compressed = packet[:12] + b"\xc0\x0c" + packet[-4:]

    assert sinkhole_dns.handle_query(compressed, GATEWAY_IP) is None
