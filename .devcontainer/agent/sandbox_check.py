#!/usr/bin/env python3
"""サンドボックスの境界をagentコンテナの内側から観測する検査コマンド。

引数なしで全項目を検査し、項目ごとに ok / ng / unknown を報告する。
ok は期待する状態の観測、ng は境界の破れの観測、unknown は観測の未完了を表す。
終了コードは、すべてokなら0、ngがあれば1、ngがなくunknownがあれば2。

ホスト名を引数に与えると、そのホストの許可状態と到達性の診断に切り替わる。

検査はこの参照構成(シンクホールDNS+SNIパススルーゲートウェイ+経路のない
internalネットワーク)を前提に観測を解釈する。たとえば外部リゾルバからの無応答は、
経路が存在しないことの確認として扱う。
"""

from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from pathlib import Path
from typing import Literal

WORKSPACE_PATH = Path("/workspace")
DEVCONTAINER_PATH = WORKSPACE_PATH / ".devcontainer"
ALLOWLIST_PATH = DEVCONTAINER_PATH / "policy" / "allowed-domains.conf"
HOST_DOCKER_SOCKETS = (Path("/var/run/docker.sock"), Path("/run/docker.sock"))
PROC_STATUS_PATH = Path("/proc/self/status")

# 未許可通信の試行に使う宛先。到達しないことだけを確かめる。
CANARY_HOSTS = ("example.com", "example.org", "example.net")
OUTSIDE_RESOLVER = "9.9.9.9"
OUTSIDE_IP = "1.1.1.1"
METADATA_ENDPOINT = "169.254.169.254"

BLOCKED_HEADER = "X-Sandbox-Blocked"
_TIMEOUT_SECONDS = 5.0

Status = Literal["ok", "ng", "unknown"]


@dataclass(frozen=True)
class Result:
    check_id: str
    status: Status
    detail: str


# --- 許可リスト(gateway/sni_proxy.py と同じ書式・同じ照合の意味論) ----------------
# gatewayと同じ判定を再現するための複製であり、両者の一致はtestsが固定する。


class AllowlistParseError(ValueError):
    """許可リストの行が書式に従わない場合に送出する。"""


def parse_allowlist(text: str) -> tuple[str, ...]:
    """allowed-domains.confの本文を解釈し、正規化済みエントリを返す。"""

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
    return host.strip().rstrip(".").lower()


def host_matches(host: str, entry: str) -> bool:
    host = normalize_host(host)
    if entry.startswith("*."):
        return host.endswith(entry[1:])
    return host == entry


def is_allowed(host: str, entries: Iterable[str]) -> bool:
    return any(host_matches(host, entry) for entry in entries)


def load_allowlist() -> tuple[str, ...] | None:
    """許可リストを読み込む。読めない、または書式が壊れている場合はNone。"""

    try:
        return parse_allowlist(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, AllowlistParseError):
        return None


def pick_probe_host(entries: tuple[str, ...]) -> str | None:
    """到達確認に使う、許可リスト先頭の完全一致エントリを返す。"""

    return next((entry for entry in entries if not entry.startswith("*.")), None)


def pick_canary(entries: tuple[str, ...]) -> str | None:
    """遮断確認に使う、許可リストに一致しない既知の外部ホストを返す。"""

    return next((host for host in CANARY_HOSTS if not is_allowed(host, entries)), None)


# --- 観測 --------------------------------------------------------------------

Https = Literal["reached", "rejected", "unreachable"]


def https_probe(host: str) -> tuple[Https, str]:
    """HTTPSで1リクエスト試み、到達、ゲートウェイによる遮断、未完了を区別する。

    どのHTTPステータスでも、応答が返ればTLSが本物の証明書で成立している(到達)。
    ゲートウェイの遮断はunrecognized_nameアラートによるTLS失敗として現れる。
    """

    try:
        connection = HTTPSConnection(host, 443, timeout=_TIMEOUT_SECONDS)
        try:
            connection.request("HEAD", "/")
            status = connection.getresponse().status
        finally:
            connection.close()
        return "reached", f"HTTP {status}"
    except ssl.SSLError as error:
        text = str(error)
        if "UNRECOGNIZED_NAME" in text.upper():
            return "rejected", "ゲートウェイがTLSアラートで遮断した"
        return "unreachable", text
    except (HTTPException, OSError) as error:
        return "unreachable", str(error) or type(error).__name__


def _build_dns_query(domain: str) -> bytes:
    """Aレコードを問い合わせるDNSパケットを組み立てる。"""

    header = struct.pack(">HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0)
    question = b""
    for label in domain.split("."):
        question += bytes([len(label)]) + label.encode("ascii")
    return header + question + b"\x00" + struct.pack(">HH", 1, 1)


# --- 検査項目 -----------------------------------------------------------------


def check_net_allowed(entries: tuple[str, ...] | None) -> Result:
    check_id = "net.allowed"
    if entries is None:
        return Result(check_id, "unknown", f"許可リスト {ALLOWLIST_PATH} を読めない")
    host = pick_probe_host(entries)
    if host is None:
        return Result(check_id, "unknown", "許可リストに完全一致エントリがなく、到達確認に使えない")
    outcome, detail = https_probe(host)
    if outcome == "reached":
        return Result(check_id, "ok", f"{host} へHTTPSで到達した ({detail})")
    if outcome == "rejected":
        return Result(check_id, "ng", f"許可済みの {host} をゲートウェイが遮断した")
    return Result(check_id, "unknown", f"{host} への観測を完了できなかった: {detail}")


def check_net_blocked_http(canary: str | None) -> Result:
    check_id = "net.blocked-http"
    if canary is None:
        return Result(check_id, "unknown", "許可リストに一致しない検査用ホストを選べない")
    try:
        connection = HTTPConnection(canary, 80, timeout=_TIMEOUT_SECONDS)
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
            blocked = response.status == 403 and response.getheader(BLOCKED_HEADER) is not None
            status = response.status
        finally:
            connection.close()
    except (HTTPException, OSError) as error:
        return Result(check_id, "unknown", f"応答を観測できなかった: {error}")
    if blocked:
        return Result(check_id, "ok", f"{canary} へのHTTPを403と{BLOCKED_HEADER}で遮断した")
    return Result(check_id, "ng", f"{canary} へのHTTPが遮断されなかった (HTTP {status})")


def check_net_blocked_tls(canary: str | None) -> Result:
    check_id = "net.blocked-tls"
    if canary is None:
        return Result(check_id, "unknown", "許可リストに一致しない検査用ホストを選べない")
    outcome, detail = https_probe(canary)
    if outcome == "rejected":
        return Result(check_id, "ok", f"{canary} へのTLSハンドシェイクが拒否された")
    if outcome == "reached":
        return Result(check_id, "ng", f"{canary} へのTLSが成立した ({detail})")
    return Result(check_id, "unknown", f"{canary} への観測を完了できなかった: {detail}")


def check_net_dns_sinkhole(entries: tuple[str, ...] | None) -> Result:
    check_id = "net.dns-sinkhole"
    names = list(CANARY_HOSTS[:2])
    if entries is not None:
        probe_host = pick_probe_host(entries)
        if probe_host is not None:
            names.append(probe_host)
    addresses: set[str] = set()
    for name in names:
        try:
            infos = socket.getaddrinfo(name, None, family=socket.AF_INET)
        except OSError as error:
            return Result(check_id, "unknown", f"{name} を解決できなかった: {error}")
        addresses.update(str(info[4][0]) for info in infos)
    if len(addresses) == 1:
        return Result(check_id, "ok", f"すべての名前が {addresses.pop()} へ解決された")
    return Result(
        check_id,
        "ng",
        f"名前ごとに異なるIPへ解決された(シンクホールが効いていない): {sorted(addresses)}",
    )


def check_net_outside_dns() -> Result:
    check_id = "net.outside-dns"
    query = _build_dns_query(CANARY_HOSTS[0])
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(3.0)
            sock.sendto(query, (OUTSIDE_RESOLVER, 53))
            sock.recvfrom(512)
    except TimeoutError:
        return Result(check_id, "ok", f"外部リゾルバ {OUTSIDE_RESOLVER} から応答がない(経路がない)")
    except OSError as error:
        return Result(check_id, "ok", f"外部リゾルバ {OUTSIDE_RESOLVER} へ送信できない: {error}")
    return Result(check_id, "ng", f"外部リゾルバ {OUTSIDE_RESOLVER} から応答が返った")


def check_net_direct_ip() -> Result:
    check_id = "net.direct-ip"
    try:
        with socket.create_connection((OUTSIDE_IP, 443), timeout=3.0):
            pass
    except ConnectionRefusedError:
        return Result(check_id, "ng", f"{OUTSIDE_IP} へ到達した(拒否応答が返った)")
    except OSError:
        return Result(check_id, "ok", f"{OUTSIDE_IP}:443 への直接接続が成立しない")
    return Result(check_id, "ng", f"{OUTSIDE_IP}:443 への直接接続が成立した")


def check_net_metadata() -> Result:
    check_id = "net.metadata"
    try:
        connection = HTTPConnection(METADATA_ENDPOINT, 80, timeout=3.0)
        try:
            connection.request("GET", "/")
            status = connection.getresponse().status
        finally:
            connection.close()
    except ConnectionRefusedError:
        return Result(check_id, "ng", f"{METADATA_ENDPOINT} へ到達した(拒否応答が返った)")
    except (HTTPException, OSError):
        return Result(check_id, "ok", f"{METADATA_ENDPOINT} へ到達しない")
    return Result(check_id, "ng", f"{METADATA_ENDPOINT} が応答した (HTTP {status})")


def _create_error_in(directory: Path) -> str | None:
    """ディレクトリでファイルの作成と削除を試み、拒否されたときのエラーを返す(成功ならNone)。"""

    probe = directory / f".sandbox-check-{uuid.uuid4().hex}"
    try:
        descriptor = os.open(str(probe), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(descriptor)
        probe.unlink()
    except OSError as error:
        return str(error)
    return None


def check_fs_workspace_writable() -> Result:
    check_id = "fs.workspace-writable"
    error = _create_error_in(WORKSPACE_PATH)
    if error is not None:
        return Result(check_id, "ng", f"{WORKSPACE_PATH} に書き込めない: {error}")
    return Result(check_id, "ok", f"{WORKSPACE_PATH} でファイルを作成と削除できた")


def check_fs_devcontainer_readonly() -> Result:
    check_id = "fs.devcontainer-readonly"
    if not ALLOWLIST_PATH.is_file():
        return Result(check_id, "unknown", f"許可リスト {ALLOWLIST_PATH} が存在しない")
    try:
        with open(ALLOWLIST_PATH, "r+b"):
            pass
        return Result(check_id, "ng", "許可リストを書き込み用に開けた")
    except OSError:
        pass
    for directory in (DEVCONTAINER_PATH, ALLOWLIST_PATH.parent):
        if _create_error_in(directory) is None:
            return Result(check_id, "ng", f"{directory} にファイルを作成できた")
    return Result(check_id, "ok", "サンドボックス構成と許可リストへの書き込みが拒否された")


def check_fs_no_docker_socket() -> Result:
    check_id = "fs.no-docker-socket"
    for path in HOST_DOCKER_SOCKETS:
        if not path.exists():
            continue
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0)
                sock.connect(str(path))
            return Result(check_id, "ng", f"ホストのDockerソケット {path} へ接続できた")
        except OSError:
            return Result(check_id, "ng", f"ホストのDockerソケット {path} が存在する")
    return Result(check_id, "ok", "ホストのDockerソケットが存在しない")


def check_priv_non_root() -> Result:
    check_id = "priv.non-root"
    uid = os.getuid()
    if uid == 0:
        return Result(check_id, "ng", "実効ユーザーがrootである")
    return Result(check_id, "ok", f"実効ユーザーID {uid} で動作している")


def check_priv_no_sudo() -> Result:
    check_id = "priv.no-sudo"
    if shutil.which("sudo") is None:
        return Result(check_id, "ok", "sudoが存在しない")
    try:
        completed = subprocess.run(
            ["sudo", "-n", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return Result(check_id, "ok", "sudoを実行できない")
    if completed.returncode == 0:
        return Result(check_id, "ng", "sudoで対話なしにrootコマンドを実行できた")
    return Result(check_id, "ok", "sudoによる無人昇格が拒否された")


def _proc_status_value(key: str) -> str | None:
    try:
        text = PROC_STATUS_PATH.read_text(encoding="ascii")
    except (OSError, UnicodeError):
        return None
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            parts = line.split()
            return parts[1] if len(parts) >= 2 else None
    return None


def check_priv_no_capabilities() -> Result:
    check_id = "priv.no-capabilities"
    value = _proc_status_value("CapEff")
    if value is None:
        return Result(check_id, "unknown", "実効capabilityを読み取れない")
    if int(value, 16) == 0:
        return Result(check_id, "ok", "実効capabilityが空である")
    return Result(check_id, "ng", f"実効capabilityが残っている (CapEff={value})")


def check_priv_no_new_privileges() -> Result:
    check_id = "priv.no-new-privileges"
    value = _proc_status_value("NoNewPrivs")
    if value is None:
        return Result(check_id, "unknown", "NoNewPrivsを読み取れない")
    if value == "1":
        return Result(check_id, "ok", "no-new-privilegesが有効である")
    return Result(check_id, "ng", "実行中の権限昇格が禁止されていない")


def run_checks() -> list[Result]:
    """全項目を検査する。項目の並びは docs/design.md の一覧と同じにする。"""

    entries = load_allowlist()
    canary = pick_canary(entries) if entries is not None else CANARY_HOSTS[0]
    return [
        check_net_allowed(entries),
        check_net_blocked_http(canary),
        check_net_blocked_tls(canary),
        check_net_dns_sinkhole(entries),
        check_net_outside_dns(),
        check_net_direct_ip(),
        check_net_metadata(),
        check_fs_workspace_writable(),
        check_fs_devcontainer_readonly(),
        check_fs_no_docker_socket(),
        check_priv_non_root(),
        check_priv_no_sudo(),
        check_priv_no_capabilities(),
        check_priv_no_new_privileges(),
    ]


def exit_code(results: list[Result]) -> int:
    statuses = {result.status for result in results}
    if "ng" in statuses:
        return 1
    if "unknown" in statuses:
        return 2
    return 0


def _print_results(results: list[Result]) -> None:
    width = max(len(result.check_id) for result in results)
    for result in results:
        print(f"[{result.status:^7}] {result.check_id:<{width}}  {result.detail}")
    counts = {
        status: sum(1 for r in results if r.status == status) for status in ("ok", "ng", "unknown")
    }
    print(f"結果: ok {counts['ok']} / ng {counts['ng']} / unknown {counts['unknown']}")


# --- ホスト診断モード ----------------------------------------------------------


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def diagnose(host_argument: str) -> int:
    """1つのホストについて、許可状態と到達性を報告する。

    通信が失敗したとき、エージェントが「境界による遮断」と「接続先や経路の障害」を
    切り分けるための入口である。
    """

    host = normalize_host(host_argument)
    print(f"[sandbox-check] host: {host}")
    if _is_ip_literal(host):
        print("IPアドレスの直接指定には経路がなく、許可リストとは無関係に常に失敗する。")
        print("許可リストにあるホスト名を使うこと。回避を試みず、必要なら利用者へ報告する。")
        return 1

    entries = load_allowlist()
    if entries is None:
        print(f"許可リスト {ALLOWLIST_PATH} を読めない。ホスト側で書式を確認すること。")
        return 2

    matches = [entry for entry in entries if host_matches(host, entry)]
    if matches:
        print(f"許可リストに一致する: {', '.join(matches)}")
    else:
        print("許可リストに一致するエントリがない。")

    outcome, detail = https_probe(host)
    print(f"HTTPS試行: {outcome} ({detail})")

    if matches and outcome == "reached":
        print("このホストへは到達できる。")
        return 0
    if matches and outcome == "rejected":
        print("許可されているのに遮断された。ホスト側で許可リストを編集した後に")
        print("gatewayを再起動したかを利用者に確認する。")
        return 1
    if matches:
        print("境界ではなく、接続先または経路の問題の可能性がある。")
        return 2
    if outcome == "reached":
        print("許可リストに一致しないのに到達した。境界の破れとして利用者へ報告すること。")
        return 1
    print("このホストは遮断されている。回避を試みないこと。")
    print("必要なら、ホスト名と用途を利用者へ伝え、ホスト側での")
    print(".devcontainer/policy/allowed-domains.conf への追加とgatewayの再起動を依頼する。")
    print("現在の許可リスト:")
    for entry in entries:
        print(f"  - {entry}")
    return 1


def main(argv: list[str]) -> int:
    if len(argv) == 1:
        results = run_checks()
        _print_results(results)
        return exit_code(results)
    if len(argv) == 2 and argv[1] not in {"-h", "--help"}:
        return diagnose(argv[1])
    print(f"usage: {Path(argv[0]).name} [<host>]", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
