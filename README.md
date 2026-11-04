# Ranking-Event-Detection

Nhận diện sự kiện đa nguồn & xếp hạng xu hướng tin tức tiếng Việt. Quy ước làm việc cho người và AI agent: xem [AGENTS.md](AGENTS.md).

**Người mới vào dự án: đọc [docs/tong-hop.md](docs/tong-hop.md) mục 11** — cài đặt, chạy, gọi API, quy trình git, xử lý sự cố.

## Chạy nhanh

```bash
make install                  # cài thư viện Python (uv) và JavaScript (npm)
cp .env.example .env          # rồi điền khoá R2 (nên dùng khoá chỉ đọc)
make dev                      # backend :8000 + web React :5173
```

| Địa chỉ | Là gì |
|---|---|
| http://127.0.0.1:5173 | Web React (`apps/web/`) |
| http://127.0.0.1:8000 | Trang kiểm soát dữ liệu nội bộ (`apps/api/static/`) — chỉ đọc |
| http://127.0.0.1:8000/docs | Tài liệu API tự sinh |

**Web EventRank** (trang chủ = bảng xu hướng "phát lại" theo giờ 01/08–19/09/2026, sự kiện, chuyên mục, dữ liệu & mô hình,
tài khoản, quản trị): cần một lần chạy pipeline trong `data/runs/` (`make pipeline`), rồi `make build && make prod` →
http://127.0.0.1:8000/. Chọn lần chạy bằng `EVENTS_RUN_DIR`; tên sự kiện 14–15/09 mặc định bị ẩn
(`EVENTS_HIDE_NAMES_WINDOW`). Bản đồ "Trực quan gom cụm": `uv run --group embed python -m eventrank.evaluation.event_map
--date 2026-09-10`. Tài khoản/quản trị đang **giả lập trên trình duyệt** (`VITE_AUTH_MOCK`, mặc định bật). Route, endpoint:
docs/tong-hop.md mục 11.3.

**Postgres + tầng Thu thập** (giai đoạn 1 của bản chạy liên tục): bảng bài báo/lần cào/đồng hồ, nạp Silver
(`make ingest-import`), phát lại Silver thay crawler (`make ingest-replay`), theo dõi (`make ingest-status`). Người viết
crawler đọc [docs/handoff/ingest.md](docs/handoff/ingest.md).

Gõ `make` để xem mọi lệnh. Triển khai cho cả nhóm truy cập qua domain: [docs/tong-hop.md](docs/tong-hop.md) mục 11.4.

## Test

```bash
make test                     # test Python (dữ liệu mẫu, không gọi mạng) + lint + kiểm tra kiểu web
make test-db                  # test cần Postgres (đặt TEST_DATABASE_URL; không có thì tự bỏ qua)
```
