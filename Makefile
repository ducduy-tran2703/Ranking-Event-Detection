# Gõ `make` để xem danh sách lệnh.
.DEFAULT_GOAL := help
API_PORT ?= 8000

help: ## Hiện danh sách lệnh
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  make %-9s %s\n", $$1, $$2}'

install: ## Cài thư viện Python và JavaScript (lần đầu, hoặc khi có người thêm thư viện)
	uv sync
	cd apps/web && npm ci

check-env: ## Kiểm tra đã có file .env chưa (tự chạy trước make api / make dev)
	@if [ ! -f .env ] && [ "$$LAKE_BACKEND" != "local" ]; then \
		echo ""; \
		echo "  Chưa có file .env nên backend không đọc được kho dữ liệu R2."; \
		echo "  Làm như sau:"; \
		echo "    cp .env.example .env"; \
		echo "    rồi điền khoá R2 vào .env  (xem docs/huong-dan-chay-du-an.md, mục 5)"; \
		echo ""; \
		echo "  Hoặc chạy bằng dữ liệu mẫu, không cần khoá:"; \
		echo "    LAKE_BACKEND=local LAKE_LOCAL_ROOT=tests/fixtures make dev"; \
		echo ""; \
		exit 1; \
	fi

api: check-env ## Chạy backend FastAPI ở cổng 8000
	uv run uvicorn apps.api.main:app --host 127.0.0.1 --port $(API_PORT) --reload

web: ## Chạy frontend React (Vite) ở cổng 5173
	cd apps/web && npm run dev

dev: check-env ## Chạy CẢ backend và frontend trong một terminal (Ctrl+C dừng cả hai)
	$(MAKE) -j2 api web

types: ## Sinh lại kiểu TypeScript sau khi sửa apps/api/schemas.py
	uv run python -c "import json; from apps.api.main import app; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))" > apps/web/openapi.json
	cd apps/web && npm run gen:types

test: ## Chạy mọi kiểm tra: test Python, lint, kiểm tra kiểu frontend
	uv run pytest -q
	uv run ruff check src apps tests
	cd apps/web && npm run typecheck

build: ## Đóng gói frontend ra apps/web/dist/
	cd apps/web && npm run build

.PHONY: help install check-env api web dev types test build
