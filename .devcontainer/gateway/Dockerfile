# SNIパススルーゲートウェイ。標準ライブラリだけのsni_proxy.pyを動かす薄いイメージ。
# TLSを終端しないため、CA証明書の生成や配布は存在しない。
FROM python:3.12-slim-bookworm

WORKDIR /gateway
COPY gateway/sni_proxy.py ./

# 80/443をbindするためrootで動かす(境界を実装する側のコンテナであり、
# 非root要件の対象はagentコンテナである)。
CMD ["python3", "sni_proxy.py"]
