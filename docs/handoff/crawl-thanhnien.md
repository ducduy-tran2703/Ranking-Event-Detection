# Bàn giao crawler Thanh Niên — 09/11/2026

Đã tích hợp logic từ bốn script người dùng cung cấp: `crawl_list_link.py`,
`read_and_save.py`, `crawl_paper.py`, `upload_silver_to_r2.py`. Chạy trong
luồng `api.main:app` → `automation/`, dùng hàng đợi, retry/resume, chống trùng
và xuất JSONL của dự án; không phụ thuộc SQLite hay đường dẫn máy cũ.

## Các file chính

| File | Chức năng |
|---|---|
| `crawler/harvester_thanhnien.py` | 10 zone từ code cũ, endpoint `/timelinelist/{zone_id}/{page}.htm`; link tiêu đề và bài liên quan; loại media/longform và URL ngoài domain |
| `crawler/ingest_thanhnien.py` | Giữ HTML cả trang, gồm metadata ngoài thân bài |
| `crawler/silver_transformer_thanhnien.py` | `transform_record`, các selector riêng Thanh Niên, đồng tác giả, ngày đăng và meta dự phòng, loại widget/boxhighlight |
| `automation/discovery.py` | Quét timeline dùng chung với Tuổi Trẻ, chọn template/parser theo nguồn |
| `automation/config.py`, `automation/http.py`, `api/schemas.py` | Nguồn `thanhnien`, domain được phép, khoảng nghỉ và API/lịch |

Silver có đúng 9 trường theo `docs/tong-hop.md` mục 5.3:
`article_id`, `url`, `source`, `category`, `title`, `sapo`, `author`,
`published_at`, `content_text`. `source=thanhnien`; ID = SHA-256 của URL
đã chuẩn hóa HTTPS, bỏ tracking/fragment; thời gian chuyển đúng sang giờ
Việt Nam, không gắn đè `+07:00` lên giờ UTC; thiếu tác giả = `null`.
Nhãn chuyên mục kế thừa ánh xạ 10 zone của script cũ, thống nhất cách viết
`Khoa học - Công nghệ`. Không thay category của dữ liệu cũ trên R2.

Các thẻ inline được unwrap/smooth để giữ chữ bị chia bởi HTML. Giữ đoạn
ngắn và các đoạn không có thuộc tính SEO; không tự loại đoạn lặp có thể là
nội dung thật. Ưu tiên ngày trong `time[data-role=publishdate]`, sau đó meta,
rồi `.detail-time`/`.detail-date`. Thiếu tiêu đề/ngày hợp lệ thì từ chối bài.

## Chạy API và lịch

Dependency dùng chung với Tuổi Trẻ đã có trong `pyproject.toml`/`uv.lock`.
Không cần cài SQLite queue hoặc lxml cho nguồn này.

```powershell
# Thay bằng tên bot và liên hệ thật của nhóm.
$env:CRAWLER_USER_AGENT = 'EventRank-PBL/0.1 (+mailto:your-team@example.com)'
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8002 --workers 1
```

`api.main` không tự nạp `.env`; truyền biến môi trường vào tiến trình.
`make dev` chạy backend web, không khởi động crawler.

Mở `http://127.0.0.1:8002/docs`, gửi `POST /crawl/jobs` để chạy riêng Thanh Niên:

```json
{"sources": ["thanhnien"]}
```

Lịch mới mặc định gồm 8 báo (đã thêm VietnamNet và VnExpress). **Lịch đã lưu giữ nguyên**; đọc
`GET /crawl/schedule`, rồi `PATCH /crawl/schedule` với danh sách muốn chạy:

```json
{"enabled": true, "interval_minutes": 30, "sources": ["baochinhphu", "nhandan", "dantri", "qdnd", "tuoitre", "thanhnien", "vietnamnet", "vnexpress"]}
```

Theo dõi trạng thái và lỗi qua `GET /crawl/jobs/{job_id}`. Mặc định chạy
phút :00/:30 giờ Việt Nam; chỉ khi tiến trình còn chạy và máy đang thức.

Tuổi Trẻ/Thanh Niên yêu cầu User-Agent trung thực, kiểm robots.txt trước
request và giãn cách tối thiểu 2 giây (hoặc Crawl-delay lớn hơn). Robots cấm,
HTTP 403/428/429 hoặc redirect sẽ dừng nguồn trong job; không tìm cách vượt
chặn. Lịch sau có thể thử lại.

## Dữ liệu và Bronze cũ

```text
data/{bronze,silver,clean_silver}/thanhnien/<article_id>.json
data/jobs/<job_id>/{bronze,silver,clean_silver}/thanhnien.jsonl
data/state/thanhnien.json
```

JSON theo bài là dữ liệu chính; JSONL theo job chỉ chứa bài đã xử lý trong
lượt đó. Bronze đã có được dùng lại, không ghi đè. Nguồn này chưa ghi Postgres,
chưa tự cập nhật bảng xu hướng, chưa nhập queue SQLite cũ. Không upload R2.

Bronze bài chi tiết từ code cũ có thể chuyển trực tiếp sang Silver local;
đầu ra phải chưa tồn tại:

```python
from crawler.silver_transformer_thanhnien import run_silver_transform

run_silver_transform("bronze_thanhnien.jsonl", "silver_thanhnien_v2.jsonl")
```

## Kiểm thử và giới hạn

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_thanhnien.py tests/test_tuoitre.py tests/test_automation.py tests/ingest -q
```

Kết quả 09/11/2026: **100 passed, 22 skipped, 4 subtests passed**.
Các test cần Postgres bị skip khi thiếu DB test. Ruff cho các module mới,
HTTP client, config, schema và test Thanh Niên đạt. Fixture HTML tổng hợp
nằm ở `tests/fixtures/crawlers/thanhnien/`; test không gọi mạng hoặc R2.

Chưa kiểm selector, zone và kết quả crawl trên website thật trong lượt này.
Cần kiểm kết quả job vận hành đầu. Lần đầu chỉ lấy 3 trang/zone; các lượt sau
dừng khi có 2 trang liên tiếp toàn URL đã biết. Chạm giới hạn trang ở lượt
tăng dần báo partial, không tiến mốc quét. HTML không rỗng nhưng không nhận
diện được link là lỗi, không coi là danh sách rỗng. Không bảo đảm backfill
toàn bộ lịch sử; bài đã clean chưa được theo dõi sửa đổi tự động.
