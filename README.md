# Ranking-Event-Detection

Nhận diện sự kiện đa nguồn & xếp hạng xu hướng tin tức tiếng Việt. Quy ước làm việc cho người và AI agent: xem [AGENTS.md](AGENTS.md).

**Người mới vào dự án: đọc [docs/huong-dan-chay-du-an.md](docs/huong-dan-chay-du-an.md)** — cài đặt, chạy, gọi API, quy trình git, xử lý sự cố.

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

Gõ `make` để xem mọi lệnh.

## Test

```bash
make test                     # test Python (dữ liệu mẫu, không gọi mạng) + lint + kiểm tra kiểu web
```
