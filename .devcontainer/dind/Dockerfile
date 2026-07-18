# コンテナ内Docker(dindサービス)のイメージ。rootless dockerdを非特権で動かす。
# エンジンの版はタグで固定する。版上げはタグを書き換えてリビルドする。
FROM docker:29.6.1-dind-rootless

USER root

# --- 組織CA(Zscaler等)をトラストストアへ導入 -----------------------------------
# 内側コンテナのTLS(docker pull等)も組織プロキシで再署名される環境では、
# agentイメージと同じCA導入が必要。Alpine版update-ca-certificatesは
# /usr/local/share/ca-certificates直下の`.crt`だけを処理するため、拡張子と
# 置き場所を揃える。certs/に証明書が1枚もなくても失敗しない。
COPY certs/ /tmp/org-certs/
RUN find /tmp/org-certs -maxdepth 1 \( -name '*.pem' -o -name '*.crt' \) -exec sh -c \
         'for f; do b=$(basename "$f"); b=${b%.pem}; b=${b%.crt}; cp "$f" "/usr/local/share/ca-certificates/org-$b.crt"; done' sh {} + \
    && rm -rf /tmp/org-certs \
    && update-ca-certificates

# --- APIソケット置き場とデータ領域をrootless所有で用意 -----------------------------
# 名前付きボリュームは初回マウント時にイメージ側ディレクトリの所有権を複製する。
# 非rootのdockerdがソケットを作成し状態を書き込めるよう、先に所有権を付けておく。
RUN mkdir -p /run/agent-docker /home/rootless/.local/share/docker \
    && chown rootless:rootless /run/agent-docker /home/rootless/.local/share/docker

USER rootless
