# Claude Code の管理設定

`managed-settings.json` は、Claude Code の内蔵サンドボックスを常時有効にし、外部機能を許可制にする。

## 対応バージョン

Claude Code 2.1.202 を対象とする。
内蔵サンドボックスを利用できる macOS、Linux、WSL2 で使用する。

## 設定内容

- 内蔵サンドボックスを有効にし、利用できない場合は処理を停止する（`sandbox.enabled`、`sandbox.failIfUnavailable`）。
- コマンドをサンドボックス外で再実行する機能を無効にする（`sandbox.allowUnsandboxedCommands: false`）。
- サンドボックス内の外向き通信と WebFetch を、管理設定のドメインだけに限定する（`sandbox.network.allowManagedDomainsOnly`。初期値は全拒否）。
- Web 検索を無効にする（`permissions.deny` の `WebSearch`。この権限規則はツール全体に適用され、ドメインを指定できない）。
- MCP サーバーを許可制にする（`allowManagedMcpServersOnly`、`allowedMcpServers`。初期値は全拒否）。
- Claude.ai コネクターを無効にする（`disableClaudeAiConnectors`）。
- 権限規則を管理設定だけから読み込む（`allowManagedPermissionRulesOnly`）。

作業に必要な接続先は `sandbox.network.allowedDomains` へ、利用する MCP サーバーは `allowedMcpServers` へ管理者が追加する。

設定キーの仕様は [Claude Code settings](https://code.claude.com/docs/en/settings) と
[Configure the sandboxed Bash tool](https://code.claude.com/docs/en/sandboxing) で確認できる。

## 導入

OS に対応する場所へ `managed-settings.json` を配置する。

- macOS：`/Library/Application Support/ClaudeCode/managed-settings.json`
- Linux と WSL2：`/etc/claude-code/managed-settings.json`

Linux と WSL2 での配置例:

```console
sudo install -D -o root -g root -m 644 managed-settings.json /etc/claude-code/managed-settings.json
sudo install -d -o root -g root -m 755 /etc/claude-code/managed-settings.d
```

同じ場所の `managed-settings.d` に置いたファイルも実効設定へ統合されるため、追加設定を使わない場合も空のディレクトリを管理者権限で作成して施錠する。
施錠の対象と確認方法は [../README.md](../README.md) に従う。
