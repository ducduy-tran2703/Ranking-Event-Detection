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

**RAG local:** Qdrant + Tantivy BM25, Modal phục vụ model. Bước chuẩn bị NER/chunk vào Postgres:
`make rag-prepare ARGS="--ner-version … --silver-glob … --ner …"`. Cài đặt, data contract và lệnh chạy:
[docs/handoff/rag.md](docs/handoff/rag.md). **Plan và hướng dẫn tiếp tục ở chat mới:**
[docs/plan-rag.md](docs/plan-rag.md). BM25 đã có: `make rag-bm25`,
`make rag-search ARGS='"câu hỏi" --limit 5'`. Dense Qdrant và hybrid RRF đã có;
`make rag-ask ARGS='"câu hỏi"'` chạy hỏi đáp có citation trên snapshot hiện tại.
`make rag-api` mở API riêng tại `http://127.0.0.1:8001/docs`.
Model services: `make rag-modal-deploy`, `make rag-modal-cache`, `make rag-model-smoke`.
Deploy xuất `.env.client` chỉ chứa cấu hình inference để chia sẻ riêng cho nhóm;
không chia sẻ toàn bộ `.env` chứa khóa quản trị/R2/Postgres.

Gõ `make` để xem mọi lệnh. Triển khai cho cả nhóm truy cập qua domain: [docs/tong-hop.md](docs/tong-hop.md) mục 11.4.

## Test

```bash
make test                     # test Python (dữ liệu mẫu, không gọi mạng) + lint + kiểm tra kiểu web
make test-db                  # test cần Postgres (đặt TEST_DATABASE_URL; không có thì tự bỏ qua)
```


Thu thập bài báo từ Báo Chính phủ, Nhân Dân, Dân Trí và Quân đội nhân dân.
Luồng tự động: tìm URL → Bronze → Silver → làm sạch. Chưa tích hợp database
hoặc gom cụm.

## Chạy trên Windows

Yêu cầu Python 3.11 trở lên. Mở PowerShell ở thư mục gốc dự án:

```powershell
# Chỉ tạo môi trường nếu chưa có .venv
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Mở http://127.0.0.1:8000/docs để gọi API qua Swagger UI.

**Khi khởi động, lịch mặc định bật và hệ thống có thể bắt đầu cào ngay một lượt
bù**, sau đó chạy vào phút `:00` và `:30`, múi giờ `Asia/Ho_Chi_Minh`.
Máy phải đang thức và tiến trình phải còn chạy. Khi máy ngủ hoặc ứng dụng tắt,
lần mở lại chỉ tạo một lượt bù, không tạo một job cho từng mốc đã bỏ lỡ.
Nếu job trước vẫn chạy khi đến mốc mới, mốc đó được bỏ qua; lý do được lưu trong
`last_event` của lịch.

Chạy **một worker Uvicorn**, không dùng `--reload` trong vận hành. Khóa hệ điều
hành ngăn hai ứng dụng cùng ghi vào một thư mục dữ liệu; nếu chạy instance thứ
hai dùng cùng thư mục, ứng dụng thứ hai sẽ báo lỗi khi khởi động.

FastAPI khởi động và dừng bộ điều phối qua
[lifespan](https://fastapi.tiangolo.com/advanced/events/).

## API và ví dụ

| Endpoint | Tác dụng |
| --- | --- |
| `GET /health` | Kiểm tra ứng dụng và ID job đang chạy |
| `POST /crawl/jobs` | Tạo lượt cào ngay, trả HTTP 202 và thông tin job |
| `GET /crawl/jobs?limit=20&offset=0` | Xem lịch sử, mới nhất trước |
| `GET /crawl/jobs/{job_id}` | Xem trạng thái và thống kê từng nguồn |
| `GET /crawl/schedule` | Xem lịch, lần chạy tiếp theo và mốc gần nhất |
| `PATCH /crawl/schedule` | Bật/tắt lịch, đổi nguồn hoặc khoảng chạy |

ID nguồn hợp lệ: `baochinhphu`, `nhandan`, `dantri`, `qdnd`.
Trong Swagger UI, chọn endpoint → Try it out → nhập JSON → Execute.

Cào ngay một nguồn:

```json
{"sources": ["qdnd"]}
```

Cào cả bốn nguồn:

```json
{"sources": ["baochinhphu", "nhandan", "dantri", "qdnd"]}
```

Job chạy ở nền. Dùng `id` trả về để gọi `GET /crawl/jobs/{job_id}`.
Nếu đang có job, yêu cầu mới nhận HTTP 409. Chức năng này cũng ngăn job thủ
công chạy chồng với job theo lịch.

Tạm dừng việc tạo job theo lịch (job đang chạy vẫn tiếp tục):

```json
{"enabled": false}
```

Bật lịch 30 phút cho cả bốn nguồn:

```json
{
  "enabled": true,
  "interval_minutes": 30,
  "sources": ["baochinhphu", "nhandan", "dantri", "qdnd"]
}
```

Khoảng chạy hỗ trợ: 5, 10, 15, 20, 30, 60 phút, căn theo giờ trên đồng hồ.
Bật lại lịch sau khi chủ động tắt sẽ chờ mốc kế tiếp, không chạy bù thời gian
đã chủ động tắt. Cấu hình lịch được giữ qua các lần khởi động.

Mỗi job có các trạng thái `queued`, `running`, `completed`, `partial`,
`failed`, `interrupted`. Kết quả mỗi nguồn còn có thể là `blocked` khi gặp
HTTP 403/428/429. `partial` nghĩa là có lỗi hoặc chưa hoàn thành đủ phạm vi quét;
hãy xem `results.<source>.errors`, số bài `failed` và `exhausted`.
Bài bị loại theo quy tắc chất lượng được tính trong `rejected`, không tự làm
job thành lỗi.

## Dữ liệu và phục hồi

Thư mục mặc định là `data/` dưới gốc dự án, không phụ thuộc thư mục chạy lệnh:

```text
data/
  state/
    schedule.json                  # Lịch và quyết định ở mốc gần nhất
    <source>.json                  # URL, trạng thái, số lần lỗi, mốc quét
    instance.lock                  # Khóa hệ điều hành; không cần xóa sau crash
  bronze/<source>/<article_id>.json
  silver/<source>/<article_id>.json
  clean_silver/<source>/<article_id>.json
  jobs/<job_id>/
    job.json
    bronze/<source>.jsonl
    silver/<source>.jsonl
    clean_silver/<source>.jsonl
    rejects/<source>.jsonl
```

File JSON riêng cho từng bài là bản lưu chính, ghi bằng file tạm rồi thay thế
nguyên tử. Chúng cho phép tiếp tục từ Bronze khi mất điện, và tránh ghi trùng
bản sạch nếu tiến trình dừng ngay trước lúc cập nhật trạng thái. ID vẫn là
SHA-256 của URL như pipeline cũ.

Các file JSONL trong mỗi job là bản xuất của những bài đã xử lý ở lượt đó,
không phải toàn bộ kho dữ liệu. Một bài xử lý lại có thể xuất hiện ở nhiều
job; khi gộp các bản xuất, dùng `article_id` để loại trùng. Bản xuất có thể
chưa tồn tại nếu tiến trình bị tắt cưỡng bức; file JSON của bài đã ghi vẫn còn.
Để đọc toàn bộ dữ liệu sạch, đọc `data/clean_silver/<source>/*.json`.

Bài tải lỗi sẽ được thử lại ở lượt sau, kể cả khi nó không còn xuất hiện trên
trang danh mục. Mỗi request có tối đa 4 lần thử với backoff cho lỗi mạng/5xx;
mỗi bài có tối đa 5 lượt xử lý lỗi. Sau đó bài được giữ ở trạng thái `failed`
để kiểm tra, không tự lặp vô hạn. Có thể đặt lại ngân sách cho các bài lỗi
của nguồn được chọn bằng:

```json
{"sources": ["qdnd"], "retry_failed": true}
```

Bài bị loại (`rejected`) không được tự thử lại. Nếu sau này thay parser/quy tắc
lọc và muốn xử lý lại các bài đó, cần bổ sung lệnh tái xử lý riêng; Bronze vẫn còn.
Job bị gián đoạn khi tắt tiến trình được đánh dấu `interrupted` ở lần khởi động
sau, rồi lượt bù xử lý các bài còn dang dở. Không xóa trạng thái khi restart.

Các file Bronze/Silver/clean_silver cũ ở gốc dự án được giữ nguyên. Phiên bản
tự động hiện **chưa nhập URL từ dữ liệu cũ**; vì thế một URL từng cào bằng script
cũ vẫn có thể được tải một lần vào kho `data/` mới.

## Phạm vi tìm bài mới và giới hạn

- Chính phủ/Nhân Dân: lượt đầu lấy 3 trang gần nhất mỗi chuyên mục để tạo nền
  theo dõi, **không bảo đảm lấy toàn bộ bài của 24 giờ trước**. Các lượt sau
  duyệt từ đầu cho đến 2 trang liên tiếp chỉ chứa URL đã biết. Đây là giả định
  về thứ tự trang tin, không bảo đảm tuyệt đối với bài bị đẩy xuống rất sâu hoặc
  xuất hiện muộn. Giới hạn 100 trang mỗi chuyên mục; chạm giới hạn sẽ báo
  `partial` và không cập nhật mốc quét hoàn tất.
- Dân Trí: duyệt sitemap tháng từ mốc quét trước trừ 24 giờ. Ngày trong URL
  được dùng để loại bài cũ; URL không nhận diện được ngày vẫn được giữ. Mục
  Thời sự được kiểm tra `ggCatList` khi tải bài, giữ HTML đó cho Bronze, không
  tải lại lần hai chỉ để phân loại. Thiếu `ggCatList` được coi là lỗi có thể
  thử lại, không cache nhầm thành "không phải Chính trị".
- Quân đội nhân dân: duyệt sitemap ngày từ mốc quét trước trừ 24 giờ.
- Lượt đầu của hai nguồn sitemap dùng cửa sổ 24 giờ. Nếu thời gian ngừng lâu,
  mốc quét cũ giúp chọn lại các sitemap trong thời gian gián đoạn.
- Lỗi ở discovery không làm mất URL đã phát hiện: chúng được lưu trước khi xử
  lý. Mốc quét chỉ tiến khi discovery hoàn tất; lỗi tải/xử lý bài được theo dõi
  độc lập theo URL.
- Các nguồn chạy song song, mỗi nguồn mặc định có 2 luồng tải/xử lý bài. Mỗi
  luồng dùng session riêng. Khoảng cách bắt đầu request tối thiểu chung cho một
  nguồn là 2 giây, riêng Dân Trí 4 giây; áp dụng cả discovery và retry. Khi bị
  chặn, nguồn đó dừng gửi thêm request trong job; request đã gửi có thể vẫn hoàn
  tất, các nguồn khác tiếp tục. Lượt theo lịch sau sẽ thử nguồn đó lại.
- Chưa theo dõi sửa đổi nội dung của bài đã xử lý xong; chưa gom cụm, chưa kết
  nối database. Ngưỡng làm sạch và selector kế thừa mã hiện có, cần kiểm chứng
  trên trang thật trước khi vận hành dài hạn.

## Cấu hình và mã hiện tại

Các giá trị luồng, timeout, cửa sổ quét và giới hạn trang nằm trong
`automation/config.py` (`Settings`). Nếu muốn đổi thư mục lưu:

```powershell
$env:CRAWLER_DATA_DIR = 'D:\NewsData'
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Thư mục này phải cho phép tài khoản đang chạy ghi dữ liệu. Đây là hệ thống
file cho một máy; khi chuyển sang nhiều máy hoặc database cần thay lớp lưu
trữ và điều phối tương ứng. Trạng thái JSON đang được ghi lại theo từng bài,
phù hợp giai đoạn thử nghiệm, sẽ cần tối ưu khi số bài tăng lớn.

Các script `crawler/ingest_*.py` và `crawler/silver_transformer_*.py` chỉ được
điều chỉnh import để chạy được cả trực tiếp lẫn dưới dạng package. Hàm
backfill, selector, quy tắc làm sạch và lệnh chạy thủ công hiện có được giữ.
Luồng tự động nằm trong `automation/`, tái sử dụng các hàm đó. Dữ liệu sạch
chuẩn hóa chung nhãn `Khoa học - Công nghệ`.

## Kiểm thử không gọi trang báo

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Kiểm tra API, lịch theo đồng hồ, ngăn chạy chồng, khóa process, chạy song song,
giới hạn tốc độ, chặn nguồn, phát hiện URL, xử lý sạch, loại bài, chống tải trùng,
retry và tiếp tục từ dữ liệu đã lưu. Các test dùng thư mục tạm và HTTP giả lập.
