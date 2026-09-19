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
| 1. Thu thập | Crawler: sitemap (backfill), RSS (tin mới), hộp "Xem nhiều" | → R2 `bronze/` |
| 2. Kho dữ liệu | Bronze → Silver → Gold → snapshots | Cloudflare R2, bucket `event-lake` |
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
| API, WEB, MOBILE | `apps/{api,web,mobile}/` | chia theo tab |
| INFRA, DOCS | `infra/`, `docs/`, `configs/`, file cấu hình AI agent | cả nhóm |

Thư mục nào chưa tồn tại là **chưa đến giai đoạn đó** — không tự tạo trước khi được yêu cầu.

## Lệnh thường dùng

```bash
uv sync                          # cài phụ thuộc theo uv.lock
uv run pytest -q                 # chạy toàn bộ test
uv run pytest tests/<module> -q  # chạy test một module
uv run ruff check . && uv run ruff format --check .
```

Mặc định chạy với `LAKE_BACKEND=local`. **Chỉ chuyển sang `r2` khi người dùng yêu cầu rõ.**

---

# QUY TẮC BẮT BUỘC

## 1. Bí mật

- **Không bao giờ đọc, in, `cat`, `echo` nội dung `.env`.** Cần kiểm tra biến có tồn tại thì chỉ in **độ dài**, không in giá trị.
- Không đưa khoá R2 vào code, notebook, log, commit message, tin nhắn.
- Người dùng dán khoá vào hội thoại → **nhắc họ thu hồi khoá đó ngay**, không dùng tiếp.

## 2. Kho dữ liệu (chi tiết: skill `data-lake`)

- **Bronze là bất biến.** Không sửa, không xoá, không ghi đè. R2 **không có versioning** — xoá là mất vĩnh viễn, và dữ liệu RSS không lấy lại được.
- **Không chạy bất kỳ lệnh xoá nào trên bucket** nếu người dùng chưa yêu cầu rõ và chưa xác nhận lại.
- Mỗi người chỉ ghi vào **vùng `source=` của báo mình phụ trách**. Không ghi vào vùng của người khác.
- Bài gần trùng giữa các báo được **đánh dấu `dup_group_id`, không xoá** — đó là tín hiệu chính của đề tài.

## 3. Thu thập dữ liệu (chi tiết: skill `add-news-source`)

- Tối thiểu **2 giây/request cho mỗi domain**. Dùng User-Agent trung thực trong `.env`.
- Tôn trọng `robots.txt`. Báo chặn hoặc chuyển hướng (VnExpress trả 302 cho sitemap) → **dừng, báo người dùng, không tìm cách vượt chặn**.
- Nhận về HTML thay vì XML khi đọc sitemap → coi là **lỗi**, không coi là "sitemap rỗng".

## 4. Đánh giá mô hình (chi tiết: skill `eval-protocol`)

- Không báo cáo con số nào **thiếu baseline và thiếu khoảng tin cậy**.
- Không dùng silhouette để so sánh hai mô hình embedding. Dùng B-Cubed.

## 5. Git

- **Không tự commit, không tự push** nếu người dùng chưa yêu cầu rõ.
- Làm trên nhánh `feat/<module>-<mô-tả>`; merge vào `dev` qua Pull Request, điền đủ mẫu PR.
- Commit message bắt đầu bằng mã module: `[LAKE] ghi Silver theo lô`.
- Không `push --force` lên `dev` hoặc `main`.

## 6. Làm việc trong nhóm nhiều người, nhiều máy

- Git và Pull Request là cơ chế đồng bộ duy nhất. **Không** tạo file registry/lock/nhật ký dùng chung trong repo — mỗi người ở một máy, một nhánh, các file đó chỉ gây xung đột merge.
- Nhật ký thay đổi nằm trong **mô tả Pull Request** (mẫu ở `.github/pull_request_template.md`).
- Bàn giao một module cho người khác → viết `docs/handoff/<module>.md`: trạng thái, việc còn dở, lệnh kiểm tra, cạm bẫy.
- Đổi schema dữ liệu hoặc cấu trúc key trên bucket → sửa `docs/lake-layout.md` / `docs/data-contracts.md` **trong cùng PR**.

## 7. Báo cáo kết quả

- Dán **kết quả chạy thật** (test, truy vấn chất lượng), không mô tả suông "đã chạy được".
- Chưa chạy được thì nói rõ chưa chạy và vì sao.
