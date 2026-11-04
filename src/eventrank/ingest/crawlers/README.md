# Thêm crawler cho một báo

Thư mục này chứa crawler của từng báo: **một báo, một file**. Bạn chỉ viết phần riêng của báo đó
(lấy danh sách bài mới, tách các trường từ HTML). Phần chung đã có sẵn trong khung `eventrank.ingest`:
giãn cách request, robots.txt, User-Agent, thử lại khi lỗi, kiểm tra hợp đồng Silver, ghi Postgres không trùng,
ghi lại mỗi lần chạy.

Chi tiết đầy đủ (bảng DB, mã lỗi, cạm bẫy): [`docs/handoff/ingest.md`](../../../../docs/handoff/ingest.md).
Quy tắc thu thập bắt buộc: `AGENTS.md` mục 3. Bẫy đã biết của từng báo: `configs/sources.yaml` (trường `notes`)
và `docs/tong-hop.md` mục 6.5.

## Tóm tắt: 3 chỗ cần sửa

Ví dụ với Tuổi Trẻ (`source = tuoitre`):

| Việc | File |
|---|---|
| Viết crawler | `src/eventrank/ingest/crawlers/tuoitre.py` (tạo mới) |
| Lưu trang mẫu để test offline | `tests/fixtures/crawlers/tuoitre/` (tạo mới) |
| Khai báo crawler cho báo | `configs/sources.yaml` (sửa mục `tuoitre`) |

Không sửa file nào khác trong khung. Không cần đụng DB, API hay web.

## Bước 0: Chuẩn bị (một lần)

```bash
git fetch && git switch feat/serving-live      # hoặc nhánh đã merge phần ingest
git switch -c feat/ingest-tuoitre              # nhánh riêng cho crawler của bạn
make install
```

- **Viết và test crawler không cần Postgres**: test chạy trên trang mẫu, không gọi mạng.
- **Cào thật vào DB** (bước 5) mới cần Postgres và hai biến trong `.env`: `DATABASE_URL` và
  `CRAWLER_USER_AGENT`. Mẫu ở `.env.example`; cách tạo Postgres ở `docs/handoff/ingest.md` mục 5.

## Bước 1: Khảo sát báo (chưa tải bài nào)

Theo skill `add-news-source` bước 1:

- Đọc `robots.txt` của báo: có cấm đường dẫn nào, có `Crawl-delay` không.
- Tìm RSS hoặc sitemap. Tải thử **một** file. Nhận về HTML thay vì XML → **dừng, báo nhóm**.
- Ghi link RSS/sitemap và bẫy mới phát hiện vào `configs/sources.yaml` (trường `rss`, `sitemap`, `notes`).

## Bước 2: Viết crawler

Chép mẫu rồi sửa. Mẫu đầy đủ, chạy được: [`example_rss.py`](example_rss.py) (báo giả `baovidu`).

```bash
cp src/eventrank/ingest/crawlers/example_rss.py src/eventrank/ingest/crawlers/tuoitre.py
```

Một crawler là một lớp có 3 thuộc tính và 1 hàm:

```python
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

from eventrank.ingest.base import CrawlContext
from eventrank.ingest.fetch import DomainBlocked, FetchError

FEED = "https://tuoitre.vn/rss/..."            # lấy từ bước 1


class TuoiTreRss:
    source = "tuoitre"                 # PHẢI trùng mục `source` trong configs/sources.yaml
    name = "tuoitre_rss"               # tên crawler, hiện trong `ingest status`
    parser_version = "tuoitre-rss-1"   # đổi cách tách bài → tăng số

    def crawl(self, ctx: CrawlContext) -> Iterator[dict[str, Any]]:
        xml = ctx.client.get_xml(FEED)                  # RSS/sitemap: luôn dùng get_xml
        for link, pub_dt in ...:                         # TODO: lấy link + giờ đăng từ RSS
            if ctx.since and pub_dt and pub_dt < ctx.since - timedelta(hours=1):
                continue                                 # đã cào ở lần chạy trước
            try:
                resp = ctx.client.get(link)              # trang bài: luôn qua ctx.client
            except DomainBlocked:
                raise                                    # báo chặn cả domain → dừng, không vượt chặn
            except FetchError as e:
                ctx.log.warning("bỏ %s: %s", link, e)    # một bài lỗi → bỏ bài đó
                continue
            if resp.status_code != 200:
                continue
            # TODO: tách bài, ưu tiên JSON-LD NewsArticle → thẻ meta → bỏ qua
            yield {
                "url": link,
                "source": self.source,
                "category": ...,         # chuyên mục nguyên văn trên trang
                "title": ...,
                "sapo": ...,
                "author": ... or None,   # không có thì None
                "published_at": ...,     # ISO 8601 CÓ múi giờ, vd "2026-11-04T07:07:00+07:00"
                "content_text": ...,     # thân bài văn bản thuần, các đoạn nối bằng "\n\n"
            }
```

`ctx` khung đưa vào gồm:

| Thuộc tính | Là gì |
|---|---|
| `ctx.client` | Client HTTP lịch sự. `get(url)` trả `httpx.Response`; `get_xml(url)` trả bytes và báo lỗi nếu nhận HTML |
| `ctx.since` | Lúc lần chạy thành công trước kết thúc (`None` = lần đầu). Dùng để chỉ cào bài mới |
| `ctx.now` | "Bây giờ" của lần chạy, có múi giờ |
| `ctx.log` | Logger |

**Khung tự làm, bạn không cần làm:** chuẩn hoá Unicode NFC và khoảng trắng, tính `article_id = sha256(url)`,
kiểm múi giờ, gắn cờ bài ngắn / thiếu sapo / thiếu tác giả, bỏ qua bài đã có, đếm bài bị loại.

**Không được:**

- Tự tạo `requests`, `httpx.Client` hay `urllib`: sẽ bỏ qua giãn cách 2 giây và robots.txt.
- Tự ghi Postgres hay R2 (`import psycopg`, `boto3`…).
- Đổi User-Agent, giả làm trình duyệt.
- Bắt `DomainBlocked` rồi chạy tiếp.
- Bịa `published_at` khi trang không có. Cứ để `None`: khung loại bài đó và đếm `published_at_missing`.
- Lấy `dateModified` thay cho `datePublished`.
- Tự bỏ bài ngắn hay bài thiếu sapo: khung chỉ gắn cờ, không loại.

Cần thư viện tách bài (`lxml`, `trafilatura`)? Thêm bằng `uv add --no-sync <gói>` rồi `uv sync --group embed`.
Chạy `uv add` thường sẽ gỡ PyTorch khỏi `.venv`. Dùng `lxml` thì đặt `resolve_entities=False`.

## Bước 3: Lưu trang mẫu để test

Tải tay trang thật (RSS + ít nhất 5 bài) vào `tests/fixtures/crawlers/tuoitre/`. Nên có cả ca xấu:
bài video, bài rất ngắn, bài thiếu JSON-LD, bài không có tác giả.

```
tests/fixtures/crawlers/tuoitre/
├── routes.yaml
├── robots.txt
├── rss.xml
├── bai-1.html
└── ...
```

`routes.yaml` nối URL với file. URL không có trong danh sách sẽ trả 404:

```yaml
routes:
  "https://tuoitre.vn/robots.txt": robots.txt
  "https://tuoitre.vn/rss/tin-moi-nhat.rss": rss.xml
  "https://tuoitre.vn/bai-1.htm": bai-1.html
```

Mẫu tham khảo: `tests/fixtures/crawlers/baovidu/`.

## Bước 4: Khai báo và test

Trong `configs/sources.yaml`, sửa mục của báo. **Giữ `enabled: false`** tới khi qua checklist ở bước 6:

```yaml
  - source: tuoitre
    ...
    enabled: false
    crawler: eventrank.ingest.crawlers.tuoitre:TuoiTreRss
```

Chạy test:

```bash
make test
```

Đã khai báo `crawler:` thì `tests/ingest/test_crawler_contract.py` **tự động** chạy crawler của bạn trên trang mẫu.
Thiếu thư mục mẫu, hoặc có bài sai hợp đồng Silver, thì test báo lỗi. Bạn không phải sửa file test đó.

Test này đòi **mọi** bài crawler sinh ra từ trang mẫu đều hợp lệ. Vì vậy ca xấu trong trang mẫu nên là loại được
gắn cờ (bài ngắn, thiếu tác giả, thiếu JSON-LD), không phải loại bị loại (thiếu ngày đăng). Muốn thử ca thiếu ngày,
hãy để URL đó trả 404, hoặc viết test riêng gọi `eventrank.ingest.contract.validate_article`.

Muốn kiểm giá trị cụ thể (đúng chuyên mục, đúng tác giả), viết thêm `tests/ingest/test_tuoitre.py`:

```python
from eventrank.ingest.crawlers.tuoitre import TuoiTreRss
from eventrank.ingest.testing import check_crawler, fixture_client_from_dir


def test_tuoitre_tach_dung_truong():
    arts = check_crawler(TuoiTreRss(), fixture_client_from_dir("tests/fixtures/crawlers/tuoitre"))
    assert len(arts) == 5
    assert all(a.published_at.tzinfo for a in arts)
    assert {a.category for a in arts} <= {"Thời sự", "Thế giới", "Kinh doanh"}
```

## Bước 5: Cào thử 12 bài thật vào Postgres cục bộ

```bash
make db-migrate                       # lần đầu: tạo bảng
uv run --group embed python -m eventrank.ingest run --source tuoitre --once --force --limit 12
make ingest-status                    # lần chạy cuối phải là ok, bài bị loại ≈ 0
```

`--force` cho phép chạy khi `enabled: false`, chỉ dùng để thử. Mở 3 bài ngẫu nhiên trong DB so với trang thật:
thân bài không lẫn quảng cáo, mục "Tin liên quan", chú thích ảnh.

```sql
-- cờ chất lượng của báo: no_body / short_body cao bất thường = tách bài hỏng
SELECT f, count(*) FROM articles, unnest(quality_flags) f WHERE source = 'tuoitre' GROUP BY 1;
```

Chạy lại lệnh `run` lần hai: `n_new` phải bằng 0.

## Bước 6: Checklist trước khi bật

- [ ] Đã khảo sát robots.txt, RSS/sitemap; ghi vào `configs/sources.yaml`.
- [ ] Có ít nhất 5 trang mẫu (gồm ca xấu); `make test` xanh.
- [ ] Cào thử 12 bài: `status` = `ok`, gần như không bài nào bị loại, 3 bài mở ra đúng với trang thật.
- [ ] Đã đặt `parser_version`; chạy lần hai cho 0 bài mới.
- [ ] Nhóm đồng ý bật.

Xong thì đổi `enabled: true`, commit theo dạng `[INGEST] crawler Tuổi Trẻ qua RSS` và mở Pull Request.
Chạy định kỳ: `python -m eventrank.ingest run --source tuoitre --loop --interval 600` (10 phút một lần).

## Đã có script cào riêng?

Không bắt buộc viết lại theo khung. Cho script xuất JSONL đúng hợp đồng Silver (`docs/tong-hop.md` mục 5.3),
rồi nạp vào DB:

```bash
uv run --group embed python -m eventrank.ingest import-jsonl 'duong/dan/*.jsonl'
```

Dữ liệu đi qua cùng bước kiểm tra, không tạo bài trùng, và vẫn hiện trong `make ingest-status`.
Nhưng script riêng phải tự tuân thủ giãn cách 2 giây và robots.txt.

## Lỗi thường gặp

| Hiện tượng | Nguyên nhân, cách xử lý |
|---|---|
| `NotXmlError` | Báo trả HTML thay vì XML (VnExpress chuyển sitemap về trang chủ). Dừng, báo nhóm, không vượt chặn |
| Lần chạy `blocked` | Báo trả 403 liên tiếp, hoặc crawler xin URL bị robots.txt cấm. Dừng, báo nhóm |
| Nhiều `published_at_missing` / `published_at_naive` | Lấy sai trường ngày, hoặc ngày thiếu múi giờ. Đọc `datePublished` trong JSON-LD; thiếu múi giờ thì thêm `+07:00` chỉ khi chắc chắn trang dùng giờ Việt Nam |
| `source_mismatch` | Trường `source` trong dict khác `source` của lớp crawler |
| Test hợp đồng báo thiếu fixture | Chưa có `tests/fixtures/crawlers/<source>/routes.yaml` |
| `CrawlerConfigError` về User-Agent | Chưa đặt `CRAWLER_USER_AGENT` trong `.env` |
| `ingest run` từ chối chạy | Báo đang `enabled: false` (thêm `--force` để thử), hoặc DB đang ở chế độ phát lại |
