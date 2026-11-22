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
| 1. Thu thập | Crawler: sitemap (backfill), RSS (tin mới), hộp "Xem nhiều" | → R2 `silver/` (hiện tại) · `bronze/` (hướng tới) |
| 2. Kho dữ liệu | **Hiện có: Silver (văn bản) + Gold (NER) dạng JSONL**, cùng nhãn yếu v1 (`weak_label_NguyenDinhHieu/`). Hướng tới: Bronze → Silver → Gold → snapshots | Cloudflare R2, bucket `vietnam-news-datalake` — xem `docs/tong-hop.md` mục 5.2 |
| 3. Xử lý / ML | NER → nhãn yếu → embedding → gom cụm → đặt tên → xu hướng | Đọc/ghi R2; huấn luyện trên Kaggle/Colab |
| 4. Phục vụ | FastAPI + Postgres (sự kiện, tên, điểm, thông báo đã gửi) | Postgres |
| 5. Giao diện | Web dashboard, mobile app (thông báo đẩy) | — |

Tầng dưới **không được import** tầng trên. Chiều phụ thuộc trong `src/`:
`common ← ingest ← lake ← nlp ← weak_labels ← embeddings ← clustering ← naming, trending ← serving ← apps`

## Bản đồ module

| Mã | Thư mục | Người phụ trách |
|---|---|---|
| INGEST, LAKE | `src/eventrank/{ingest,lake}/`, `jobs/` | A |
| NLP, WEAK | `src/eventrank/{nlp,weak_labels}/` | B |
| EMB, CLUST | `src/eventrank/{embeddings,clustering}/`, `training/` | C |
| NAME, TREND, EVAL | `src/eventrank/{naming,trending,evaluation}/` | D |
| API | `apps/api/main.py` — backend FastAPI | A |
| Trang kiểm soát dữ liệu (nội bộ) | `apps/api/static/` — HTML/JS thuần, FastAPI phục vụ trực tiếp | A |
| WEB (công khai) | `apps/web/` — React + Vite + TypeScript | chia theo trang |
| MOBILE | `apps/mobile/` — chưa làm | — |
| INFRA, DOCS | `infra/`, `docs/`, `configs/`, file cấu hình AI agent | cả nhóm |

Thư mục nào chưa tồn tại là **chưa đến giai đoạn đó** — không tự tạo trước khi được yêu cầu.

## Trạng thái hiện tại (cập nhật 04/10/2026)

| Phần | Trạng thái | Đọc gì trước |
|---|---|---|
| Thu thập + kho Silver | chạy được, 6 báo, ~28,7 nghìn bài | `docs/tong-hop.md` mục 5.2–5.3 |
| Gold (NER) | có trên R2, do thành viên khác làm; offset tính trên văn bản ghép `Tiêu đề: …\n\nSapo: …\n\nNội dung:\n…` | `data/lake/gold/README.md` (tải về), `docs/tong-hop.md` mục 5.4–5.5 |
| **Nhãn yếu** (`src/eventrank/weak_labels/`) | **v3 xong**: precision cặp dương 0,93, recall 0,28 (đo bằng Claude gán mù, có trọng số theo tầng) | **`docs/tong-hop.md` mục 7** |
| Định nghĩa "sự kiện" | **đã chốt Gói 1 / hướng E**: đơn vị = sự kiện tin tức, nhóm cha = câu chuyện | `docs/tong-hop.md` mục 4 |
| Embedding, gom cụm, đặt tên, xu hướng | **chưa làm** (thư mục chưa tồn tại) | `docs/tong-hop.md` mục 7.13, 8, 9 |
| Web/API kiểm soát dữ liệu | chạy được | `docs/tong-hop.md` mục 11 |

**RAG (mốc riêng 06/11/2026):** đã có migration 007, NER/chunk Postgres, BM25, Qwen/Gemma
services trên Modal và dense Qdrant đủ 96.230 point. Dense search/resume và hybrid RRF
(trace, bộ lọc, fallback) đã kiểm thật; đã có chọn context/pipeline hỏi đáp CLI/API trên snapshot. Người tiếp nhận đọc
[`docs/plan-rag.md`](docs/plan-rag.md) rồi [`docs/handoff/rag.md`](docs/handoff/rag.md);
Lượt tiếp theo kiểm thử hỏi đáp theo bàn giao; không embedding lại corpus đã ready.
Mốc này không cập nhật lại các mục ML khác ở bảng cũ.

**RAG tool calling (22/11/2026, nhánh `feat/rag-tool-calling`):** chatbot gọi tool (tìm tin, đếm bài, sự kiện
nổi bật, hồ sơ người dùng), nhớ 3 lượt hội thoại, cá nhân hoá theo hồ sơ (migration 010). **Bật mặc định**
từ 22/11 (`tool_calling.enabled: true`). Đọc [`docs/handoff/rag-tool-calling.md`](docs/handoff/rag-tool-calling.md) và
[`docs/handoff/rag-tool-calling-issues.md`](docs/handoff/rag-tool-calling-issues.md) (lỗi còn gặp, sửa trước tiên).

## Lệnh thường dùng

```bash
make                 # xem danh sách lệnh
make install         # cài thư viện Python (uv) và JavaScript (npm)
make dev             # chạy backend :8000 + frontend :5173 trong một terminal
make test            # test Python + lint + kiểm tra kiểu frontend
make types           # sinh lại kiểu TypeScript sau khi sửa apps/api/schemas.py
make embed           # embedding ngữ nghĩa cho nhãn yếu (tải mô hình ~135 MB lần đầu)
make weak-labels     # sinh nhãn yếu → data/weak_labels/v3/ (cần data/lake/{gold,silver} và make embed trước)
make agreement       # đo đồng thuận nhãn người ↔ nhãn LLM (Cohen's κ)
make db-migrate      # áp migration Postgres (infra/db/migrations/) vào DATABASE_URL
make ingest-status   # tình trạng từng báo trong Postgres (crawler: docs/handoff/ingest.md)
make crawler         # dịch vụ cào 8 báo, CÀO NGAY khi bật, nạp vào Postgres (cần CRAWLER_USER_AGENT trong .env)
make worker          # bài mới trong Postgres → embedding → gom cụm giữ event_id → đặt tên → xu hướng (docs/handoff/worker.md)
make test-db         # test cần Postgres (TEST_DATABASE_URL), thiếu biến thì skip
```

| Địa chỉ | Là gì |
|---|---|
| http://127.0.0.1:5173 | Web React (Vite) — tự chuyển tiếp `/api` sang backend |
| http://127.0.0.1:8000 | Trang kiểm soát dữ liệu nội bộ |
| http://127.0.0.1:8000/docs | Tài liệu API tự sinh |

- **Test** luôn dùng dữ liệu mẫu trong `tests/fixtures/`, không cần khoá, không gọi mạng.
- **Trang kiểm soát** chỉ **đọc** R2 (`LAKE_BACKEND=r2`), nên dùng khoá *Object Read only*.
- **Code ghi dữ liệu** mặc định ghi vào máy (`LAKE_BACKEND=local`). **Chỉ ghi lên R2 khi người dùng yêu cầu rõ.**

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
- Làm trên nhánh `feat/<module>-<mô-tả>`; merge vào `dev` qua Pull Request, điền đủ mẫu PR.
- Commit message bắt đầu bằng mã module: `[LAKE] ghi Silver theo lô`.
- Không `push --force` lên `dev` hoặc `main`.

## 6. Làm việc trong nhóm nhiều người, nhiều máy

- Git và Pull Request là cơ chế đồng bộ duy nhất. **Không** tạo file registry/lock/nhật ký dùng chung trong repo — mỗi người ở một máy, một nhánh, các file đó chỉ gây xung đột merge.
- Nhật ký thay đổi nằm trong **mô tả Pull Request** (mẫu ở `.github/pull_request_template.md`).
- Bàn giao một module cho người khác → viết `docs/handoff/<module>.md`: trạng thái, việc còn dở, lệnh kiểm tra, cạm bẫy.
- Đổi schema dữ liệu hoặc cấu trúc key trên bucket → sửa `docs/tong-hop.md` mục 5.2 / 5.3 **trong cùng PR**.

## 7. Báo cáo kết quả

- Dán **kết quả chạy thật** (test, truy vấn chất lượng), không mô tả suông "đã chạy được".
- Chưa chạy được thì nói rõ chưa chạy và vì sao.
