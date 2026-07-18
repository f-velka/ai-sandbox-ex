# AIエージェントサンドボックスの操作と開発タスク
COMPOSE := docker compose -f .devcontainer/docker-compose.yml
VENV := .venv
PYTEST := $(VENV)/bin/pytest

.PHONY: up down reset check test test-unit test-integration typecheck lint clean init

# --- サンドボックスの操作 ------------------------------------------------------

# ビルドして起動する(初回はエージェントCLIの取得で数分かかる)。
up:
	.devcontainer/bootstrap
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

# 停止し、保存した認証情報・利用者設定・セッション・キャッシュも削除する。
reset:
	$(COMPOSE) down -v

# agentコンテナ内で境界の検査を実行する。
check:
	$(COMPOSE) exec agent sandbox-check

# サンドボックス一式をTARGETへ配置する(ホスト固有の.envとキャッシュは除く)。
init:
	@if [ -z "$(TARGET)" ]; then echo "usage: make init TARGET=<directory>"; exit 1; fi
	@if [ -e "$(TARGET)/.devcontainer" ]; then echo "init: $(TARGET)/.devcontainer already exists"; exit 1; fi
	@mkdir -p "$(TARGET)"
	tar -cf - --exclude='.env' --exclude='__pycache__' --exclude='*.pyc' .devcontainer | tar -x -C "$(TARGET)"
	@mkdir -p "$(TARGET)/workspace"
	@echo "init: created $(TARGET)/.devcontainer"
	@echo "next: cd $(TARGET) && code .   # Dev Container対応エディタで開く"
	@echo "  または: cd $(TARGET) && .devcontainer/bootstrap && docker compose -f .devcontainer/docker-compose.yml up -d --build"

# --- 開発タスク ---------------------------------------------------------------

$(PYTEST): tests/requirements.txt
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -r tests/requirements.txt

# 速い: 境界の判定ロジックのみ(コンテナ不要)。
test-unit: $(PYTEST)
	$(PYTEST) tests --ignore=tests/integration

# 遅い: 実際のコンテナ群を専用プロジェクト名で起動して検証する(要docker)。
test-integration: $(PYTEST)
	$(PYTEST) tests/integration

test: $(PYTEST)
	$(PYTEST) tests

typecheck: $(PYTEST)
	$(VENV)/bin/mypy

lint: $(PYTEST)
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache
