# Hướng dẫn chạy EventRank trên máy local

Tài liệu này dành cho người chạy toàn bộ hệ thống trên máy của mình (WSL hoặc Linux): cào báo, lưu vào Postgres, gom
sự kiện, mở web, hỏi đáp RAG, và xem dữ liệu trực quan. Cập nhật 10/11/2026.

## Tóm tắt nhanh

```bash
make up        # bật tất cả, Ctrl+C để tắt
make status    # xem cái gì đang chạy
make down      # tắt nếu terminal chạy `make up` bị đóng ngang
```

Sau khi `make up` báo xong, mở **http://localhost:5173**.

`make dev` **không** bật tất cả: nó chỉ bật API và web, và trình duyệt Windows không vào được web vì Vite chỉ nghe
`127.0.0.1`. Dùng `make up`.

## 1. Hệ thống gồm những gì

```
 Báo (8 trang) ──► Crawler :8002 ──► Postgres :5432 ──► Worker ──► Postgres ──► API :8000 ──► Web :5173
                   (30 phút/lần)     bảng articles      (5 phút/vòng)  events,       │
                                                         embedding →    trend_scores  └─► Hỏi đáp RAG ──► Qdrant :6333
                                                         gom cụm →                                     └─► Modal (GPU)
                                                         đặt tên → xu hướng
```

| Thành phần | Cổng | Lệnh riêng | Cần gì |
|---|---|---|---|
| Postgres | 5432 | (dịch vụ hệ thống) `sudo service postgresql start` | `DATABASE_URL` trong `.env` |
| Qdrant (vector cho RAG) | 6333 | `make qdrant-up` | Docker |
| Crawler 8 báo | 8002 | `make crawler` | `CRAWLER_USER_AGENT` trong `.env` |
| Worker | — | `make worker` (lặp) · `make worker ARGS="--once"` (1 vòng) | RAM trống ≥ ~2 GB |
| API backend | 8000 | `make api` | `EVENTS_BACKEND=db` trong `.env` |
| Web React | 5173 | `cd apps/web && npm run dev -- --host 0.0.0.0` | `npm ci` đã chạy |
| Mô hình RAG (Qwen, Gemma) | — | chạy trên Modal, không bật ở máy | `RAG_*`, `MODAL_PROXY_*` trong `.env` |

## 2. Cài lần đầu

1. **Thư viện Python:** `uv sync --group embed`. Đừng chạy `uv sync` không kèm `--group embed`, cũng đừng chạy
   `make install`: cả hai gỡ PyTorch khỏi `.venv`.
2. **Thư viện web:** `cd apps/web && npm ci`.
3. **File `.env`:** `cp .env.example .env` rồi điền. Tối thiểu cần:
   `DATABASE_URL`, `EVENTS_BACKEND=db`, `CRAWLER_USER_AGENT` (tên bot + email liên hệ thật, không bắt đầu bằng
   `Mozilla/`). Muốn hỏi đáp RAG thì thêm 4 biến `MODAL_PROXY_TOKEN_ID`, `MODAL_PROXY_TOKEN_SECRET`,
   `RAG_EMBEDDING_URL`, `RAG_LLM_URL` (lấy từ `.env.client` người phụ trách RAG gửi).
4. **Postgres ≥ 16** chạy sẵn, rồi `make db-migrate`. Dữ liệu ban đầu: khôi phục bản dump của nhóm (xem
   `docs/tong-hop.md` và `docs/handoff/rag.md`). **Không dùng `pg_restore --clean` trên DB đã có tài khoản người dùng.**
5. **Docker** (Docker Desktop nếu dùng WSL, bật WSL integration) cho Qdrant. Dữ liệu Qdrant và BM25 cài theo
   `docs/handoff/rag.md`.
6. **Tài khoản admin** để vào trang quản trị:
   `uv run --group embed python -m eventrank.accounts create-user --email <email> --role admin`

## 3. Chạy hằng ngày: `make up`

`make up` làm lần lượt:

1. Kiểm Postgres kết nối được (nếu không, thử `sudo service postgresql start`) và mọi migration đã áp.
   Migration chưa áp thì chỉ cảnh báo, **không tự áp**.
2. Bật Qdrant. Trên WSL, nếu Docker chưa chạy, tự bật Docker Desktop và chờ tối đa 2 phút.
3. Bật crawler. Crawler cào theo khung 30 phút (:00 và :30, giờ VN). Khi bật, nếu khung hiện tại chưa cào thì cào
   ngay; nếu đã cào (kể cả lượt bị `make down` cắt ngang) thì đợi khung kế tiếp. `make up` in ra crawler đang cào hay
   giờ cào kế tiếp. Muốn cào ngay: `make crawl-now`.
4. Bật API, chờ đến khi `/api/trending` trả lời.
5. Bật web với `--host 0.0.0.0`, để trình duyệt Windows vào được.
6. Bật worker **chỉ khi RAM còn trống ≥ 2.000 MB** sau khi các bước trên đã chạy. Một vòng worker cần tới ~2,2 GB (đo 10/11: 852 bài).
7. In bảng tình trạng, rồi canh các dịch vụ: dịch vụ nào chết thì in 15 dòng cuối log.

Ctrl+C tắt crawler, API, web, worker. Postgres và Qdrant vẫn chạy.

Tuỳ chọn, đặt trước lệnh:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `CRAWLER=0` | 1 | Không bật crawler |
| `WORKER=0` / `WORKER=1` | auto | Không bật worker / ép bật dù RAM thấp |
| `WORKER_MIN_FREE_MB` | 2000 | Ngưỡng RAM cho `WORKER=auto` |
| `QDRANT=0` | 1 | Không bật Qdrant (trang Hỏi đáp sẽ báo chưa sẵn sàng) |
| `WEB_DIR` | `apps/web` | Thư mục frontend khác, ví dụ một worktree giao diện mới |
| `WEB_HOST` | `0.0.0.0` | Địa chỉ Vite nghe |
| `DETACH=1` | 0 | Bật xong trả terminal, dịch vụ chạy nền; tắt bằng `make down` |

Ví dụ:

```bash
WORKER=0 make up                                        # máy yếu: không chạy worker
DETACH=1 make up                                        # chạy nền
WEB_DIR=../RED-web-redesign/apps/web make up            # dùng frontend ở worktree khác
QDRANT_STOP=1 make down                                 # tắt cả Qdrant
```

Log của từng dịch vụ: `data/logs/<dịch vụ>.log`. PID: `data/run/<dịch vụ>.pid`.

### Máy ít RAM (≤ 8 GB)

API + web + crawler chiếm khoảng 1,2–1,5 GB. Worker lên tới ~2,2 GB mỗi vòng. Máy 7,6 GB đã từng treo khi bật đủ cả,
cùng VS Code và trình duyệt. Thứ tự an toàn:

```bash
CRAWLER=1 WORKER=0 make up      # cào + xem web
# … đợi crawler nạp bài (xem make ingest-status) …
make down                       # tắt API/web cho đủ RAM
make worker ARGS="--once"       # gom bài mới thành sự kiện (~1 phút cho 100 bài, ~4 phút cho 850 bài)
WORKER=0 make up                # mở lại web, API tự thấy dữ liệu mới
```

## 4. Từng phần chạy thế nào

### Cào báo

- Mỗi lượt cào ghi `data/jobs/<job>/clean_silver/<báo>.jsonl`. Báo nào cào xong mới nạp vào bảng `articles`.
  Nạp xong có file `<báo>.db-imported`.
- Bài cũ hơn 7 ngày bị bỏ (`CRAWLER_MAX_ARTICLE_AGE_DAYS`).
- Tiến độ: http://localhost:8002/crawl/jobs, hoặc `make ingest-status`.
- Đổi lịch hoặc chọn báo: http://localhost:8002/docs → `PATCH /crawl/schedule`, ví dụ
  `{"interval_minutes": 60, "sources": ["vnexpress", "tuoitre"]}`.
- Cào ngay một lượt cả 8 báo: `make crawl-now` (crawler phải đang chạy). Chỉ vài báo: `POST /crawl/jobs` với
  `{"sources": ["vnexpress"]}`.
- Tắt giữa chừng (`make down`, Ctrl+C) thì job bị đánh dấu `interrupted` và **không tự cào bù** trong cùng khung 30
  phút. Bài đã cào xong của báo nào thì đã vào DB; phần còn lại sẽ được lượt sau lấy lại (crawler lấy lùi 24 giờ).
  Chỉ khi tiến trình chết đột ngột, lần bật sau mới cào bù ngay.

### Worker

Mỗi vòng: `embed` (vector cho bài mới) → `recluster` (gom cụm, giữ `event_id` cũ) → `name` (ViT5 đặt tên cụm ≥ 2
bài, cụm 1 bài dùng tiêu đề) → `trend` (điểm nóng theo giờ). Mỗi bước ghi một dòng vào bảng `worker_runs`.
API tự nạp dữ liệu mới sau tối đa 60 giây. Chi tiết và số đo: `docs/handoff/worker.md`.

### Web và API

- Trang chủ mặc định chọn **giờ mới nhất có tin của đủ nhiều báo**. Nếu mới cào được 1–2 báo, trang chủ vẫn hiện ngày
  cũ. Dữ liệu mới xem bằng nút chuyển giờ hoặc `?t=`, ví dụ `http://localhost:5173/?t=2026-11-10T15:00:00%2B07:00`.
- **Hỏi đáp** (`/hoi-dap`) cần đăng nhập. Người dùng thường có giới hạn câu/ngày (`RAG_DAILY_LIMIT`), admin thì không.
  Câu đầu tiên sau lúc GPU nghỉ chờ **7–15 phút**, vì Modal phải khởi động GPU. GPU tự tắt sau 2 phút rảnh.
- Thử RAG không cần web:
  `make rag-search ARGS='"giá xăng tăng" --limit 5'` (BM25, chạy local, không tốn GPU);
  `make rag-ask ARGS='"câu hỏi"'` (gọi GPU).

## 5. Xem dữ liệu trực quan

### Trong web (dễ nhất)

| Trang | Xem gì |
|---|---|
| http://localhost:5173/admin/kho | Tổng quan kho: bài theo thời gian, chuyên mục, chất lượng, danh sách bài, từng báo |
| http://localhost:5173/admin/thu-thap | Tình trạng cào từng báo |
| http://localhost:5173/du-lieu/gom-cum | Bản đồ cụm sự kiện |
| http://localhost:5173/du-lieu/mo-hinh | Các mô hình đang dùng |
| http://localhost:8000/docs | Thử trực tiếp mọi API |
| http://localhost:6333/dashboard | Qdrant: collection `rag_v1_qwen_text_v1`, xem vector và payload |

Trang `/admin/*` cần tài khoản admin (mục 2, bước 6).

### Công cụ xem Postgres

Thông số kết nối lấy từ `DATABASE_URL` trong `.env`
(`postgresql://<user>:<mật khẩu>@127.0.0.1:5432/<database>`).

- **VS Code:** cài extension *PostgreSQL* (Chris Kolkman), bấm `+` thêm kết nối với host `127.0.0.1`, cổng `5432`.
  Duyệt bảng, chuột phải → *Select Top 1000*.
- **DBeaver** (khuyên dùng, chạy trên Windows): *New Connection → PostgreSQL*, host `localhost`, cổng `5432`.
  Có tab *ER Diagram* vẽ quan hệ giữa các bảng. Windows kết nối thẳng được tới Postgres trong WSL.
- **pgAdmin**: cùng thông số.
- **Dòng lệnh:** `psql "$DATABASE_URL"` (gõ `\dt` để xem bảng, `\d events` để xem cột).

### Bảng nên xem

| Bảng | Chứa gì |
|---|---|
| `articles` | Bài báo: `source`, `title`, `published_at`, `content_text` |
| `events` | Sự kiện: `display_name`, `size` (số bài), `n_sources`, `first_seen`, `status` |
| `event_articles` | Bài nào thuộc sự kiện nào (`is_medoid` = bài đại diện) |
| `trend_scores` | Điểm nóng theo giờ: `t`, `rank`, `score` |
| `worker_runs` | Lịch sử worker: `step`, `status`, `stats`, `error` |
| `crawl_runs` | Lịch sử cào từng báo |
| `rag_chunks`, `rag_conversations`, `rag_messages` | Đoạn văn cho RAG, lịch sử hỏi đáp |
| `users`, `event_bookmarks`, `event_follows` | Tài khoản và tính năng người dùng |

### Câu SQL hay dùng

```sql
-- Bài theo báo, bài mới nhất
select source, count(*) so_bai, max(published_at) moi_nhat from articles group by 1 order by 1;

-- Sự kiện mới trong 2 ngày, lớn nhất trước
select event_id, display_name, size, n_sources, first_seen
from events where first_seen > now() - interval '2 days'
order by size desc, first_seen desc limit 20;

-- Bảng xếp hạng ở giờ mới nhất
select t.rank, round(t.score::numeric, 3) diem, e.display_name, e.size
from trend_scores t join events e using (event_id)
where t.t = (select max(t) from trend_scores) order by t.rank limit 10;

-- Các bài trong một sự kiện
select a.source, a.published_at, a.title, ea.is_medoid
from event_articles ea join articles a using (article_id)
where ea.event_id = 'E20261109-6c724690' order by a.published_at;

-- Worker đã chạy gì, có lỗi không
select step, status, started_at, stats->>'seconds' giay, error from worker_runs order by started_at desc limit 10;

-- Bài mới chưa được gom vào sự kiện (worker chưa chạy tới)
select count(*) from articles a left join event_articles ea using (article_id)
where a.published_at > now() - interval '7 days' and ea.article_id is null;

-- Lịch sử cào
select source, status, started_at, n_new, n_rejected, error from crawl_runs order by started_at desc limit 20;
```

## 6. Sự cố thường gặp

| Hiện tượng | Nguyên nhân · cách xử lý |
|---|---|
| Windows mở `localhost:5173` không được | Vite nghe `127.0.0.1`. Dùng `make up`, hoặc thêm `-- --host 0.0.0.0` khi chạy `npm run dev` |
| `make up` báo cổng đang bị dùng | Có tiến trình cũ (một `make api` chạy tay). Tắt nó, hoặc để `make up` dùng luôn tiến trình đó |
| Trang chủ hiện ngày cũ | Mới có ít báo cào xong, xem mục 4 phần Web và API |
| Có bài mới nhưng web không có sự kiện mới | Worker chưa chạy (bị bỏ do RAM). Chạy `make worker ARGS="--once"` |
| Web báo 503 | DB chưa có dòng `worker_runs` step `import`. Nạp dump của nhóm hoặc `make db-import-run` |
| Hỏi đáp "chưa sẵn sàng" | Qdrant chưa bật (`make qdrant-up`), hoặc thiếu biến `RAG_*` trong `.env` |
| Hỏi đáp chờ rất lâu rồi lỗi | GPU Modal khởi động nguội. Hỏi lại sau khi GPU đã ấm |
| Hỏi đáp lỗi `generation_not_finished` | Câu trả lời dài hơn `max_output_tokens` (1.024) trong `configs/rag.yaml` |
| Máy treo, swap đầy | Quá nhiều thứ chạy cùng lúc. Xem mục 3, phần Máy ít RAM |
| `make crawler` báo thiếu `CRAWLER_USER_AGENT` | Thêm biến vào `.env` (mẫu trong `.env.example`) |
| `docker: command not found` trong WSL | Docker Desktop chưa bật hoặc chưa bật WSL integration |
