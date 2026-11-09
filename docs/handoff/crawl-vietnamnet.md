# Bàn giao crawler VietnamNet — 09/11/2026

Đã đưa logic từ bốn script người dùng cung cấp (`crawl_list_link.py`,
`read_and_save.py`, `crawl_paper.py`, `upload_silver_to_r2.py`) vào luồng
`api.main:app` → `automation/`, tương tự các báo hiện có. Không chạy script
cũ khi import; không phụ thuộc đường dẫn máy cá nhân hoặc queue SQLite cũ.

## Các module và định dạng

| File | Vai trò |
|---|---|
| `crawler/harvester_vietnamnet.py` | 10 chuyên mục từ script cũ; link `-{id}.html`; loại media, domain ngoài và tracking |
| `crawler/ingest_vietnamnet.py` | Giữ HTML cả trang, bảo toàn JSON-LD và metadata ngoài thân bài |
| `crawler/silver_transformer_vietnamnet.py` | `transform_record` và chuyển Bronze JSONL cũ sang Silver local |
| `automation/discovery.py` | Phân trang VietnamNet từ `-page0`, quét tăng dần |
| `automation/config.py`, `automation/http.py`, `api/schemas.py` | Đăng ký nguồn, domain và khoảng nghỉ; nhận nguồn trong API/lịch |

Silver gồm đúng 9 trường ở `docs/tong-hop.md` mục 5.3: `article_id`, `url`,
`source`, `category`, `title`, `sapo`, `author`, `published_at`, `content_text`.
`source=vietnamnet`; ID = SHA-256 URL HTTPS đã bỏ tracking/fragment;
ngày chuyển đúng sang múi giờ Việt Nam `+07:00`; thiếu tác giả = `null`.
Mười nhãn chuyên mục giữ ánh xạ của code cũ, thống nhất cách viết
`Khoa học - Công nghệ`, không thay category của dữ liệu cũ trên R2.

Parser dùng `h1.content-detail-title`/`h1.title`, `.content-detail-sapo`,
`#maincontent`/`.maincontent`. Ngày ưu tiên JSON-LD (kể cả danh sách và
`@graph`), sau đó meta và `.bread-crumb-detail__time`/`.publish-date`.
Tác giả ưu tiên DOM, sau đó JSON-LD; giữ đồng tác giả, gộp tên trùng.
Giữ đoạn ngắn và đoạn lặp có thể là nội dung thật; loại các widget, chú thích
ảnh và boilerplate nhận diện được. Thiếu tiêu đề/ngày hợp lệ thì từ chối bài.

## Chạy

Không có dependency mới ngoài các thư viện đã thêm cho Tuổi Trẻ/Thanh Niên.
`api.main` không tự nạp `.env`; truyền User-Agent thật qua môi trường:

```powershell
# Thay tên bot và liên hệ bằng thông tin thật của nhóm.
$env:CRAWLER_USER_AGENT = 'EventRank-PBL/0.1 (+mailto:your-team@example.com)'
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8002 --workers 1
```

`make dev` vẫn chạy backend web, không khởi động crawler. Mở
`http://127.0.0.1:8002/docs`, gửi `POST /crawl/jobs` để chạy riêng VietnamNet:

```json
{"sources": ["vietnamnet"]}
```

Lịch mới mặc định có 8 nguồn (đã thêm VnExpress). **Lịch đã lưu được giữ nguyên**; đọc
`GET /crawl/schedule`, sau đó gửi `PATCH /crawl/schedule` theo nhu cầu:

```json
{"enabled": true, "interval_minutes": 30, "sources": ["baochinhphu", "nhandan", "dantri", "qdnd", "tuoitre", "thanhnien", "vietnamnet", "vnexpress"]}
```

Theo dõi `GET /crawl/jobs/{job_id}`. Lịch mặc định chạy phút :00/:30 giờ VN,
chỉ khi tiến trình và máy còn hoạt động. Giãn cách ít nhất 2 giây/request,
tăng theo Crawl-delay nếu lớn hơn; kiểm robots.txt trước request.
Robots cấm, HTTP 403/428/429 hay redirect sẽ dừng nguồn trong job, không
tìm cách vượt chặn. Lượt theo lịch sau có thể thử lại.

## Kho local và chuyển Bronze cũ

```text
data/{bronze,silver,clean_silver}/vietnamnet/<article_id>.json
data/jobs/<job_id>/{bronze,silver,clean_silver}/vietnamnet.jsonl
data/state/vietnamnet.json
```

File theo bài là bản lưu chính. JSONL theo job chỉ chứa các bài đã xử lý
trong lượt đó, không phải toàn bộ kho. Dùng lại Bronze khi phục hồi; không
ghi đè Bronze đã có. Chưa nhập SQLite queue cũ, chưa tự ghi Postgres hay cập
nhật sự kiện trên dashboard. Không upload R2.

Bronze bài chi tiết cũ có `url`, `category`, `raw_html` có thể chuyển offline
vào file đầu ra chưa tồn tại:

```python
from crawler.silver_transformer_vietnamnet import run_silver_transform

run_silver_transform("bronze_vietnamnet.jsonl", "silver_vietnamnet_v2.jsonl")
```

## Kiểm thử và giới hạn

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_vietnamnet.py tests/test_thanhnien.py tests/test_tuoitre.py tests/test_automation.py tests/ingest -q
```

Kết quả 09/11/2026: **127 passed, 22 skipped, 4 subtests passed**.
Các test Postgres skip khi thiếu DB test. Ruff cho module/test mới, HTTP
client, config và schema đạt. HTML tổng hợp ở
`tests/fixtures/crawlers/vietnamnet/`; test không gọi báo thật hoặc R2.

Chưa xác minh selector, robots và crawl trên website thật trong lượt này.
Cần theo dõi job đầu khi vận hành. Lần đầu lấy tối đa 3 trang/chuyên mục
(`page0`–`page2`), không bảo đảm quét đủ 24 giờ trước đó. Các lượt sau dừng
sau 2 trang liên tiếp toàn URL đã biết, tối đa 100 trang/chuyên mục. Chạm
giới hạn tăng dần hoặc HTML rỗng/không nhận diện link báo partial và giữ mốc
quét cũ; URL đã tìm thấy vẫn được xử lý. Quét toàn bộ link trong trang như
script gốc có thể lấy cả bài liên quan ngoài chuyên mục, nhãn kế thừa trang
tìm thấy đầu tiên. Không tự theo dõi sửa đổi bài đã clean hoặc backfill
toàn bộ lịch sử.
