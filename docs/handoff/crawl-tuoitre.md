# Bàn giao crawler Tuổi Trẻ — 09/11/2026

Đã chuyển logic từ bốn script người dùng cung cấp (`crawl_list_link.py`,
`read_and_save.py`, `crawl_paper.py`, `upload_silver_to_r2.py`) vào luồng
`api/` → `automation/` → `crawler/`. Không chạy các script cũ khi import,
không phụ thuộc đường dẫn máy cá nhân hay SQLite cũ.

## Cấu trúc và định dạng

| Module | Vai trò |
|---|---|
| `crawler/harvester_tuoitre.py` | 10 zone timeline từ script cũ; chuẩn hóa URL, loại link media/ngoài domain |
| `crawler/ingest_tuoitre.py` | Giữ HTML cả trang để bảo toàn JSON-LD/meta nằm ngoài thân bài |
| `crawler/silver_transformer_tuoitre.py` | `transform_record(bronze)` trả đúng 9 trường Silver; `source=tuoitre`, ID SHA-256 URL, ngày có múi giờ Việt Nam, thiếu tác giả = null |
| `automation/discovery.py` | Quét timeline tăng dần; lần đầu tối đa 3 trang/zone, lượt sau dừng sau 2 trang liên tiếp toàn URL đã biết |
| `automation/config.py`, `automation/http.py`, `api/schemas.py` | Đăng ký nguồn, domain, khoảng nghỉ, kiểm robots và nhận yêu cầu API |

Mười nhãn chuyên mục kế thừa script cũ để đồng nhất với luồng automation;
`Khoa học - Công nghệ` dùng cùng cách viết của pipeline. Zone `3` là Thời sự,
được script cũ ánh xạ thành Chính Trị; không coi đây là bộ lọc riêng bài chính trị.

File do pipeline chung tạo:

```text
data/bronze/tuoitre/<article_id>.json
data/silver/tuoitre/<article_id>.json
data/clean_silver/tuoitre/<article_id>.json
data/jobs/<job_id>/{bronze,silver,clean_silver}/tuoitre.jsonl
data/state/tuoitre.json
```

JSONL của mỗi job chỉ chứa những bài đã xử lý trong lượt đó. Bài có cùng URL
chỉ tải một lần khi đã xử lý thành công; bài lỗi tiếp tục dùng retry/resume
của pipeline. Bronze đã có không bị ghi lại. Không thay đổi key hay dữ liệu R2.

## Chạy và thêm vào lịch

Cài dependency theo `pyproject.toml`/`uv.lock`. Nếu dùng uv, giữ nhóm embed:

```powershell
.\.venv\Scripts\python.exe -m uv sync --group embed
# Thay bằng tên bot và liên hệ thật của nhóm trước khi chạy.
$env:CRAWLER_USER_AGENT = 'EventRank-PBL/0.1 (+mailto:your-team@example.com)'
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8002 --workers 1
```

`api.main` hiện không tự nạp `.env`; biến môi trường phải được truyền vào
tiến trình, như ví dụ PowerShell trên. Không dùng User-Agent giả trình duyệt.
Tuổi Trẻ kiểm robots.txt trước khi tải bài/timeline, dùng khoảng nghỉ ít nhất
2 giây (hoặc Crawl-delay lớn hơn); bị cấm, HTTP 403/428/429 hay redirect thì
dừng nguồn trong job và ghi trạng thái blocked. Lượt theo lịch sau có thể thử lại.

Mở `http://127.0.0.1:8002/docs`. Có thể gửi `POST /crawl/jobs` với:

```json
{"sources": ["tuoitre"]}
```

Lịch mới mặc định có cả 8 nguồn (đã thêm Thanh Niên, VietnamNet và VnExpress). **Lịch đã lưu được giữ nguyên** để không
tự thay lựa chọn vận hành. Đọc `GET /crawl/schedule`, sau đó gửi
`PATCH /crawl/schedule` với danh sách muốn chạy, ví dụ:

```json
{"enabled": true, "interval_minutes": 30, "sources": ["baochinhphu", "nhandan", "dantri", "qdnd", "tuoitre", "thanhnien", "vietnamnet", "vnexpress"]}
```

Server crawler và backend web là hai tiến trình khác nhau; luồng này chưa
ghi Postgres, chưa tự cập nhật sự kiện trên dashboard. Không chạy nhiều
worker/instance dùng chung thư mục trạng thái.

## Chuyển Bronze cũ sang Silver offline

Bronze chi tiết cũ đã có `url`, `category`, `raw_html` nên có thể đưa trực tiếp
vào transformer, không tải lại. Dùng đường dẫn đầu ra mới, chưa tồn tại:

```python
from crawler.silver_transformer_tuoitre import run_silver_transform

run_silver_transform("bronze_tuoitre.jsonl", "silver_tuoitre_v2.jsonl")
```

Lệnh này chuyển định dạng; không nhập hàng đợi SQLite cũ vào scheduler,
không upload R2. Các bản Silver trước đây trên R2 vẫn giữ nguyên.

## Kiểm thử và phần cần kiểm thật

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_tuoitre.py tests/test_automation.py -q
```

Kết quả kiểm tại máy tích hợp (09/11/2026), có chạy thêm `tests/ingest`:
`78 passed, 22 skipped, 4 subtests passed`; các test Postgres bị skip khi
không có DB test. Ruff cho các module mới, HTTP client, config, schema và
test Tuổi Trẻ đạt; `uv lock --check --offline` và `git diff --check` đạt.
`automation/discovery.py` và `automation/pipeline.py` còn 7 cảnh báo lint
có từ trước (datetime, broad exception); không phát sinh cảnh báo mới.

Fixture HTML tổng hợp tại `tests/fixtures/crawlers/tuoitre/`, dựa trên selector
của code người dùng; kiểm URL, timeline/bootstrap/page cap, 9 trường Silver,
múi giờ, JSON-LD ngoài thân bài, loại widget, retry/resume/chống trùng, lịch,
robots và dừng khi bị chặn. Không gọi trang báo hay R2 trong test.

Chưa xác minh selector, zone, robots hay kết quả crawl trên website thật trong
lượt tích hợp. Cần theo dõi `GET /crawl/jobs/{job_id}` trong lượt vận hành đầu.
HTML có nội dung nhưng không nhận diện được link là lỗi discovery, không coi
là danh sách rỗng. Chạm giới hạn trang ở lượt tăng dần báo partial và giữ mốc
quét cũ. Không tự động theo dõi cập nhật bài đã clean, không backfill toàn bộ
lịch sử và không di chuyển dữ liệu cũ vào kho mới.
