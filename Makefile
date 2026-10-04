# Gõ `make` để xem danh sách lệnh.
.DEFAULT_GOAL := help
API_PORT ?= 8000
HOST ?= 127.0.0.1

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
	# --reload-dir: chỉ theo dõi code chạy thật. Không có nó, sửa file trong tests/ hay docs/
	# cũng làm server khởi động lại và tải lại toàn bộ dữ liệu từ R2.
	uv run uvicorn apps.api.main:app --host 127.0.0.1 --port $(API_PORT) \
		--reload --reload-dir src --reload-dir apps/api

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

prod: check-env build ## Chạy bản triển khai: MỘT cổng phục vụ cả web React lẫn API
	uv run uvicorn apps.api.main:app --host $(HOST) --port $(API_PORT)

EMBED_MODEL ?= Xenova/paraphrase-multilingual-MiniLM-L12-v2

embed: ## Embedding ngữ nghĩa cho nhãn yếu (tải ~135 MB lần đầu; chạy TRƯỚC weak-labels) → data/weak_labels/cache/
	uv run --group embed python -m eventrank.weak_labels.dense --model $(EMBED_MODEL)

weak-labels: ## Sinh nhãn yếu cặp cùng sự kiện từ data/lake/{gold,silver} → data/weak_labels/v3/
	uv run --group embed python -m eventrank.weak_labels.build --dense-model $(EMBED_MODEL)

agreement: ## So nhãn người (human_label_100.csv) với nhãn LLM: Cohen's κ + cặp lệch nhau
	uv run python -m eventrank.weak_labels.agreement

tunnel: ## Mở trang ra Internet qua Cloudflare Tunnel tạm thời (cần cài cloudflared)
	cloudflared tunnel --url http://127.0.0.1:$(API_PORT)

.PHONY: help install check-env api web dev types test build prod tunnel weak-labels agreement embed
