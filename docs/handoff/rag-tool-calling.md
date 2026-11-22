# Bàn giao: chatbot RAG có tool calling + cá nhân hoá

Nhánh `feat/rag-tool-calling` (đã gộp `feat/web-rag-chat`: tài khoản + khung chat). Cập nhật 22/11/2026.
Lỗi còn gặp và việc còn dở: [rag-tool-calling-issues.md](rag-tool-calling-issues.md).
Luồng RAG gốc (BM25, Qdrant, Modal, sync): [rag.md](rag.md).

## 1. Tóm tắt cho người tích hợp BE

- Web/BE **không gọi pipeline trực tiếp**. Người dùng đăng nhập → gửi câu hỏi vào hàng đợi `POST /api/rag/messages`
  → worker nền trong tiến trình API trả lời → web hỏi lại `GET /api/rag/messages/{id}` tới khi xong.
- **`user_id` KHÔNG gửi trong body.** API lấy người dùng từ cookie phiên `er_session` (tầng tài khoản
  `apps/api/accounts.py`). Mọi POST/PUT/DELETE phải kèm header `X-CSRF-Token` = giá trị cookie `csrf_token`.
  Thiết kế này để không ai tự khai `user_id` của người khác. Nếu BE là dịch vụ riêng cần gọi thay người dùng
  (server-to-server) thì phải thêm endpoint nội bộ + token dịch vụ — **chưa có**.
- Tool calling chỉ chạy qua hàng đợi chat. `POST /api/rag/ask` (đồng bộ, app chính chỉ cho admin; app riêng :8001)
  vẫn là pipeline snapshot cũ.
- Công tắc: `configs/rag.yaml` → `tool_calling.enabled`. **Hiện để `false`** (chat chạy pipeline cũ, single-turn).
  Đặt `true` rồi khởi động lại API là chat chuyển sang tool calling + hội thoại nhiều lượt + hồ sơ.

## 2. Điều kiện để bật

| Thành phần | Yêu cầu | Kiểm tra |
|---|---|---|
| Postgres | Áp migration 001–010 (008–009 chat, **010 hồ sơ**) | `python -m eventrank.common.db status` |
| Qdrant | Collection `rag_v1_qwen_text_v1` 96.230 point, `published=true` | `curl http://127.0.0.1:6333/readyz` |
| BM25 | `data/rag/bm25/CURRENT.json` | xem [rag.md](rag.md) |
| Modal | App `eventrank-rag-models` deploy với `models.llm.tool_calling: true` (thêm `--enable-auto-tool-choice --tool-call-parser gemma4`). **Đã deploy 22/11/2026** | `.env.client` có `RAG_LLM_URL` |
| Tokenizer Gemma | Cache local | `python -m eventrank.rag.token_budget prepare` (lần đầu) |
| BamiBERT | `data/models/bamibert-qft-s44/best` (GPU nếu có) | thiếu thì vẫn chạy, chỉ không có NER boost |

vLLM 0.33.0 đang ghim đã có parser `gemma4`; dùng chat template của chính model (đã hỗ trợ tool), **không** dùng
`--chat-template` của vLLM — để bộ đếm token phía client khớp server (đã đo: khớp 10/10 câu).

## 3. API

Tất cả dưới `/api/rag`, cần đăng nhập trừ `/status`. Khai báo kiểu ở `apps/api/schemas.py`; TypeScript sinh ở
`apps/web/src/api/schema.d.ts`.

| Method | Đường dẫn | Body | Trả |
|---|---|---|---|
| GET | `/status` | — | `available`, `problems`, `snapshot`, hạn mức của người đang đăng nhập |
| POST | `/messages` | `{question, conversation_id?, source?, date_from?, date_to?}` | **202** + lượt `queued` |
| GET | `/messages/{id}` | — | Lượt hỏi đáp (xem dưới) |
| POST | `/messages/{id}/cancel` | — | Lượt `cancelled` |
| GET | `/conversations` | — | Danh sách cuộc trò chuyện |
| GET / DELETE | `/conversations/{id}` | — | Chi tiết (mọi lượt) / xoá |
| GET | `/profile` | — | Hồ sơ cá nhân hoá |
| PUT | `/profile` | Các trường muốn đổi; gửi `null` để xoá trường | Hồ sơ sau khi sửa |
| POST | `/profile/confirm` | `{accept: true/false}` | Áp hoặc bỏ thay đổi nghề đang chờ |
| DELETE | `/profile` | — | 204 |

Mã lỗi: 401 chưa đăng nhập · 403 thiếu/sai CSRF · 409 câu trước còn chờ (mỗi người 1 lượt) · 429 hết lượt/24 giờ
(`RAG_DAILY_LIMIT`, mặc định 30; admin không giới hạn) · 422 sai dữ liệu (ví dụ chuyên mục ngoài danh sách).

### Một lượt hỏi đáp (`RAGChatMessage`)

`status`: `queued` → `running` → một trong:

| status | Nghĩa | Web hiển thị |
|---|---|---|
| `answered` | Trả lời có nguồn đã kiểm | `answer` (có `[1]`, `[2]`) + `sources` |
| `insufficient_evidence` | Kho không đủ bằng chứng | `answer` là câu cố định |
| `smalltalk` | Chào hỏi / xác nhận hồ sơ, **không có nguồn** (chỉ khi tool calling bật) | `answer` |
| `invalid_generation` | Câu trả lời model không qua kiểm trích dẫn → bị loại | thông báo lỗi |
| `unsupported_query` | Chỉ ở pipeline cũ (câu thống kê/"hôm nay" thiếu ngày) | gợi ý hỏi lại |
| `failed` / `cancelled` | Lỗi hạ tầng (câu an toàn trong `error`) / người dùng dừng | |

`sources[]` có hai loại theo `kind`:

```json
{"citation_id": 1, "kind": "chunk", "title": "Đánh bại U23 Philippines...", "url": "https://tuoitre.vn/...",
 "source": "tuoitre", "published_at": "2026-09-18T...", "quotes": ["U23 Việt Nam đánh bại U23 Philippines 2-0"],
 "event_id": "E20260918-...", "event_name": "...", "chunk_id": "...", "article_id": "...", "start_char": 0, ...}

{"citation_id": 2, "kind": "data", "tool": "count_articles", "title": "Đếm bài trong kho",
 "text": "Kho dữ liệu có 2086 bài báo của báo vnexpress, đăng từ 2026-09-01 đến 2026-09-30.",
 "quotes": ["có 2086 bài báo của báo vnexpress"], "url": null, "source": null, "event_id": null}
```

`kind="data"` là số liệu do tool truy vấn kho sinh ra (đếm bài, phạm vi kho, sự kiện nổi bật): **không có link**,
hiển thị `title` + `text`. `ChatPage.tsx` đã xử lý cả hai loại.

### Hồ sơ (`RAGProfile`)

| Trường | Giá trị |
|---|---|
| `persona` | `pho_thong`, `doanh_nhan`, `ke_toan`, `nha_dau_tu`, `sinh_vien`, `giao_vien`, `can_bo_cong_chuc`, `nha_bao`, `lap_trinh_vien`, `khac` |
| `occupation_text` | Nghề tự mô tả khi `persona = khac` (≤ 60 ký tự) |
| `address_user`, `address_self` | Cách gọi người dùng / chatbot tự xưng (≤ 30) |
| `tone` | `than_thien`, `trang_trong`, `ngan_gon` |
| `answer_length` | `ngan`, `vua`, `chi_tiet` |
| `interests` | ≤ 10, chỉ trong `profile.categories` (khớp `events.category_std`) |
| `pending` | Thay đổi nghề do chatbot suy ra, **chờ người dùng xác nhận** qua `/profile/confirm` |

Chatbot tự cập nhật hồ sơ khi người dùng nói về bản thân trong chat. Xưng hô/giọng/chuyên mục áp ngay; đổi nghề
chỉ vào `pending` và câu trả lời có thêm dòng nhắc xác nhận. Không lưu tuổi, giới tính, địa chỉ.
Web **chưa có trang Hồ sơ** — cần làm để người dùng xem/sửa/xác nhận.

## 4. Bên trong một lượt (khi bật tool calling)

1. Nạp hồ sơ, báo bị ẩn (`user_settings.hidden_sources`), 3 lượt trước của cuộc trò chuyện.
2. Gemma nhận câu hỏi + danh sách tool, tối đa 3 vòng gọi tool, ≤ 4 lệnh mỗi vòng. Tool chỉ đọc, SQL viết sẵn,
   tham số kiểm bằng Pydantic: `search_news` (BM25 + Qwen/Qdrant + NER), `corpus_info`, `count_articles`,
   `top_events`, `event_articles`, `update_user_profile` (chỉ khi đăng nhập).
3. Lượt trả lời cuối không có tool, ép JSON; mỗi ý phải trích **nguyên văn** từ bằng chứng (kể cả số liệu SQL).
   URL luôn lấy từ DB. Quote sai → bỏ ý; dẫn bằng chứng không tồn tại → loại cả câu.
4. Worker ghi `answer`, `sources`, `trace` (tool đã gọi, NER, thay đổi hồ sơ; API không trả `trace`).

Code: `src/eventrank/rag/agent.py`, `tools.py`, `profile.py`, `chat.py`; API `apps/api/rag_chat.py`.

## 5. Kết quả kiểm (22/11/2026)

- Test: `tests/rag tests/common tests/api` 310 passed; test Postgres (database tạm) 68 passed khi đặt
  `TEST_DATABASE_URL`; Ruff đạt; `tsc --noEmit` đạt.
- E2E thật (Postgres 28.725 bài, Qdrant, Gemma Modal, BamiBERT GPU), cuộc trò chuyện 7 lượt, chạy 5 lần.
  Đúng ổn định: câu thông tư thuế (nguồn thật), đếm bài VnExpress tháng 9 (2.086), lưu xưng hô "chị Lan",
  chào hỏi; câu vừa giới thiệu nghề vừa hỏi tin gọi đủ 2 tool 6/6. Lỗi còn lại xem file lỗi.
- Thời gian: lượt đầu khi GPU nguội ~300 s; khi GPU đang chạy 3–35 s/lượt.
  Đây là smoke chức năng, **chưa phải đánh giá chất lượng** (chưa có tập câu hỏi, baseline, CI).

## 6. Lệnh kiểm tra

```powershell
.\.venv\Scripts\python.exe -m pytest tests/rag tests/common tests/api -q -p no:cacheprovider
# Test Postgres trên database tạm: đặt TEST_DATABASE_URL (role có CREATEDB) rồi
.\.venv\Scripts\python.exe -m pytest -m db tests/rag tests/api -q -p no:cacheprovider
.\.venv\Scripts\python.exe -X utf8 -m eventrank.common.db migrate
```

## 7. Cạm bẫy

- **Không chạy `uv sync` / `uv run` thiếu `--no-sync`** trên máy GPU: `uv.lock` ghim PyTorch CPU, sẽ thay bản
  CUDA (gặp 22/11, phải cài lại `torch==2.6.0+cu124`).
- Qdrant native: `infra/start-qdrant.ps1` (hoặc chạy `data/tools/qdrant-v1.20.0/qdrant.exe --config-path config.yaml`
  với thư mục làm việc `data/rag/qdrant`). Thư mục `storage/` và file `.qdrant-initialized` ở gốc repo là do Qdrant
  từng bị chạy nhầm thư mục — không phải dữ liệu thật.
- Gemma phục vụ 1 chuỗi một lúc (`--max-num-seqs 1`); mỗi lượt tool calling gọi Gemma 2–4 lần.
- Đổi `models.*` trong YAML chỉ có hiệu lực sau `python -m eventrank.rag.modal_setup deploy`.
