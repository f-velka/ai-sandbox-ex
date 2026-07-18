# この環境について

隔離されたDev Containerです。環境の構成は`/etc/agent-sandbox/devcontainer/`から読み取れます。
構成ファイルは読み取り専用であり、変更はホスト側で行います。
エージェントCLIが自前のサンドボックスを持つ場合、その拒否はこの環境の制限とは別のものです。

# ネットワーク

このDev Containerから外部へ接続できるのは、管理者が許可したホストだけです。
遮断は、HTTPでは`X-Sandbox-Blocked`ヘッダー付きの403応答、HTTPSではTLSハンドシェイクの失敗
(unrecognized nameアラートや接続エラー)として現れます。

接続に失敗したら`sandbox-check <host>`を実行してください。遮断か障害かを判別できます。
遮断を回避しようとせず、接続先の追加が必要な場合は対象ホストと用途を利用者へ伝えてください。
許可リストはホスト側の`.devcontainer/policy/allowed-domains.conf`で管理し、編集は再起動なしで
数秒のうちに反映されます。

# 開発ツール

この環境に不足しているランタイムやCLIは、別の手段での迂回をせず、必要なパッケージと用途を
利用者へ伝えて、ホスト側の`.devcontainer/agent/Dockerfile`への追加を依頼してください。
commitにはGit identityが必要です。未設定の場合は利用者に確認し、`git config --local`で設定してください。

# コンテナ内Docker

dindプロファイルが有効な場合、`docker`(build / run / compose / buildx)を利用できます。
エンジンはこの環境専用のrootless dockerdで、ホストのDockerとは独立しています。

- コンテナ内とビルド内の外向き通信にも、上と同じ許可リストが適用されます。
- イメージの取得には対象レジストリの許可が必要です(`sandbox-check <host>`で確認)。
- `-p`で公開したポートは、この環境の`localhost`へ届きます。
- bind mount(`-v`)でこの環境と内容が一致するのは`/workspace`配下だけです。
- `--memory`等のリソース制限フラグは適用されません。

`docker`コマンドが接続エラーになる場合、dindプロファイルが無効です。
有効化(ホスト側の`.devcontainer/.env`に`COMPOSE_PROFILES=dind`)を利用者へ依頼してください。
