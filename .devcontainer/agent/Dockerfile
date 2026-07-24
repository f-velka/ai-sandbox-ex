# syntax=docker/dockerfile:1
# agentコンテナ本体。非rootユーザーと内部ネットワークによって、管理機能と外部への
# 直接経路から分離する。
#
# 素のdebianを使う: このイメージは開発ランタイム(Node/Python等)を提供しない。
# エージェントCLI(Claude Code / Codex)はネイティブバイナリで導入し、開発に必要な
# ランタイムは利用者が末尾の「利用者拡張」へ追記する。
#
# このファイルは「管理領域」と「利用者拡張」の2部構成。管理領域はサンドボックスの
# 前提(非rootユーザー、CA、検査コマンド、管理設定)を作る部分で、変更しない。
FROM debian:bookworm-slim

# ==============================================================================
# 管理領域 — ここから「利用者拡張」までは変更しない
# ==============================================================================

# --- 非rootユーザー dev (uid 1000) を作成。sudoは導入しない ---------------------
# ユーザー名はdev: このコンテナは人間の開発者とエージェントの両方が使う
# (composeのサービス名agentはアーキテクチャ上の役割名)。
RUN useradd --uid 1000 --create-home --shell /bin/bash dev

# --- 基本ツール ---------------------------------------------------------------
# curl/git/ca-certificates: ソース取得とHTTPS接続に必要。
# tar: Claude Code/Codexのネイティブインストーラが使う。
# procps: VS Code Remote Serverの動作に必要。
# python3: sandbox-checkの実行に必要。
# bubblewrap: Claude Code/Codexが起動するコマンドへLinuxサンドボックスを適用する。
# socat: Claude Codeのsandboxがネットワーク中継に使う(欠けると起動を拒否する)。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         curl git ca-certificates tar procps python3 bubblewrap socat \
    && rm -rf /var/lib/apt/lists/*

# --- 組織CA(Zscaler等)をトラストストアへ導入 -----------------------------------
# 組織のプロキシが外向きTLSを再署名する環境では、certs/へ投入されたCA証明書を
# 信頼しないと上流のTLS検証が通らない。update-ca-certificatesが処理するのは
# /usr/local/share/ca-certificates直下の`.crt`のため、拡張子と置き場所を揃える。
# certs/に証明書が1枚もなくても(README.mdだけでも)失敗しない。
COPY certs/ /tmp/org-certs/
RUN <<'EOF'
set -eu
for f in /tmp/org-certs/*.pem /tmp/org-certs/*.crt; do
    [ -e "$f" ] || continue
    b=$(basename "$f")
    b=${b%.pem}
    b=${b%.crt}
    cp "$f" "/usr/local/share/ca-certificates/org-$b.crt"
done
rm -rf /tmp/org-certs
update-ca-certificates
EOF

# --- 追加のaptリポジトリとクライアントCLI --------------------------------------
# ghはDebian bookwormの標準リポジトリにないため、GitHub公式のaptリポジトリを追加する
# (認証はコンテナ内で `gh auth login` する)。
# docker CLI(+buildx/composeプラグイン)はdindサービスのdockerdへ接続するクライアント。
# エンジン本体はこのイメージに含まれず、接続先はcomposeのDOCKER_HOSTで固定する。
RUN <<'EOF'
set -eu
mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    -o /etc/apt/keyrings/githubcli-archive-keyring.gpg
curl -fsSL https://download.docker.com/linux/debian/gpg \
    -o /etc/apt/keyrings/docker.asc
chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg /etc/apt/keyrings/docker.asc
arch=$(dpkg --print-architecture)
echo "deb [arch=$arch signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list
echo "deb [arch=$arch signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
    > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y --no-install-recommends \
    gh docker-ce-cli docker-buildx-plugin docker-compose-plugin
rm -rf /var/lib/apt/lists/*
EOF

# --- 検査コマンドと行動規範メモリ ----------------------------------------------
# sandbox-guidance.mdはClaude Codeのmanaged層(cwd非依存で必ず読まれる)と、
# Codexのグローバル層 $CODEX_HOME/AGENTS.md へ置く。
RUN mkdir -p -m 755 /etc/claude-code /etc/codex
COPY --chmod=755 agent/sandbox_check.py /usr/local/bin/sandbox-check
COPY --chmod=644 agent/sandbox-guidance.md /etc/claude-code/CLAUDE.md

# 状態ボリューム(認証情報、利用者設定、セッション)を非rootユーザーから
# 利用できるようにする。初回マウント時にこの内容が複製される。
RUN mkdir -p /home/dev/.codex /home/dev/.claude \
    && chown dev:dev /home/dev/.codex /home/dev/.claude
COPY --chown=dev:dev --chmod=644 agent/sandbox-guidance.md /home/dev/.codex/AGENTS.md

# --- Claude Code / Codex -------------------------------------------------------
# 再現性と、バージョン更新時に管理設定スキーマとの整合を確認するためバージョンを固定する。
# バージョン引数を直前に置き、共通ツールのビルドキャッシュをバージョン更新後も再利用する。
#
# バージョン固定は本体を状態ボリュームのマウント先の外に置くことで成立する:
# マウント先に入ると初回マウントで複製された古いバージョンがリビルド後も使われ続ける。
# 自己更新はmanaged設定(DISABLE_UPDATES)で禁止し、バージョンはこのファイルだけが決める。
ENV PATH="/home/dev/.local/bin:${PATH}"

# Claude Codeの配置先 ~/.local はボリュームのマウント先ではないため、既定のままでよい
# (マウント先は ~/.claude ~/.codex のみ)。
ARG CLAUDE_CODE_VERSION=2.1.218
# https://code.claude.com/docs/en/setup#install-a-specific-version
USER dev
RUN curl -fsSL https://claude.ai/install.sh | bash -s ${CLAUDE_CODE_VERSION}
USER root

# Codexの既定の配置先 CODEX_HOME(~/.codex) はボリュームのマウント先のため、
# イメージ領域 /opt/codex へ移す。
ARG CODEX_VERSION=0.145.0
# https://developers.openai.com/codex/cli (native installer)
RUN mkdir -p /opt/codex \
    && CODEX_HOME=/opt/codex \
       CODEX_INSTALL_DIR=/usr/local/bin \
       CODEX_RELEASE=${CODEX_VERSION} \
       CODEX_NON_INTERACTIVE=1 \
       sh -c "curl -fsSL https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/install.sh | sh"

# 更新禁止を含む管理設定は、指定バージョンのインストールを終えてから配置する。
COPY --chmod=644 agent/managed-settings.json /etc/claude-code/managed-settings.json
COPY --chmod=644 agent/codex-requirements.toml /etc/codex/requirements.toml

# ==============================================================================
# 利用者拡張 — 開発に必要なランタイムやツールはここへ自由に追記する
# ==============================================================================
# この時点のUSERはroot。末尾のUSER devが実行ユーザーを戻すため、devユーザー向けの
# 導入(例2)以外はUSERの切り替えを書かなくてよい。
#
# 例1: aptパッケージを足す
#   RUN <<'EOF'
#   set -eu
#   apt-get update
#   apt-get install -y --no-install-recommends jq
#   rm -rf /var/lib/apt/lists/*
#   EOF
#
# 例2: devユーザーのホームへツールを導入する
#   USER dev
#   RUN curl -LsSf https://astral.sh/uv/install.sh | sh
#   USER root



# ==============================================================================
USER dev
WORKDIR /workspace
