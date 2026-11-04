# Bàn giao INGEST — cắm crawler vào hệ thống chạy liên tục

> Viết 04/11/2026 (giai đoạn 1 của "web chạy như thật"). Dành cho **người viết crawler**. Đọc kèm
> `AGENTS.md` mục 3, `docs/tong-hop.md` mục 5.3 (hợp đồng Silver), 6.5 (10 cái bẫy), skill `add-news-source`.

## 1. Trạng thái

| Phần | Trạng thái |
|---|---|
| Postgres: bảng `sources`, `articles`, `crawl_runs`, `app_clock` (`infra/db/migrations/001_ingest.sql`) | **Xong**, có test |
| Hợp đồng một bài, ghi DB idempotent, client HTTP lịch sự, khung chạy crawler, bộ test hợp đồng | **Xong**, có test |
| `import-jsonl` (nạp Silver có sẵn), `replay` (phát lại Silver thay crawler), `status` | **Xong**, đã chạy thử trên 28.746 bài Silver (Postgres 18 tạm, 04/11/2026) |
| **Crawler thật cho 6 báo** | **Chưa có** — việc của bạn. `configs/sources.yaml`: mọi báo `enabled: false`, `crawler: ""` |
| Worker embedding → gom cụm tăng dần → đặt tên → xu hướng đọc từ Postgres; API đọc DB | Giai đoạn 2–3, chưa làm |

```
crawler của bạn ──yield dict──► contract.validate_article ──► sink.upsert_articles ──► Postgres.articles
   │ (mọi request qua ctx.client = PoliteClient)      │ (bài lỗi: đếm lý do)            ▲
   └────────────── run_crawler ghi crawl_runs (bắt đầu / đếm / ok|failed|blocked) ──────┘
JSONL của script riêng ──► ingest import-jsonl ──────────────(cùng contract + sink)──────┘
Silver cũ ──► ingest replay (đồng hồ giả lập, app_clock) ──► DB RIÊNG (thay crawler khi chưa có)
```

## 2. Bảng (chi tiết + chú thích trong file migration)

| Bảng | Khoá | Nội dung |
|---|---|---|
| `sources` | `source` (viết thường, không dấu) | tên hiển thị, homepage, `enabled`, `crawler` ("module:Lớp"), ghi chú. Nạp từ `configs/sources.yaml` |
| `articles` | `article_id = sha256(url)`; `url` UNIQUE | đúng 9 trường hợp đồng 5.3 + `crawled_at` (lần đầu vào DB, không đổi), `updated_at` (lần cuối nội dung đổi), `ingested_via` (`import_jsonl` / `replay` / `crawler:<tên>`), `parser_version`, `content_hash`, `quality_flags text[]`, `dup_group_id` (giai đoạn sau). Chỉ mục `published_at`, `(source, published_at)`, `updated_at` |
| `crawl_runs` | `run_id` | mỗi lần một crawler (hoặc một lần import) chạy cho một báo: giờ bắt đầu/kết thúc, `status` (`running`/`ok`/`failed`/`blocked`), `n_seen/n_new/n_updated/n_unchanged/n_rejected`, `reject_reasons` (jsonb), `error` |
| `app_clock` | một dòng | `mode` `real`/`replay`, `sim_now`, `speed`. Hàm SQL `app_now()` = "bây giờ" của hệ thống |
| `schema_migrations` | tên file | sha256 + thời điểm áp (do `eventrank.common.db` quản lý) |

Không có pgvector, không bảng sự kiện (giai đoạn 2 thêm bằng `002_….sql`). **Không sửa file migration đã áp** — thêm file mới.

## 3. Viết crawler ở đâu, giao diện thế nào

Một file một báo: `src/eventrank/ingest/crawlers/<source>.py`. Mẫu đầy đủ, chạy được offline:
**`src/eventrank/ingest/crawlers/example_rss.py`** (báo giả `baovidu`, fixture `tests/fixtures/crawlers/baovidu/`).

```python
class TuoiTreRss:
    source = "tuoitre"                 # khớp configs/sources.yaml
    name = "tuoitre_rss"               # → ingested_via = "crawler:tuoitre_rss", crawl_runs.crawler
    parser_version = "tuoitre-rss-1"   # đổi cách tách bài → tăng (docs/tong-hop.md mục 3.2)

    def crawl(self, ctx):              # ctx: CrawlContext(client, now, source, since, log)
        xml = ctx.client.get_xml("https://…/rss.xml")
        for url in …:
            html = ctx.client.get(url).text
            yield {"url": url, "source": "tuoitre", "category": …, "title": …, "sapo": …,
                   "author": … or None, "published_at": "2026-09-16T07:07:00+07:00", "content_text": …}
```

Đăng ký: `crawler: eventrank.ingest.crawlers.tuoitre:TuoiTreRss` trong `configs/sources.yaml` (để `enabled: false` tới khi qua checklist mục 6).

**Khung lo hộ bạn** (đừng tự làm lại):

| Việc | Ở đâu |
|---|---|
| ≥ 2 s/request/domain (lấy max với `Crawl-delay`), kể cả từng bước chuyển hướng | `ingest/fetch.py` `PoliteClient` |
| User-Agent trung thực từ `CRAWLER_USER_AGENT`; từ chối UA giả trình duyệt | `PoliteClient` |
| `robots.txt` (đệm theo domain); URL bị cấm → `RobotsDisallowed`, không gửi request | `PoliteClient` |
| 429/5xx/lỗi mạng → thử lại với backoff (tôn trọng `Retry-After`) | `PoliteClient` |
| 403 liên tiếp → `DomainBlocked`, dừng domain; lần chạy ghi `blocked` | `PoliteClient` + `run_crawler` |
| `get_xml()`: HTML thay XML (VnExpress 302 → trang chủ) → `NotXmlError`; bỏ BOM; gunzip | `PoliteClient.get_xml` |
| NFC, gộp khoảng trắng, `author` rỗng → `null`, `article_id` từ url, kiểm múi giờ, cờ chất lượng | `ingest/contract.py` |
| Ghi DB idempotent, chỉ UPDATE khi nội dung đổi, giữ `crawled_at` đầu | `ingest/sink.py` |
| Ghi `crawl_runs`, đếm, lưu phần đã cào khi crawler lỗi giữa chừng | `ingest/base.py` `run_crawler` |

**Bạn phải tự lo:** chọn URL (RSS / sitemap theo tên file, xem bẫy trong `configs/sources.yaml`); tách bài
(JSON-LD → meta → trafilatura, mục 6.3); lấy `datePublished` **có múi giờ** (không lấy `dateModified`, không lấy
ngày kiểu "10.9" trong thân trang); cào tăng dần bằng `ctx.since` (lúc lần chạy thành công trước kết thúc).

**Không được:** import `psycopg` hay tự ghi DB/R2; tự tạo `httpx.Client`/`requests` (bỏ qua giãn cách và robots);
đổi User-Agent; bắt `DomainBlocked` rồi chạy tiếp; tự loại bài ngắn/thiếu sapo (khung **gắn cờ**, không xoá);
bịa `published_at` khi không có (cứ để trống — khung loại và đếm `published_at_missing`, thấy trong `status`).

Mã lý do loại bài (`crawl_runs.reject_reasons`): `url_missing`, `url_not_https`, `url_invalid`, `article_id_mismatch`,
`source_missing`, `source_unknown`, `source_mismatch`, `category_missing`, `title_missing`, `published_at_missing`,
`published_at_naive`, `published_at_invalid`, `not_an_object`, `json_invalid`. Cờ (không loại): `missing_sapo`,
`no_body`, `short_body` (1–79 từ), `missing_author`, `future_date` (> bây giờ + 1 giờ).

## 4. Test offline với fixture (bắt buộc, không gọi mạng)

1. Lưu trang thật (RSS/sitemap + ≥ 5 bài, gồm ca xấu: video, bài ngắn, thiếu JSON-LD) vào
   `tests/fixtures/crawlers/<source>/`, thêm `routes.yaml` (URL → file; URL thiếu = 404):
   ```yaml
   routes:
     "https://tuoitre.vn/rss/tin-moi-nhat.rss": rss.xml
     "https://tuoitre.vn/bai-1.htm": bai-1.html
   ```
2. **Test hợp đồng tự động**: crawler nào đăng ký trong `sources.yaml` đều bị
   `tests/ingest/test_crawler_contract.py` chạy trên fixture của nó — thiếu fixture hay có bài sai hợp đồng là FAIL.
3. Test riêng của bạn (`tests/ingest/test_<source>.py`) cho giá trị cụ thể:
   ```python
   from eventrank.ingest.testing import check_crawler, fixture_client_from_dir
   def test_tuoitre_tach_dung_chuyen_muc():
       arts = check_crawler(TuoiTreRss(), fixture_client_from_dir("tests/fixtures/crawlers/tuoitre"))
       assert {a.category for a in arts} == {"Thời sự", "Thế giới"}
   ```
   Thử ca xấu bằng `testing.fixture_client({url: httpx.Response(302, …)})` (xem test 302 của crawler ví dụ).
4. `make test` (chạy cả ruff).

## 5. Chạy thử với Postgres cục bộ

```bash
# Postgres cài sẵn (apt, cổng 5432) — làm MỘT lần, mật khẩu tự đặt:
sudo -u postgres psql -c "CREATE ROLE eventrank LOGIN CREATEDB PASSWORD '<mat-khau>'"
sudo -u postgres createdb -O eventrank eventrank
sudo -u postgres createdb -O eventrank eventrank_replay
# (Không có Postgres: đặt POSTGRES_PASSWORD trong .env rồi `make db-up` → cổng 5433)
# .env: DATABASE_URL, REPLAY_DATABASE_URL, TEST_DATABASE_URL, CRAWLER_USER_AGENT — mẫu trong .env.example

make db-migrate                                         # tạo bảng (chạy lại không làm gì)
uv run --group embed python -m eventrank.ingest sources sync
uv run --group embed python -m eventrank.ingest run --source tuoitre --once --force   # chạy thử khi chưa bật
make ingest-status
make test-db                                            # test cần Postgres
```

`--force` chỉ để chạy thử khi `enabled: false`. Chạy định kỳ: `ingest run --source X --loop --interval 600`
(giai đoạn 4 sẽ đưa vào systemd/cron). `run` từ chối DB đang ở chế độ replay.

**Giữ script cào riêng?** Xuất JSONL đúng mục 5.3 rồi `python -m eventrank.ingest import-jsonl '<glob>'` — đi qua
đúng hợp đồng, idempotent, có dòng `crawl_runs` (crawler = `import_jsonl`) để `status` theo dõi.

**Chưa có crawler — phát lại Silver** (vào DB RIÊNG, không trộn với DB import):
`make ingest-replay REPLAY_START=2026-08-01T00:00+07:00 REPLAY_SPEED=60` (60 = 1 phút thật/1 giờ giả lập).
Ctrl+C rồi chạy lại = tiếp tục từ `sim_now`; `ARGS=--reset` để bắt đầu lại; `ingest clock --real` đưa đồng hồ về giờ thật.

## 6. Checklist trước khi đặt `enabled: true`

- [ ] Khảo sát robots.txt / sitemap / RSS theo skill `add-news-source` bước 1; ghi `rss:`/`sitemap:`/`notes:` vào `configs/sources.yaml`.
- [ ] Fixture ≥ 5 bài (có ca xấu) + `routes.yaml`; `make test` xanh (test hợp đồng tự động chạy crawler của bạn).
- [ ] Lát cắt thật `ingest run --source X --once --force --limit 12` vào DB cục bộ: `status` = `ok`,
      `n_rejected` ≈ 0; mở 3 bài ngẫu nhiên so với trang thật (thân bài không lẫn quảng cáo / "Tin liên quan").
- [ ] Truy vấn chất lượng: `SELECT f, count(*) FROM articles, unnest(quality_flags) f WHERE source = '<báo>' GROUP BY 1;`
      — `no_body`/`short_body` cao bất thường = parser hỏng.
- [ ] `parser_version` đã đặt; chạy lại lần hai cho `n_new = 0` (idempotent thật).
- [ ] Người dùng/nhóm đồng ý bật. Backfill lớn thì ước lượng `số bài × 2 s` và báo trước.

## 7. Theo dõi: `make ingest-status`

Mỗi báo: lần chạy cuối, trạng thái, bài mới 1h/24h (chế độ real theo `crawled_at`; replay theo `published_at` so
với `app_now()`), tổng, bài đăng mới nhất, lỗi gần nhất. **Cảnh báo** khi: báo đã bật mà 2 giờ không có bài mới
(crawler chết âm thầm — RSS không lấy lại được quá khứ); lần chạy kẹt `running` > 1 giờ (tiến trình đã chết);
lần chạy cuối `failed`/`blocked` (`blocked` = báo chặn → dừng, báo nhóm, **không vượt chặn**).

## 8. Cạm bẫy

- **Gold offset:** NER Gold tính offset trên văn bản Silver **gốc trên R2**. DB lưu văn bản đã NFC — 264 trường trong
  kho thật là NFD (217 thân bài, 36 sapo, 11 tiêu đề) nên độ dài khác bản gốc. Không ghép offset Gold vào văn bản DB cho các bài đó.
- `content_hash` chỉ gồm trường nội dung đã chuẩn hoá: đổi `parser_version` mà nội dung không đổi → **không** UPDATE (giữ `parser_version` cũ).
- `ingested_via` = đường ghi **lần cuối** (bài import rồi được crawler cập nhật sẽ thành `crawler:…`).
- `future_date` tính lúc nạp; không tự gỡ khi thời gian trôi qua.
- `urllib.robotparser` không hiểu wildcard `*`/`$` trong đường dẫn robots → báo nào dùng thì cân nhắc `protego`.
- `RobotsDisallowed` dừng **cả lần chạy** (`blocked`): crawler đang xin URL bị cấm là lỗi thiết kế, cần người xem.
- Migration chạy trong transaction: không dùng `CREATE INDEX CONCURRENTLY` trong file migration.
- `replay` nạp toàn bộ Silver vào RAM (~28,7 nghìn bài) — đủ cho demo, không dùng cho kho lớn hơn nhiều.

## 9. Lệnh kiểm tra

```bash
make test                     # pytest (test `db` tự skip nếu thiếu TEST_DATABASE_URL) + ruff + typecheck web
make test-db                  # chỉ test cần Postgres
make db-status                # migration đã áp?
make ingest-status
uv run --group embed python -m eventrank.ingest --help
```

## 10. Gợi ý cho giai đoạn 2 (worker)

- Lấy bài cần xử lý bằng **anti-join** `articles` ↔ bảng embedding theo `(article_id, content_hash)` (bền với
  transaction commit lệch thứ tự), không chỉ theo mốc `updated_at`.
- "Bây giờ" luôn đọc `app_now()`; cửa sổ gom cụm 48h tính theo `published_at ≤ app_now()`.
- Vector lưu `bytea` (float32) + cột `model_version`; bảng sự kiện/tên/điểm thêm bằng `002_….sql`.
