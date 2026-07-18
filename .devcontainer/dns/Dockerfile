# シンクホールDNS。標準ライブラリだけのsinkhole_dns.pyを動かす薄いイメージ。
FROM python:3.12-slim-bookworm

WORKDIR /dns
COPY dns/sinkhole_dns.py ./

# 53/udpをbindするためrootで動かす(境界を実装する側のコンテナであり、
# 非root要件の対象はagentコンテナである)。
CMD ["python3", "sinkhole_dns.py"]
