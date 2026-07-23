"""許可リストにあるホストだけを外部へ中継するSNIパススルーゲートウェイ。

443番ではTLS ClientHelloのSNIから、80番ではHTTPのHostヘッダーから接続先ホスト名を
読み取り、許可リストに一致した接続だけを本来の宛先へ中継する。TLSは終端せず、
判定後はバイト列を双方向にそのまま転送する。ホスト名を読み取れない接続は遮断する。

中継先は接続の先頭で決めた1ホストに固定されるため、同一接続の後続バイト列で
別ホストへ到達することはできない。

判定のたびに1行のJSON(時刻、ポート、ホスト、判定)を標準出力へ書く。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

ALLOWLIST_PATH = Path("/etc/agent-sandbox/policy/allowed-domains.conf")
BLOCKED_HEADER = "X-Sandbox-Blocked"

_CLIENT_READ_TIMEOUT_SECONDS = 10.0
_UPSTREAM_CONNECT_TIMEOUT_SECONDS = 10.0
_PIPE_CHUNK_BYTES = 65536
# TLSレコードの正規最大長(2^14)+互換のための余裕。
_MAX_TLS_RECORD_BYTES = 2**14 + 2048

# fatal(2) unrecognized_name(112)のTLSアラート。遮断された事実がクライアントの
# エラーメッセージ(unrecognized name)に現れる。
TLS_ALERT_UNRECOGNIZED_NAME = bytes((0x15, 0x03, 0x03, 0x00, 0x02, 0x02, 0x70))


class _ParseError(ValueError):
    """接続の先頭バイト列からホスト名を読み取れない場合に送出する。"""


# --- 許可リスト -------------------------------------------------------------
# 書式と照合の意味論はここが原本であり、agent/sandbox_check.py が同じ実装を持つ。
# 両者の一致はtestsが同一ケース集合で固定する。


class AllowlistParseError(ValueError):
    """許可リストの行が書式に従わない場合に送出する。"""


def parse_allowlist(text: str) -> tuple[str, ...]:
    """allowed-domains.confの本文を解釈し、正規化済みエントリを返す。

    1行1エントリ。空行と`#`で始まる行は無視する。エントリは完全一致のホスト名
    (`github.com`。サブドメインには一致しない)か、`*.`接頭辞のワイルドカード
    (`*.github.com`。任意の深さのサブドメインに一致し、ベースドメイン自身には
    一致しない)。照合は大文字小文字を無視する。
    """

    entries: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if any(ch.isspace() for ch in line):
            raise AllowlistParseError(f"line {lineno}: whitespace in entry: {line!r}")
        body = line[2:] if line.startswith("*.") else line
        if not body or "*" in body:
            raise AllowlistParseError(f"line {lineno}: invalid entry: {line!r}")
        entries.append(line.lower())
    return tuple(entries)


def normalize_host(host: str) -> str:
    """照合と上流接続に使うホスト名表記へ正規化する(小文字、末尾ドットなし)。"""

    return host.strip().rstrip(".").lower()


def host_matches(host: str, entry: str) -> bool:
    """1つの許可リストエントリにホスト名が一致するかを判定する。"""

    host = normalize_host(host)
    if entry.startswith("*."):
        return host.endswith(entry[1:])
    return host == entry


def is_allowed(host: str, entries: Iterable[str]) -> bool:
    """ホスト名がいずれかのエントリに一致すればTrueを返す。"""

    return any(host_matches(host, entry) for entry in entries)


def load_allowlist(path: Path) -> tuple[str, ...]:
    """許可リストを起動時に一度だけ読み込む。読めなければ例外で停止する。

    稼働中の再読込はしない。許可リストは作業リポジトリのワークツリーにあり、
    内容は管理者の編集だけでなくホスト側のgit操作(checkout、merge)でも変わる。
    反映をgatewayの再起動という明示操作に限ることで、エージェントが履歴に
    紛れ込ませた変更が人間のレビューより先に境界へ効くことを防ぐ。
    """

    return parse_allowlist(path.read_text(encoding="utf-8"))


# --- ホスト名の読み取り -------------------------------------------------------


class _Cursor:
    """境界チェック付きでバイト列を先頭から読み進める。"""

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    @property
    def remaining(self) -> int:
        return len(self._data) - self._pos

    def take(self, count: int) -> bytes:
        end = self._pos + count
        if count < 0 or end > len(self._data):
            raise _ParseError("truncated")
        value = self._data[self._pos : end]
        self._pos = end
        return value

    def uint8(self) -> int:
        return self.take(1)[0]

    def uint16(self) -> int:
        return int.from_bytes(self.take(2), "big")

    def uint24(self) -> int:
        return int.from_bytes(self.take(3), "big")


def extract_sni(record_payload: bytes) -> str | None:
    """TLSレコードのペイロードからClientHelloのserver_nameを取り出す。

    読み取れない入力にはNoneを返す(呼び出し側が遮断する)。
    """

    try:
        cursor = _Cursor(record_payload)
        if cursor.uint8() != 0x01:  # HandshakeType client_hello
            return None
        body = _Cursor(cursor.take(cursor.uint24()))
        body.take(2 + 32)  # legacy_version + random
        body.take(body.uint8())  # legacy_session_id
        body.take(body.uint16())  # cipher_suites
        body.take(body.uint8())  # legacy_compression_methods
        if body.remaining == 0:  # 拡張なし
            return None
        extensions = _Cursor(body.take(body.uint16()))
        while extensions.remaining > 0:
            extension_type = extensions.uint16()
            extension_data = _Cursor(extensions.take(extensions.uint16()))
            if extension_type != 0x0000:  # server_name以外
                continue
            names = _Cursor(extension_data.take(extension_data.uint16()))
            while names.remaining > 0:
                name_type = names.uint8()
                name = names.take(names.uint16())
                if name_type == 0x00:  # host_name
                    return name.decode("ascii")
        return None
    except (_ParseError, UnicodeDecodeError):
        return None


def parse_http_host(head: bytes) -> str | None:
    """HTTPリクエストの先頭ブロックからHostヘッダーの値(ポート部を除く)を取り出す。

    IPv6リテラル(`[::1]`など)は許可リストの対象にならないためNoneを返す。
    """

    text = head.decode("iso-8859-1")
    for line in text.split("\r\n")[1:]:
        if not line:
            break
        name, separator, value = line.partition(":")
        if separator and name.strip().lower() == "host":
            host = value.strip()
            if host.startswith("["):
                return None
            host = host.partition(":")[0].strip()
            return host or None
    return None


def blocked_http_response(host: str | None) -> bytes:
    """未許可ホストへのHTTPに返す、理由と対処を示す403応答。"""

    target = host or "(host unknown)"
    body = (
        f"[agent-sandbox] Connection to '{target}' was blocked by network policy.\n"
        "This host is not in the allowlist (policy/allowed-domains.conf).\n"
        f"Run `sandbox-check {target}` inside this container for details.\n"
        "To allow it, edit .devcontainer/policy/allowed-domains.conf on the host\n"
        "machine and restart the gateway (docker compose restart gateway).\n"
    ).encode("utf-8")
    return (
        b"HTTP/1.1 403 Forbidden\r\n"
        + f"{BLOCKED_HEADER}: policy\r\n".encode("ascii")
        + b"Content-Type: text/plain; charset=utf-8\r\n"
        + f"Content-Length: {len(body)}\r\n".encode("ascii")
        + b"Connection: close\r\n\r\n"
        + body
    )


# --- 中継 -------------------------------------------------------------------


def _log(record: dict[str, object]) -> None:
    line = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **record}
    print(json.dumps(line, ensure_ascii=False), flush=True)


def _log_decision(port: int, host: str | None, decision: str, reason: str | None = None) -> None:
    record: dict[str, object] = {"port": port, "host": host, "decision": decision}
    if reason is not None:
        record["reason"] = reason
    _log(record)


async def _close(writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(OSError):
        writer.close()
        await writer.wait_closed()


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(_PIPE_CHUNK_BYTES)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except OSError:
        pass
    finally:
        with contextlib.suppress(OSError, RuntimeError):
            writer.write_eof()


async def _relay(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
) -> None:
    """半クローズを伝えながら、両方向が終わるまでバイト列を転送する。"""

    await asyncio.gather(
        _pipe(client_reader, upstream_writer),
        _pipe(upstream_reader, client_writer),
        return_exceptions=True,
    )


async def _connect_upstream(
    host: str, port: int
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    async with asyncio.timeout(_UPSTREAM_CONNECT_TIMEOUT_SECONDS):
        return await asyncio.open_connection(host, port)


# 接続の先頭を読めなかった場合に遮断へ落とす例外の集合。
_HEAD_READ_ERRORS = (
    asyncio.IncompleteReadError,
    asyncio.LimitOverrunError,
    TimeoutError,
    OSError,
    _ParseError,
)


async def _read_tls_head(reader: asyncio.StreamReader) -> tuple[bytes, str | None]:
    header, payload = await _read_tls_record(reader)
    return header + payload, extract_sni(payload)


async def _read_http_head(reader: asyncio.StreamReader) -> tuple[bytes, str | None]:
    head = await reader.readuntil(b"\r\n\r\n")
    return head, parse_http_host(head)


class Gateway:
    def __init__(self, entries: tuple[str, ...]) -> None:
        self._entries = entries

    async def handle_tls(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await self._handle(
            443,
            reader,
            writer,
            read_head=_read_tls_head,
            blocked_response=lambda host: TLS_ALERT_UNRECOGNIZED_NAME,
            unreadable_reason="client-hello-unreadable",
        )

    async def handle_http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await self._handle(
            80,
            reader,
            writer,
            read_head=_read_http_head,
            blocked_response=blocked_http_response,
            unreadable_reason="request-head-unreadable",
        )

    async def _handle(
        self,
        port: int,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        read_head: Callable[[asyncio.StreamReader], Awaitable[tuple[bytes, str | None]]],
        blocked_response: Callable[[str | None], bytes],
        unreadable_reason: str,
    ) -> None:
        """接続1本を処理する。

        ポートによる違いは、先頭からのホスト名の読み方と遮断応答のバイト列だけであり、
        判定と中継の振る舞いは両ポートで同一とする。
        """

        try:
            try:
                async with asyncio.timeout(_CLIENT_READ_TIMEOUT_SECONDS):
                    head, raw_name = await read_head(reader)
            except _HEAD_READ_ERRORS:
                _log_decision(port, None, "block", unreadable_reason)
                return

            host = normalize_host(raw_name) if raw_name else None
            if host is None or not is_allowed(host, self._entries):
                _log_decision(port, host, "block")
                writer.write(blocked_response(host))
                with contextlib.suppress(OSError):
                    await writer.drain()
                return

            try:
                upstream_reader, upstream_writer = await _connect_upstream(host, port)
            except (TimeoutError, OSError) as error:
                _log_decision(port, host, "upstream-error", str(error))
                return
            _log_decision(port, host, "allow")
            try:
                upstream_writer.write(head)
                await upstream_writer.drain()
                await _relay(reader, writer, upstream_reader, upstream_writer)
            finally:
                await _close(upstream_writer)
        finally:
            await _close(writer)


async def _read_tls_record(reader: asyncio.StreamReader) -> tuple[bytes, bytes]:
    """TLSレコードを1つ読み、(ヘッダー, ペイロード)を返す。

    ClientHelloが先頭レコードに収まらない接続は扱わない(実際のTLSクライアントは
    1レコードで送る)。
    """

    header = await reader.readexactly(5)
    if header[0] != 0x16:  # ContentType handshake
        raise _ParseError("not a TLS handshake record")
    length = int.from_bytes(header[3:5], "big")
    if not 0 < length <= _MAX_TLS_RECORD_BYTES:
        raise _ParseError("implausible record length")
    payload = await reader.readexactly(length)
    return header, payload


async def _serve(allowlist_path: Path) -> None:
    gateway = Gateway(load_allowlist(allowlist_path))
    tls_server = await asyncio.start_server(gateway.handle_tls, "0.0.0.0", 443)
    http_server = await asyncio.start_server(gateway.handle_http, "0.0.0.0", 80)
    _log({"event": "listening", "allowlist": str(allowlist_path)})
    async with tls_server, http_server:
        await asyncio.gather(tls_server.serve_forever(), http_server.serve_forever())


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_serve(ALLOWLIST_PATH))
