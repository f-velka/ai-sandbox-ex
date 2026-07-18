"""エージェントの名前解決をすべてゲートウェイへ向けるシンクホールDNSサーバー。

AクエリにはGATEWAY_IPを返し、HTTP通信とHTTPS通信をゲートウェイへ送り込む。
A以外のクエリには、該当するレコードがないことを示す応答を返す。
"""

from __future__ import annotations

import ipaddress
import os
import socket
import struct
from dataclasses import dataclass

_QTYPE_A = 1
_QCLASS_IN = 1
_DNS_HEADER = struct.Struct(">HHHHHH")
_FLAGS_RESPONSE_NOERROR = 0x8180  # QR=1, opcode=0, AA=0, TC=0, RD=1, RA=1, RCODE=0


class DnsParseError(ValueError):
    """受信パケットがDNSクエリとして解釈できない場合に送出する。"""


@dataclass(frozen=True)
class DnsQuestion:
    transaction_id: int
    qname: str  # 正規化済み(小文字、末尾ドットなし)
    qtype: int
    qclass: int


def parse_query(packet: bytes) -> DnsQuestion:
    """UDPで受信した生バイト列をDNSクエリとして解釈する。

    先頭の質問(QDCOUNT>=1の1問目)のみを扱う。圧縮ポインタを使った質問名は
    クライアントからのクエリでは出現しないため、対応せずエラーにする。
    """

    if len(packet) < _DNS_HEADER.size:
        raise DnsParseError("packet shorter than DNS header")
    transaction_id, _flags, qdcount, _, _, _ = _DNS_HEADER.unpack_from(packet, 0)
    if qdcount < 1:
        raise DnsParseError("no question in query")

    labels: list[str] = []
    offset = _DNS_HEADER.size
    while True:
        if offset >= len(packet):
            raise DnsParseError("truncated question name")
        length = packet[offset]
        offset += 1
        if length == 0:
            break
        if length & 0xC0:
            raise DnsParseError("compressed name not supported in query")
        label = packet[offset : offset + length]
        if len(label) != length:
            raise DnsParseError("truncated label")
        labels.append(label.decode("ascii", errors="replace"))
        offset += length

    if offset + 4 > len(packet):
        raise DnsParseError("truncated question type/class")
    qtype, qclass = struct.unpack_from(">HH", packet, offset)
    qname = ".".join(labels).lower()
    return DnsQuestion(transaction_id=transaction_id, qname=qname, qtype=qtype, qclass=qclass)


def _encode_name(name: str) -> bytes:
    if name == "":
        return b"\x00"
    out = b""
    for label in name.split("."):
        out += bytes([len(label)]) + label.encode("ascii")
    return out + b"\x00"


def build_response(question: DnsQuestion, answer_ip: str | None, ttl: int = 60) -> bytes:
    """質問への応答パケットを組み立てる。

    `answer_ip` を指定すると、そのIPを1件のAレコードとして返す。
    `None` はNOERROR / ANCOUNT=0の否定応答になる。
    """

    ancount = 1 if answer_ip is not None else 0
    header = _DNS_HEADER.pack(question.transaction_id, _FLAGS_RESPONSE_NOERROR, 1, ancount, 0, 0)
    qname_bytes = _encode_name(question.qname)
    question_section = qname_bytes + struct.pack(">HH", question.qtype, question.qclass)
    if answer_ip is None:
        return header + question_section

    rdata = socket.inet_aton(answer_ip)
    answer_section = (
        qname_bytes  # 圧縮せず質問名をそのまま繰り返す
        + struct.pack(">HHIH", _QTYPE_A, _QCLASS_IN, ttl, len(rdata))
        + rdata
    )
    return header + question_section + answer_section


def handle_query(packet: bytes, gateway_ip: str) -> bytes | None:
    """受信パケットから応答パケットを組み立てる。解釈できなければNone(無応答)。"""

    try:
        question = parse_query(packet)
    except DnsParseError:
        return None
    answer_ip = gateway_ip if question.qtype == _QTYPE_A else None
    return build_response(question, answer_ip)


def serve_forever(gateway_ip: str) -> None:  # pragma: no cover
    """UDP/53で待ち受け、受信の都度応答を組み立てて送り返す。"""

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", 53))
        while True:
            packet, addr = sock.recvfrom(512)
            response = handle_query(packet, gateway_ip)
            if response is not None:
                sock.sendto(response, addr)


if __name__ == "__main__":  # pragma: no cover
    gateway_ip = os.environ.get("GATEWAY_IP", "")
    ipaddress.ip_address(gateway_ip)
    serve_forever(gateway_ip)
