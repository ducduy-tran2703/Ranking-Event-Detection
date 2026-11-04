# Ranking-Event-Detection (EventRank)

Đồ án PBL: gom các bài báo tiếng Việt của nhiều báo thành **sự kiện**, đặt tên ngắn cho mỗi sự kiện và xếp hạng độ "nóng"
theo giờ thành bảng xu hướng. Pipeline hiện chạy theo lô trên dữ liệu 6 báo đến 19/09/2026: embedding fine-tune → gom cụm →
đặt tên ViT5 → điểm xu hướng → API FastAPI (đọc thư mục kết quả hoặc Postgres) → web React.
Mọi thông tin của dự án nằm trong **một** tài liệu: [docs/tong-hop.md](docs/tong-hop.md); quy tắc cho người và AI agent:
[AGENTS.md](AGENTS.md).

## Chạy nhanh

```bash
git switch dev
make install && uv sync --group embed     # thư viện Python (uv, kèm PyTorch CPU) và JavaScript (npm)
cp .env.example .env                      # điền khoá R2 chỉ đọc; không commit .env
make dev                                  # backend :8000 + web React :5173
make test                                 # pytest + ruff + kiểm tra kiểu web (dữ liệu mẫu, không gọi mạng)
```

Chưa có khoá R2: `LAKE_BACKEND=local LAKE_LOCAL_ROOT=tests/fixtures make dev`. Phần sự kiện của web cần một lần chạy
pipeline trong `data/runs/` (`make pipeline`) hoặc Postgres (`EVENTS_BACKEND=db`). Gõ `make` để xem mọi lệnh.

## Đọc gì

| Muốn | Mục trong `docs/tong-hop.md` |
|---|---|
| Hiểu nhanh dự án, trạng thái, điều cấm | [0. Đọc nhanh](docs/tong-hop.md#0-đọc-nhanh-cho-ai-agent), [0.2 Trạng thái](docs/tong-hop.md#02-trạng-thái-từng-phần-cập-nhật-04112026) |
| Cài đặt, lệnh `make`, API | [11.1](docs/tong-hop.md#111-cài-đặt-linuxwsl-tại-gốc-repo), [11.2](docs/tong-hop.md#112-lệnh-make), [11.3](docs/tong-hop.md#113-api) |
| Chạy web demo, pipeline, nạp DB | [17.1](docs/tong-hop.md#171-chạy-web-demo), [17.2](docs/tong-hop.md#172-chạy-pipeline-sự-kiện), [17.3](docs/tong-hop.md#173-nạp-db-và-chuyển-api-sang-db) |
| Viết crawler cho một báo | [17.4](docs/tong-hop.md#174-thêm-crawler-cho-một-báo) |
| Dùng kết quả gom cụm cho RAG | [17.5](docs/tong-hop.md#175-dùng-đầu-ra-gom-cụm-để-làm-rag) |
| Định nghĩa sự kiện, hướng dẫn gán nhãn 4 mức | [4](docs/tong-hop.md#4-định-nghĩa-sự-kiện) |
| Kho dữ liệu R2, hợp đồng Silver | [5](docs/tong-hop.md#5-dữ-liệu) |
| Database Postgres | [16](docs/tong-hop.md#16-database-postgres) |
| Số đo và cách đánh giá | [10](docs/tong-hop.md#10-đánh-giá), [10.4 Bảng tổng](docs/tong-hop.md#104-bảng-tổng-mọi-số-đo-04112026) |
| Triển khai cho cả nhóm | [11.4](docs/tong-hop.md#114-triển-khai-cho-cả-nhóm) |
| Việc còn lại | [18](docs/tong-hop.md#18-việc-còn-lại-lộ-trình-hạn-chế-đã-biết) |
