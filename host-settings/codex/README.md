# Codex の管理要件

`requirements.toml` は、Codex が選べる実行方式を内蔵サンドボックス付きのものへ限定し、外部機能を許可制にする。

## 対応バージョン

Codex 0.142 系を対象とする。

## 設定内容

- 実行方式を `read-only` と `workspace-write` に限定し、全アクセスモードを選べなくする（`allowed_sandbox_modes`）。
- Web 検索を無効または OpenAI 管理のキャッシュに限定する（`allowed_web_search_modes`。`cached` は検索要求に応じた外部 Web へのアクセスを行わない）。
- MCP サーバーを空の許可リストから開始する（`[mcp_servers]`）。

利用する MCP サーバーは、管理者が `mcp_servers` へ追加する。

設定キーの仕様は [Codex Configuration Reference](https://developers.openai.com/codex/config-reference) で確認できる。

## 導入

OS に対応する場所へ `requirements.toml` を配置する。

- macOS と Linux：`/etc/codex/requirements.toml`
- Windows：`%ProgramData%\OpenAI\Codex\requirements.toml`

macOS と Linux での配置例:

```console
sudo install -D -o root -g root -m 644 requirements.toml /etc/codex/requirements.toml
```

Windows では管理者権限で配置し、Codex を実行するユーザーの書き込み権がないことを確認する。
施錠の対象と確認方法は [../README.md](../README.md) に従う。
