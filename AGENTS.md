# ai-sandbox-ex 開発コンテキスト

このリポジトリは、AIエージェントの操作を管理者の許可した範囲に収めるための、保証の強さが異なる二つの提供物を持つ。

- `.devcontainer/`：実行環境サンドボックス。設計と保証は`docs/design.md`が定める。
- `host-settings/`：コンテナを使えない利用者向けの製品管理設定。保証は`host-settings/README.md`が定める。

## 原則

1. 同じ意味を少ないコードと少ない概念で表し、各部品は一ファイルで読み切れる大きさに保つ。
2. 提供物ごとに仕様と検査を閉じる。二つの提供物が共有するのはREADMEの選び方と版数の規律だけであり、共通の仕様書、検査器、ポリシースキーマを作らない。
3. 検査は宣言ではなく観測に基づく。エージェントと同じ権限で操作を試行し、この参照構成を前提に ok / ng / unknown で言い切る。ポリシーやcomposeの記述を証拠として扱わない。
4. 境界はfail-closedにする。接続先ホスト名を読み取れない通信は遮断する。
5. 境界はagentの外側に置く。agentコンテナへ境界の実装、外部への経路、秘密を持ち込まない。`.devcontainer`に秘密を置かない(全体をroでagentへ見せる前提)。
6. TLSは終端しない。CAの生成と配布をこのリポジトリに持ち込まない。
7. 通信ポリシーは`policy/allowed-domains.conf`一本とする。書式と照合の意味論の原本は`gateway/sni_proxy.py`にあり、`agent/sandbox_check.py`の複製と`tests/test_allowlist_semantics.py`を同時に更新する。
8. 製品バージョンはピンする(`agent/Dockerfile`のARG、host-settingsの対応版)。版上げは、公式文書で設定キーの強制範囲を確認してから行う。

## 作業の進め方

- 変更後は`make typecheck && make lint && make test-unit`を実行する。
- 境界(docker-compose.yml、gateway、dns、sandbox_check)を変えたら`make test-integration`も実行する。
- `docs/design.md`の検査項目一覧と`run_checks()`の項目・並びを一致させる。
- テストは境界の判定の意味論を固定する最小集合に保つ。dindは統合テストの対象外であり、変更時は手動で確認する。
- docstring、コメント、文書は日本語で書く。文書は一文ごとに改行する。
