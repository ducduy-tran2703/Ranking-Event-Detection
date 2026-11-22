# Bàn giao crawler VnExpress — 09/11/2026

Đã tích hợp logic từ bốn script người dùng cung cấp: `crawl_list_link.py`,
`real_and_save.py`, `crawl_paper.py`, `upload_silver_to_r2.py`. Chạy trong
`api.main:app` → `automation/`, dùng queue, retry/resume, lịch và xuất JSONL
chung; không phụ thuộc SQLite hoặc đường dẫn máy cũ. Import module không
chạy crawl hay upload.

## Module và hợp đồng

| File | Chức năng |
|---|---|
| `crawler/harvester_vnexpress.py` | 10 chuyên mục của script cũ; trang đầu nguyên URL, tiếp theo `-p2`, `-p3`; link tiêu đề trong `article` |
| `crawler/ingest_vnexpress.py` | Giữ HTML cả trang để bảo toàn metadata bên ngoài thân bài |
| `crawler/silver_transformer_vnexpress.py` | Tiêu đề, sapo, ngày, tác giả và `article.fck_detail p.Normal` → Silver |
| `automation/discovery.py` | Dùng vòng quét category chung với VietnamNet, chọn URL/parser theo nguồn |
| `automation/config.py`, `automation/http.py`, `api/schemas.py` | Nguồn `vnexpress`, domain hợp lệ, khoảng nghỉ và API/lịch |

Silver có 9 trường theo `docs/tong-hop.md` mục 5.3: `article_id`, `url`,
`source`, `category`, `title`, `sapo`, `author`, `published_at`, `content_text`.
`source=vnexpress`, ID = SHA-256 URL HTTPS đã bỏ tracking/fragment; thời gian
đổi đúng sang giờ Việt Nam `+07:00`, thiếu tác giả = `null`. Mười chuyên mục
kế thừa nhãn ánh xạ từ code cũ, thống nhất `Khoa học - Công nghệ`; không thay
category trên R2. URL phải kết thúc bằng `-{id}.html`, đúng domain; loại
`/video/`, `/podcast/`, `/photo/`, `/interactive/`.

Tiêu đề `h1.title-detail`, sapo `.description`; ngày ưu tiên meta `pubdate`
hoặc `datePublished`, sau đó `span.date`. Lấy tác giả từ `strong` trong dòng
căn phải của bài, tách credit ảnh nếu bị dính; hỗ trợ `width-detail-photo`
cho Bronze cũ. Thiếu tác giả không tự điền tên báo. Bỏ dòng tác giả khỏi
thân bài; loại widget, caption, boilerplate; giữ đoạn ngắn và đoạn lặp có
thể là nội dung thật. Thiếu tiêu đề/ngày hợp lệ thì từ chối bài.

## Chạy và lịch đã lưu

Không thêm dependency ngoài bộ crawler đã tích hợp. Truyền User-Agent thật
qua môi trường (`api.main` không tự nạp `.env`):

```powershell
# Thay tên bot và liên hệ bằng thông tin thật của nhóm.
$env:CRAWLER_USER_AGENT = 'EventRank-PBL/0.1 (+mailto:your-team@example.com)'
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8002 --workers 1
```

`make dev` chạy backend web, không khởi động crawler. Mở
`http://127.0.0.1:8002/docs`; `POST /crawl/jobs` để chạy riêng:

```json
{"sources": ["vnexpress"]}
```

Lịch mới mặc định có 8 nguồn. **Lịch đã lưu được giữ nguyên**; đọc
`GET /crawl/schedule`, rồi gửi `PATCH /crawl/schedule` với danh sách cần chạy:

```json
{"enabled": true, "interval_minutes": 30, "sources": ["baochinhphu", "nhandan", "dantri", "qdnd", "tuoitre", "thanhnien", "vietnamnet", "vnexpress"]}
```

Theo dõi `GET /crawl/jobs/{job_id}`. Mặc định chạy phút :00/:30 giờ VN,
chỉ khi máy thức và tiến trình còn chạy. Kiểm robots.txt trước request;
giãn cách ít nhất 2 giây, theo Crawl-delay nếu lớn hơn. Redirect hoặc HTTP
403/428/429 dừng **cả nguồn** trong job với trạng thái `blocked`, không theo
Location, không tiếp tục danh mục khác, không đổi endpoint để vượt chặn.
URL đã tìm thấy vẫn giữ pending, mốc quét không tiến. Lượt lịch sau có thể
thử lại; muốn ngừng thử thì bỏ nguồn khỏi lịch hoặc tắt lịch qua API.

Quy định repo đã ghi VnExpress từng trả 302 cho sitemap. Bản tích hợp này
dùng listing của script người dùng cung cấp, không thêm logic fallback từ
sitemap bị chặn, và chưa kiểm website thật trong lượt tích hợp.

## Kho local và Bronze cũ

```text
data/{bronze,silver,clean_silver}/vnexpress/<article_id>.json
data/jobs/<job_id>/{bronze,silver,clean_silver}/vnexpress.jsonl
data/state/vnexpress.json
```

File theo bài là dữ liệu chính. JSONL theo job chỉ gồm bài xử lý trong lượt
đó. Bronze đã có được dùng lại, không ghi đè; chưa nhập queue SQLite cũ.
Chưa tự ghi Postgres, cập nhật bảng xu hướng hay upload R2.

Chuyển Bronze bài chi tiết cũ sang Silver offline, dùng file đích chưa có:

```python
from crawler.silver_transformer_vnexpress import run_silver_transform

run_silver_transform("bronze_vnexpress.jsonl", "silver_vnexpress_v2.jsonl")
```

## Kiểm thử và giới hạn

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_vnexpress.py tests/test_vietnamnet.py tests/test_thanhnien.py tests/test_tuoitre.py tests/test_automation.py tests/ingest -q
```

Kết quả 09/11/2026: **152 passed, 22 skipped, 4 subtests passed**; các test
Postgres skip khi thiếu DB test. Ruff cho module/test mới, harvester VietnamNet,
HTTP client, config và schema đạt; `git diff --check` đạt. Fixture HTML tổng
hợp ở `tests/fixtures/crawlers/vnexpress/`, không gọi mạng hoặc R2 trong test.

Chưa xác minh selector, robots hoặc kết quả crawl website thật. Lượt đầu
chỉ lấy tối đa 3 trang/chuyên mục, không bảo đảm đủ 24 giờ. Các lượt sau
dừng sau 2 trang liên tiếp toàn URL đã biết, giới hạn 100 trang/chuyên mục.
Chạm giới hạn, HTML rỗng hoặc không nhận diện link báo partial, không tiến
mốc quét. Không backfill toàn lịch sử hay tự theo dõi sửa đổi bài đã clean.
