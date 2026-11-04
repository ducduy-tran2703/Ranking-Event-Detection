# Ranking-Event-Detection — Hướng dẫn cho AI agent

> File gốc duy nhất cho mọi AI agent (Claude Code, Codex, Cursor, Copilot...).
> `CLAUDE.md` chỉ import file này. **Sửa quy tắc ở đây, không sửa trong CLAUDE.md.**
> Mọi đường dẫn trong file là **đường dẫn tương đối tính từ gốc repo** — repo được clone ở nhiều máy khác nhau.

## Dự án là gì

Đồ án PBL: nhận diện **sự kiện** từ tin tức của nhiều báo tiếng Việt, đặt tên ngắn (5–10 từ) cho mỗi sự kiện, và xếp hạng độ "nóng" để hiển thị bảng xu hướng trên web và mobile.

Đơn vị phân tích là **sự kiện**, không phải bài báo: 12 báo cùng đưa một tin → 1 sự kiện.

## Kiến trúc 5 tầng (dữ liệu chỉ chảy lên trên)

| Tầng | Thành phần | Lưu ở đâu |
|---|---|---|
| 1. Thu thập | Crawler: sitemap (backfill), RSS (tin mới), hộp "Xem nhiều" | Postgres `articles` (khung `eventrank.ingest`, chưa có crawler thật) · R2 `silver/` (kho chung, do từng người cào) |
| 2. Kho dữ liệu | **Hiện có: Silver (văn bản) + Gold (NER) dạng JSONL**, nhãn yếu, mô hình, kết quả chạy, dump DB (các prefix `…_NguyenDinhHieu/`). Hướng tới: Bronze → Silver → Gold → snapshots | Cloudflare R2, bucket `vietnam-news-datalake` — xem `docs/tong-hop.md` mục 5.2 |
| 3. Xử lý / ML | NER → nhãn yếu → embedding → gom cụm → đặt tên → xu hướng (hiện chạy **theo lô**: `make pipeline` → `data/runs/<run_id>/`) | Huấn luyện trên Kaggle; suy luận ở máy; ghi `data/` |
| 4. Phục vụ | FastAPI (`apps/api/`) đọc run (`EVENTS_BACKEND=files`) hoặc Postgres (`db`) | Postgres (`infra/db/migrations/`) |
| 5. Giao diện | Web React (`apps/web/`); mobile app (thông báo đẩy) chưa làm | — |

Tầng dưới **không được import** tầng trên. Chiều phụ thuộc trong `src/`:
`common ← ingest ← lake ← nlp ← weak_labels ← embeddings ← clustering ← naming, trending ← serving ← apps`

## Bản đồ module

| Mã | Thư mục | Người phụ trách |
|---|---|---|
| INGEST, LAKE | `src/eventrank/{ingest,lake}/`, `jobs/` | A |
| NLP, WEAK | `src/eventrank/{nlp,weak_labels}/` | B |
| EMB, CLUST | `src/eventrank/{embeddings,clustering}/`, `training/` | C |
| NAME, TREND, EVAL | `src/eventrank/{naming,trending,evaluation}/` | D |
| SERVING | `src/eventrank/serving/` — điều phối pipeline, nạp run/DB cho API | — |
| API | `apps/api/main.py` — backend FastAPI | A |
| Trang kiểm soát dữ liệu (nội bộ) | `apps/api/static/` — HTML/JS thuần, FastAPI phục vụ trực tiếp | A |
| WEB (công khai) | `apps/web/` — React + Vite + TypeScript | chia theo trang |
| MOBILE | `apps/mobile/` — chưa làm | — |
| INFRA, DOCS | `infra/`, `docs/`, `configs/`, file cấu hình AI agent | cả nhóm |

Thư mục nào chưa tồn tại là **chưa đến giai đoạn đó** — không tự tạo trước khi được yêu cầu.

## Trạng thái hiện tại (cập nhật 04/11/2026)

Bảng đầy đủ (kèm số đo, mốc so sánh, CI): `docs/tong-hop.md` mục 0.2. Nhãn đối chiếu hầu hết do **Claude** gán, chưa phải người.

| Phần | Trạng thái | Đọc gì trước |
|---|---|---|
| Kho Silver + Gold (NER) trên R2 | có; 6 báo, 28.746 bài, dữ liệu tĩnh đến 19/09/2026; Gold offset tính trên văn bản ghép `Tiêu đề: …\n\nSapo: …\n\nNội dung:\n…` | `docs/tong-hop.md` mục 5.2–5.5 |
| Thu thập + Postgres (`001_ingest`) | khung crawler + import/replay xong, có test; **chưa có crawler thật** (mọi báo `enabled: false`) | `docs/tong-hop.md` mục 16, 17.4 |
| Định nghĩa "sự kiện" | **đã chốt Gói 1 / hướng E** + thang 4 mức + quy tắc R1–R6 | `docs/tong-hop.md` mục 4 |
| Nhãn yếu (`src/eventrank/weak_labels/`) | v3 nhị phân (precision 0,93, recall 0,28) + **v4 4 mức `final_v3`** (dữ liệu train hiện tại) | `docs/tong-hop.md` mục 7 |
| Embedding | 7 mô hình đã đo; pipeline dùng bkai fine-tune v1 (`bkai_ft_v1_s44`) | `docs/tong-hop.md` mục 8 |
| Gom cụm, đặt tên, xu hướng | **chạy theo lô** (`make pipeline`); run đang phục vụ `data/runs/2026-11-03_v2`; gom cụm B-Cubed 0,967 (nhãn Claude); đặt tên chưa có số trên tập test; xu hướng chưa đánh giá | `docs/tong-hop.md` mục 9, 10 |
| Tầng sự kiện Postgres (`002_events`), API, web | chạy được; web có khu tài khoản **giả lập** (`VITE_AUTH_MOCK`) | `docs/tong-hop.md` mục 11, 16 |
| Worker liên tục, đối chiếu ID, thông báo, tài khoản thật (003–006), mobile | chưa làm | `docs/tong-hop.md` mục 18 |

⚠ **Ẩn tên cửa sổ 14–15/09/2026** (tập test đặt tên cần tên người viết mù): không đưa tên mô hình của sự kiện giao cửa sổ này
(và tên gần trùng) vào tài liệu, web, DB, ví dụ; không đặt `EVENTS_HIDE_NAMES_WINDOW=off` khi có người xem. Chi tiết
`docs/tong-hop.md` mục 11.3.

## Lệnh thường dùng

```bash
make                 # xem danh sách lệnh
make install         # cài thư viện Python (uv) và JavaScript (npm)
make dev             # chạy backend :8000 + frontend :5173 trong một terminal
make test            # test Python + lint + kiểm tra kiểu frontend
make types           # sinh lại kiểu TypeScript sau khi sửa apps/api/schemas.py
make embed           # embedding ngữ nghĩa cho nhãn yếu (tải mô hình ~135 MB lần đầu)
make weak-labels     # sinh nhãn yếu → data/weak_labels/v3/ (cần data/lake/{gold,silver} và make embed trước)
make pipeline        # gom cụm → đặt tên → xu hướng → data/runs/<run_id>/ (docs/tong-hop.md mục 9.4)
make db-import-run   # nạp một run vào tầng sự kiện Postgres
make agreement       # đo đồng thuận nhãn người ↔ nhãn LLM (Cohen's κ)
make db-migrate      # áp migration Postgres (infra/db/migrations/) vào DATABASE_URL
make ingest-status   # tình trạng từng báo trong Postgres (viết crawler: docs/tong-hop.md mục 17.4)
make test-db         # test cần Postgres (TEST_DATABASE_URL), thiếu biến thì skip
```

| Địa chỉ | Là gì |
|---|---|
| http://127.0.0.1:5173 | Web React (Vite) — tự chuyển tiếp `/api` sang backend |
| http://127.0.0.1:8000 | Trang kiểm soát dữ liệu nội bộ (sau `make build`: web React; trang cũ ở `/legacy/`) |
| http://127.0.0.1:8000/docs | Tài liệu API tự sinh |

- **Test** luôn dùng dữ liệu mẫu trong `tests/fixtures/`, không cần khoá, không gọi mạng.
- **Trang kiểm soát** chỉ **đọc** R2 (`LAKE_BACKEND=r2`), nên dùng khoá *Object Read only*.
- **Code ghi dữ liệu** chỉ ghi vào máy (`data/`, gitignored) hoặc Postgres; không lệnh nào tự ghi R2. **Chỉ ghi lên R2 khi người dùng yêu cầu rõ**, vào prefix mới.

---

# QUY TẮC BẮT BUỘC

## 1. Bí mật

- **Không bao giờ đọc, in, `cat`, `echo` nội dung `.env`.** Cần kiểm tra biến có tồn tại thì chỉ in **độ dài**, không in giá trị.
- Không đưa khoá R2 vào code, notebook, log, commit message, tin nhắn.
- Người dùng dán khoá vào hội thoại → **nhắc họ thu hồi khoá đó ngay**, không dùng tiếp.

## 2. Kho dữ liệu (chi tiết: skill `data-lake`)

- **Đọc `docs/tong-hop.md` mục 5.2 (bố cục kho) và 5.3 (hợp đồng dữ liệu) trước khi đọc hay ghi kho.** Đó là mô tả đúng của dữ liệu thật; đừng đoán cấu trúc.
- Kho hiện có `silver/<source>/*.jsonl` (**mỗi báo một file**; ghi lại là **thay thế toàn bộ dữ liệu của báo** → không ghi đè khi người dùng chưa xác nhận), `gold/gold_data.jsonl` (NER cả bài, không chứa văn bản — join Silver theo `article_id`) và `weak_label_NguyenDinhHieu/` (nhãn yếu v1, chỉ đọc). Bản mới ghi vào prefix mới (`…/v2/`), **không ghi đè**.
- R2 **không có versioning** — xoá hay ghi đè là mất vĩnh viễn, và dữ liệu RSS không lấy lại được. **Không chạy bất kỳ lệnh xoá nào** khi người dùng chưa yêu cầu rõ và xác nhận lại.
- Khi có lớp Bronze: **Bronze là bất biến** — không sửa, không xoá, không ghi đè.
- Mỗi người chỉ ghi vào **thư mục `silver/<source>/` của báo mình phụ trách**.
- Khoá của một bài là `article_id = sha256(url)`. Khử trùng lặp theo khoá này.
- Bài gần trùng giữa các báo được **đánh dấu `dup_group_id`, không xoá** — đó là tín hiệu chính của đề tài.

## 2b. Hợp đồng API giữa backend và frontend

- Hình dạng JSON của API khai báo trong **`apps/api/schemas.py`** (Pydantic). Endpoint mà web dùng phải có `response_model=`.
- `apps/web/openapi.json` và `apps/web/src/api/schema.d.ts` **sinh tự động** bằng `make types` — **không sửa tay**.
- Sửa `schemas.py` → chạy `make types` → **commit cả hai file sinh ra trong cùng PR**. Frontend báo lỗi kiểu ở đâu thì sửa ở đó.
- Frontend chỉ gọi backend qua `apps/web/src/api/` (`client.ts`, `queries.ts`), không gọi `fetch` rải rác trong các trang.
- TypeScript đang ghim ở **5.x**: `openapi-typescript` không chạy được với TypeScript 7.

## 3. Thu thập dữ liệu (chi tiết: skill `add-news-source`)

- Tối thiểu **2 giây/request cho mỗi domain**. Dùng User-Agent trung thực trong `.env`.
- Tôn trọng `robots.txt`. Báo chặn hoặc chuyển hướng (VnExpress trả 302 cho sitemap) → **dừng, báo người dùng, không tìm cách vượt chặn**.
- Nhận về HTML thay vì XML khi đọc sitemap → coi là **lỗi**, không coi là "sitemap rỗng".

## 4. Đánh giá mô hình (chi tiết: skill `eval-protocol`)

- Không báo cáo con số nào **thiếu baseline và thiếu khoảng tin cậy**.
- Không dùng silhouette để so sánh hai mô hình embedding. Dùng B-Cubed.

## 4b. Nhãn yếu (chi tiết: `docs/tong-hop.md` mục 7)

- **Không bao giờ chỉnh ngưỡng trên chính mẫu dùng để đo.** Tập chỉnh = `data/weak_labels/v1/audit_labeled_llm_ids.csv`; tập đo = `data/weak_labels/v2/audit_labeled_llm.csv`. Đổi luật → đo lại bằng `python -m eventrank.weak_labels.evaluate`.
- Precision/recall phải tính **có trọng số theo tầng** (`evaluate.py`), không dùng tỉ lệ thô trên mẫu phân tầng.
- Mọi luật mới phải có test viết trước (`tests/weak_labels/`) và **bằng chứng đo được** ghi trong docstring.
- Nhãn đối chiếu hiện là của Claude, **chưa phải người** — không báo cáo như nhãn vàng.
- Chạy `uv run` **không kèm `--group embed`** sẽ gỡ PyTorch/onnxruntime khỏi `.venv`; các lệnh `make` đã kèm sẵn.

## 5. Git

- **Không tự commit, không tự push** nếu người dùng chưa yêu cầu rõ.
- `main` = bản sản phẩm, `dev` = bản thử nghiệm. Làm trên nhánh `feat/<module>-<mô-tả>` tách từ `dev`; merge vào `dev` qua Pull Request, điền đủ mẫu PR.
- Commit message bắt đầu bằng mã module: `[LAKE] ghi Silver theo lô`.
- Không `push --force` lên `dev` hoặc `main`.

## 6. Làm việc trong nhóm nhiều người, nhiều máy

- Git và Pull Request là cơ chế đồng bộ duy nhất. **Không** tạo file registry/lock/nhật ký dùng chung trong repo — mỗi người ở một máy, một nhánh, các file đó chỉ gây xung đột merge.
- Nhật ký thay đổi nằm trong **mô tả Pull Request** (mẫu ở `.github/pull_request_template.md`).
- Bàn giao một module cho người khác → viết/cập nhật **mục bàn giao của module trong `docs/tong-hop.md`** (mục 17, xem 17.6): trạng thái, việc còn dở, lệnh kiểm tra, cạm bẫy. Không tạo file `docs/handoff/` riêng — dự án giữ **một** tài liệu tổng.
- Đổi schema dữ liệu hoặc cấu trúc key trên bucket → sửa `docs/tong-hop.md` mục 5.2 / 5.3 **trong cùng PR**.

## 7. Báo cáo kết quả

- Dán **kết quả chạy thật** (test, truy vấn chất lượng), không mô tả suông "đã chạy được".
- Chưa chạy được thì nói rõ chưa chạy và vì sao.
