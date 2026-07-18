# agentコンテナ本体。非rootユーザーと内部ネットワークによって、管理機能と外部への
# 直接経路から分離する。
#
# 素のdebianを使う: このイメージは開発ランタイム(Node/Python等)を提供しない。
# エージェントCLI(Claude Code / Codex)はネイティブバイナリで導入し、開発に必要な
# ランタイムは利用者がこのDockerfileへ追加する。
FROM debian:bookworm-slim

# 再現性と、版上げ時に管理設定スキーマとの整合を確認するため固定する。
# 版上げはこの2行を書き換えてリビルドする。
ARG CLAUDE_CODE_VERSION=2.1.202
ARG CODEX_VERSION=0.142.5

# --- 非rootユーザー dev (uid 1000) を作成。sudoは導入しない ---------------------
# ユーザー名はdev: このコンテナは人間の開発者とエージェントの両方が使う
# (composeのサービス名agentはアーキテクチャ上の役割名)。
RUN useradd --uid 1000 --create-home --shell /bin/bash dev

# --- 基本ツール ---------------------------------------------------------------
# curl/git/ca-certificates: ソース取得とHTTPS接続に必要。
# tar: Claude Code/Codexのネイティブインストーラが使う。
# procps: VS Code Remote Serverの動作に必要。
# python3: sandbox-checkの実行に必要。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         curl git ca-certificates tar procps python3 \
    && rm -rf /var/lib/apt/lists/*

# --- 組織CA(Zscaler等)をトラストストアへ導入 -----------------------------------
# 組織のプロキシが外向きTLSを再署名する環境では、certs/へ投入されたCA証明書を
# 信頼しないと上流のTLS検証が通らない。update-ca-certificatesが処理するのは
# /usr/local/share/ca-certificates直下の`.crt`のため、拡張子と置き場所を揃える。
# certs/に証明書が1枚もなくても(README.mdだけでも)失敗しない。
USER root
COPY certs/ /tmp/org-certs/
RUN find /tmp/org-certs -maxdepth 1 \( -name '*.pem' -o -name '*.crt' \) -exec sh -c \
         'for f; do b=$(basename "$f"); b=${b%.pem}; b=${b%.crt}; cp "$f" "/usr/local/share/ca-certificates/org-$b.crt"; done' sh {} + \
    && rm -rf /tmp/org-certs \
    && update-ca-certificates

# --- 追加のaptリポジトリとクライアントCLI --------------------------------------
# ghはDebian bookwormの標準リポジトリにないため、GitHub公式のaptリポジトリを追加する
# (認証はコンテナ内で `gh auth login` する)。
# docker CLI(+buildx/composeプラグイン)はdindサービスのdockerdへ接続するクライアント。
# エンジン本体はこのイメージに含まれず、接続先はcomposeのDOCKER_HOSTで固定する。
RUN apt-get update \
    && mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
         -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
         > /etc/apt/sources.list.d/github-cli.list \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
         -o /etc/apt/keyrings/docker.asc \
    && chmod go+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
         > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
         gh docker-ce-cli docker-buildx-plugin docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# --- Claude Code / Codex を非root(dev)でネイティブインストール ------------------
# 両インストーラともダウンロード後にチェックサム検証を行い、アーキテクチャ
# (x86_64/arm64)を自動検出する。
USER dev
ENV PATH="/home/dev/.local/bin:${PATH}"

# https://code.claude.com/docs/en/setup#install-a-specific-version
RUN curl -fsSL https://claude.ai/install.sh | bash -s ${CLAUDE_CODE_VERSION}

# https://developers.openai.com/codex/cli (native installer)
RUN CODEX_RELEASE=${CODEX_VERSION} CODEX_NON_INTERACTIVE=1 \
      sh -c "curl -fsSL https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/install.sh | sh"

# --- 管理設定をroot所有・644で導入(利用者設定より優先される管理配置) --------------
USER root
RUN mkdir -p /etc/claude-code /etc/codex \
    && chmod 755 /etc/claude-code /etc/codex
COPY --chown=root:root --chmod=644 agent/managed-settings.json /etc/claude-code/managed-settings.json
COPY --chown=root:root --chmod=644 agent/codex-requirements.toml /etc/codex/requirements.toml

# --- 検査コマンドと行動規範メモリ ----------------------------------------------
# sandbox-guidance.mdはClaude Codeのmanaged層(cwd非依存で必ず読まれる)と、
# Codexのグローバル層 $CODEX_HOME/AGENTS.md へ置く。
COPY --chown=root:root --chmod=755 agent/sandbox_check.py /usr/local/bin/sandbox-check
COPY --chown=root:root --chmod=644 agent/sandbox-guidance.md /etc/claude-code/CLAUDE.md

# 状態ボリューム(認証情報、利用者設定、セッション)とキャッシュボリュームを
# 非rootユーザーから利用できるようにする。初回マウント時にこの内容が複製される。
RUN mkdir -p /home/dev/.codex /home/dev/.claude /home/dev/.cache \
    && chown dev:dev /home/dev/.codex /home/dev/.claude /home/dev/.cache
COPY --chown=dev:dev --chmod=644 agent/sandbox-guidance.md /home/dev/.codex/AGENTS.md

USER dev
WORKDIR /workspace
