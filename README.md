# ai-sandbox

AIエージェント(Claude Code、Codex)を、操作が管理者の許可した範囲から出ないDev Containerの中で動かすためのサンドボックスです。
外向き通信は許可リストにあるホストだけへ中継され、永続的な書き込みは作業ディレクトリだけに残り、エージェントは管理権限を持ちません。
制限が実際に成立していることは、検査コマンド`sandbox-check`がコンテナの内側から確かめます。

```text
agent ── internal ネットワーク ── gateway ── egress ネットワーク ── インターネット
              │                              (許可リストのホストのみ)
             dns
```

このリポジトリはサンドボックスの配布元であり、ここで直接エージェントを動かすことは想定していません。
`.devcontainer/`一式を自分のプロジェクトへコピーして使います。
設計と保証の範囲は[docs/design.md](docs/design.md)を参照してください。

## 提供物の選び方

このリポジトリには、保証の強さが異なる二つの提供物があります。

- **実行環境サンドボックス**(このREADMEの以降の内容):DockerとDev Containerを使える場合。エージェントと子プロセスの操作を、製品の外側から構造的に制限します。
- **[host-settings/](host-settings/README.md)**:コンテナを使えない場合。各製品の管理設定で内蔵サンドボックスを強制します。製品自身の強制を信頼する分、一段弱い保証です。

両者は独立に使えます。併用した場合、製品の管理設定は外側の境界に対する防御の重ね掛けになります。

## 必要なもの(導入先)

- DockerとDocker Compose
- Dev Container対応エディタ(VS Code等)。使わない場合はdocker composeで直接起動できます。

## プロジェクトへの導入

このリポジトリで次を実行すると、サンドボックス一式が導入先へ配置されます。

```bash
make init TARGET=/path/to/project
```

`TARGET/.devcontainer`と`TARGET/workspace`が作られます。
導入先はこのリポジトリに依存せず、以後の更新は再コピーで取り込みます。

## 導入先での使い方

作業対象のファイルを`workspace/`に置き(または後述の`WORKSPACE_DIR`を設定し)、次のどちらかで起動します。

**Dev Container対応エディタ**:導入先プロジェクトを開き、「Reopen in Container」を実行します。

**docker compose**:

```bash
.devcontainer/bootstrap
docker compose -f .devcontainer/docker-compose.yml up -d --build   # 初回はエージェントCLIの取得で数分かかる
docker compose -f .devcontainer/docker-compose.yml exec agent bash
```

コンテナ内で`claude`または`codex`を起動し、初回は各CLIの認証を行います。
認証情報、利用者設定、セッションは名前付きボリュームに保存され、コンテナを作り直しても保持されます(削除は`docker compose -f .devcontainer/docker-compose.yml down -v`)。

境界の検査はコンテナ起動時に自動実行されるほか、コンテナ内で`sandbox-check`を実行していつでも確かめられます。

## 接続先の追加

接続の失敗が遮断によるものかは、コンテナ内で`sandbox-check <host>`を実行すると判別できます。
許可する場合は、ホスト側で`.devcontainer/policy/allowed-domains.conf`へ1行追加します。
再起動は不要で、数秒のうちに反映されます。

## 設定

導入先の`.devcontainer/`に対して行います。

| 目的 | 場所 |
|---|---|
| 接続先の許可 | `.devcontainer/policy/allowed-domains.conf` |
| 別ディレクトリを作業対象にする | `.devcontainer/.env`に`WORKSPACE_DIR=/path/to/repo` |
| コンテナ内Dockerを使う | `.devcontainer/.env`に`COMPOSE_PROFILES=dind` |
| 言語ランタイムやCLIの追加 | `.devcontainer/agent/Dockerfile`に追記してリビルド |
| 組織CA(Zscaler等)の信頼 | `.devcontainer/certs/`に証明書を置いてリビルド |

これらの変更はホスト側で行い、コンテナ内のgitには差分として現れません。
エージェントが自分の境界の設定を書き換えられないよう、`.devcontainer/`は作業対象の外に置かれているためです。

`WORKSPACE_DIR`に`.devcontainer`を含むディレクトリ(導入先プロジェクトのルート等)は指定しないでください。
許可リストが`/workspace`経由で書き込み可能になり、境界が破れます(`sandbox-check`が検出します)。

## このリポジトリの開発

開発タスクの実行には[uv](https://docs.astral.sh/uv/)が必要です。

```bash
make test-unit          # 境界の判定ロジックの単体テスト
make test-integration   # 実コンテナでの統合テスト(要docker)
make typecheck          # mypy --strict
make lint               # ruff
```

動作確認用に、このリポジトリ自身でも`make up`(起動)と`make check`(境界の検査)が使えます。
