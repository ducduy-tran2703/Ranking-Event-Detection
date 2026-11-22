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
		echo "    rồi điền khoá R2 vào .env  (xem docs/tong-hop.md, mục 11.1)"; \
		echo ""; \
		echo "  Hoặc chạy bằng dữ liệu mẫu, không cần khoá:"; \
		echo "    LAKE_BACKEND=local LAKE_LOCAL_ROOT=tests/fixtures make dev"; \
		echo ""; \
		exit 1; \
	fi

api: check-env ## Chạy backend FastAPI ở cổng 8000
	# --reload-dir: chỉ theo dõi code chạy thật. Không có nó, sửa file trong tests/ hay docs/
	# cũng làm server khởi động lại và tải lại toàn bộ dữ liệu từ R2.
	uv run --group embed uvicorn apps.api.main:app --host 127.0.0.1 --port $(API_PORT) \
		--reload --reload-dir src --reload-dir apps/api

web: ## Chạy frontend React (Vite) ở cổng 5173
	cd apps/web && npm run dev

dev: check-env ## Chạy CẢ backend và frontend trong một terminal (Ctrl+C dừng cả hai)
	$(MAKE) -j2 api web

up: ## Bật TẤT CẢ: Qdrant, crawler, API, web (Windows vào được), worker nếu đủ RAM; Ctrl+C tắt (docs/huong-dan-chay.md)
	@bash infra/chay-tat-ca.sh up

down: ## Tắt mọi dịch vụ `make up` đã bật (Postgres, Qdrant vẫn chạy; QDRANT_STOP=1 để dừng Qdrant)
	@bash infra/chay-tat-ca.sh down

status: ## Xem dịch vụ nào đang chạy, địa chỉ, log, RAM trống
	@bash infra/chay-tat-ca.sh status

crawl-now: ## Cào ngay một lượt cả 8 báo (crawler :8002 phải đang chạy, ví dụ qua make up)
	@curl -sf -X POST http://127.0.0.1:8002/crawl/jobs -H 'Content-Type: application/json' -d '{}' \
		| python3 -c 'import sys, json; j = json.load(sys.stdin); print("Đã giao job", j["id"][:8], "cho", len(j["sources"]), "báo. Tiến độ: http://localhost:8002/crawl/jobs")' \
		|| echo "Không giao được: crawler chưa chạy (make up) hoặc đang có job chạy (xem http://localhost:8002/crawl/jobs)"

types: ## Sinh lại kiểu TypeScript sau khi sửa apps/api/schemas.py
	uv run --group embed python -c "import json; from apps.api.main import app; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))" > apps/web/openapi.json
	cd apps/web && npm run gen:types

test: ## Chạy mọi kiểm tra: test Python, lint, kiểm tra kiểu frontend
	uv run --group embed pytest -q
	uv run --group embed ruff check src apps tests
	cd apps/web && npm run typecheck

build: ## Đóng gói frontend ra apps/web/dist/
	cd apps/web && npm run build

prod: check-env build ## Chạy bản triển khai: MỘT cổng phục vụ cả web React lẫn API
	uv run --group embed uvicorn apps.api.main:app --host $(HOST) --port $(API_PORT)

EMBED_MODEL ?= Xenova/paraphrase-multilingual-MiniLM-L12-v2

embed: ## Embedding ngữ nghĩa cho nhãn yếu (tải ~135 MB lần đầu; chạy TRƯỚC weak-labels) → data/weak_labels/cache/
	uv run --group embed python -m eventrank.weak_labels.dense --model $(EMBED_MODEL)

weak-labels: ## Sinh nhãn yếu cặp cùng sự kiện từ data/lake/{gold,silver} → data/weak_labels/v3/
	uv run --group embed python -m eventrank.weak_labels.build --dense-model $(EMBED_MODEL)

agreement: ## So nhãn người (human_label_100.csv) với nhãn LLM: Cohen's κ + cặp lệch nhau
	uv run --group embed python -m eventrank.weak_labels.agreement

agreement-v4: ## So nhãn 4 mức người gán (data/weak_labels/v4/human_label_100.csv) với Claude: κ + cặp lệch
	uv run --group embed python -m eventrank.weak_labels.graded agree

GOLD_START ?= 2026-09-14
GOLD_END ?= 2026-09-16

gold-tool: ## Sinh công cụ gán tập vàng gom cụm (1 file HTML, mở bằng trình duyệt) → data/gold_clusters/v1/
	uv run --group embed python -m eventrank.evaluation.gold_clusters build --start $(GOLD_START) --end $(GOLD_END)

gold-review: ## Sinh màn hình duyệt cụm Claude đề xuất (sau khi agent ghi llm/output_*.json) → data/gold_clusters/v1/duyet_cum.html
	uv run --group embed python -m eventrank.evaluation.gold_review review

gold-viz: ## Trang trực quan tập vàng gom cụm (kích thước, dòng thời gian, bản đồ 2D, thử nối cặp) → data/gold_clusters/v1/truc_quan.html
	uv run --group embed --with pyvi python -m eventrank.evaluation.gold_viz

compare: ## So mô hình gốc (zero-shot) với bản fine-tune trên tập đo cặp 4 mức, CI bootstrap ghép cặp (CPU, ~3 phút lần đầu) → data/temp/compare_models/
	uv run --group embed --with pyvi python -m eventrank.evaluation.compare_models $(ARGS)

cluster: ## Gom cụm sự kiện cả kho Silver theo configs/clustering.yaml (lần đầu ~45 phút CPU để encode) → data/events/<algo_version>/
	uv run --group embed --with pyvi python -m eventrank.clustering.pipeline $(ARGS)

name: ## Đặt tên mọi sự kiện của data/events/v1 bằng ViT5 (cụm 1 bài = tiêu đề; CPU ~1 s/cụm ≥ 2 bài, có đệm) → ten_su_kien.csv
	uv run --group embed python -m eventrank.naming.predict $(ARGS)

trend: ## Điểm xu hướng mỗi giờ cho data/events/v1 theo configs/pipeline.yaml → xu_huong.csv, diem_su_kien.csv
	uv run --group embed python -m eventrank.trending.score $(ARGS)

pipeline: ## Chạy trọn: gom cụm → đặt tên → xu hướng → xuất (configs/pipeline.yaml) → data/runs/<run_id>/ (ARGS="--run-id … --start … --end …")
	uv run --group embed --with pyvi python -m eventrank.serving.pipeline $(ARGS)

events-viz: ## Trang trực quan bảng sự kiện (sau make cluster) → data/events/v1/truc_quan.html
	uv run --group embed python -m eventrank.evaluation.events_viz $(ARGS)

# ---------------------------------------------------------------- Postgres + tầng Thu thập (docs/handoff/ingest.md)
COMPOSE = docker compose --env-file .env -f infra/docker-compose.yml
INGEST = uv run --group embed python -m eventrank.ingest
SILVER_GLOB ?= data/lake/silver/*/*.jsonl
REPLAY_START ?= 2026-08-01T00:00+07:00
REPLAY_SPEED ?= 60
REPLAY_DB_ENV ?= REPLAY_DATABASE_URL

db-up: ## Bật Postgres 16 bằng Docker ở 127.0.0.1:5433 (chỉ khi máy chưa có Postgres; cần POSTGRES_PASSWORD trong .env)
	$(COMPOSE) up -d --wait

db-down: ## Tắt Postgres Docker (giữ dữ liệu trong volume)
	$(COMPOSE) down

db-migrate: ## Áp migration infra/db/migrations/ vào DATABASE_URL (chạy lại không làm gì)
	uv run --group embed python -m eventrank.common.db migrate

db-status: ## Migration nào đã áp / chưa áp / bị sửa
	uv run --group embed python -m eventrank.common.db status

db-import-run: ## Nạp một lần chạy pipeline (data/runs/<run_id>/, mặc định mới nhất) vào bảng sự kiện (ARGS="<run_dir> --replace")
	uv run --group embed python -m eventrank.serving.db_import $(ARGS)

ingest-import: ## Nạp Silver JSONL có sẵn vào DATABASE_URL (idempotent; SILVER_GLOB=…)
	$(INGEST) import-jsonl '$(SILVER_GLOB)'

ingest-replay: ## Phát lại Silver theo đồng hồ giả lập vào DB RIÊNG (REPLAY_DATABASE_URL; REPLAY_START, REPLAY_SPEED, ARGS)
	uv run --group embed python -m eventrank.common.db migrate --db-env $(REPLAY_DB_ENV)
	$(INGEST) replay --db-env $(REPLAY_DB_ENV) --start $(REPLAY_START) --speed $(REPLAY_SPEED) --glob '$(SILVER_GLOB)' $(ARGS)

worker: check-env ## Chạy worker liên tục: bài mới trong Postgres → embedding → gom lại giữ event_id → đặt tên → xu hướng (CPU; ARGS="--once" chạy 1 vòng)
	uv run --group embed --with pyvi python -m eventrank.serving.worker $(if $(ARGS),$(ARGS),--loop)

crawler: check-env ## Chạy dịch vụ cào 8 báo :8002, CÀO NGAY rồi 30 phút/lần, nạp bài vào Postgres (cần CRAWLER_USER_AGENT trong .env)
	@grep -q '^CRAWLER_USER_AGENT=.' .env || { echo "Thiếu CRAWLER_USER_AGENT trong .env (xem .env.example)"; exit 1; }
	CRAWLER_DB_SINK=1 uv run --env-file .env --group embed uvicorn api.main:app --host 127.0.0.1 --port 8002 --workers 1

ingest-status: ## Tình trạng từng báo: lần cào cuối, bài mới 1h/24h, lỗi gần nhất; đồng hồ
	$(INGEST) status

test-db: ## Chỉ chạy test cần Postgres (TEST_DATABASE_URL; role có CREATEDB) — thiếu biến thì skip
	uv run --group embed pytest -q -m db -rs

tunnel: ## Mở trang ra Internet qua Cloudflare Tunnel tạm thời (cần cài cloudflared)
	cloudflared tunnel --url http://127.0.0.1:$(API_PORT)

qdrant-up: ## Bật Qdrant local :6333/:6334 (volume riêng, không khởi động Postgres)
	docker compose -f infra/docker-compose.rag.yml up -d

qdrant-stop: ## Dừng Qdrant, giữ container và dữ liệu
	docker compose -f infra/docker-compose.rag.yml stop

qdrant-status: ## Xem trạng thái Qdrant local
	docker compose -f infra/docker-compose.rag.yml ps

rag-prepare: ## Nhập NER + chia chunk vào DB (ARGS="--ner-version … --silver-glob … --ner …")
	uv run --no-sync python -m eventrank.rag.prepare $(ARGS)

rag-chunks: ## Chia chunk từ article_ner đã có; cấu hình configs/rag.yaml
	uv run --no-sync python -m eventrank.rag.prepare --steps chunks $(ARGS)

rag-sync: ## Đồng bộ RAG một lượt: NER → chunk → Qdrant → BM25 (ARGS="--max-articles 200", "--dry-run"); có thể bật GPU Modal
	uv run --no-sync python -m eventrank.rag.sync $(ARGS)

rag-bm25: ## Dựng hoặc dùng lại snapshot BM25 local từ Postgres
	uv run --no-sync python -m eventrank.rag.bm25 build $(ARGS)

rag-search: ## Tìm BM25 (ARGS='"câu hỏi" --limit 5 --source vnexpress')
	uv run --no-sync python -m eventrank.rag.bm25 search $(ARGS)

rag-dense: ## Index Qwen vào Qdrant (ARGS='--pilot 32' để thử trước)
	uv run --no-sync python -m eventrank.rag.dense build $(ARGS)

rag-dense-search: ## Dense search + hydrate từ Postgres
	uv run --no-sync python -X utf8 -m eventrank.rag.dense search $(ARGS)

rag-hybrid-search: ## BM25 + dense RRF; ARGS='"câu hỏi" --limit 10 --trace data/rag/reports/NEW.json'
	uv run --no-sync python -X utf8 -m eventrank.rag.hybrid search $(ARGS)

rag-tokenizer: ## Tải tokenizer Gemma (không tải model weights)
	uv run --no-sync python -X utf8 -m eventrank.rag.token_budget prepare

rag-ask: ## Hỏi đáp snapshot có citation; ARGS='"câu hỏi" --trace data/rag/reports/NEW.json'
	uv run --no-sync python -X utf8 -m eventrank.rag.pipeline ask $(ARGS)

rag-api: ## API RAG local :8001, không nạp Silver/R2
	uv run --no-sync python -m uvicorn apps.api.rag:app --host 127.0.0.1 --port 8001

rag-modal-deploy: ## Deploy hai API model có proxy auth; xuất .env.client cho nhóm
	uv run --no-sync python -m eventrank.rag.modal_setup deploy

rag-modal-cache: ## Tải trọng số model vào Modal Volume bằng CPU
	uv run --no-sync python -m eventrank.rag.modal_setup cache

rag-model-smoke: ## Gọi thử embedding và LLM thật (khởi động GPU khi cần)
	uv run --no-sync python -X utf8 -m eventrank.rag.modal_setup smoke

.PHONY: help install check-env api web dev up down status crawl-now types test build prod tunnel weak-labels agreement agreement-v4 embed compare cluster events-viz name trend pipeline \
	db-up db-down db-migrate db-status db-import-run ingest-import ingest-replay ingest-status crawler worker test-db \
	qdrant-up qdrant-stop qdrant-status rag-prepare rag-chunks rag-sync rag-bm25 rag-search rag-dense rag-dense-search rag-hybrid-search \
	rag-modal-deploy rag-modal-cache rag-model-smoke rag-tokenizer rag-ask rag-api
