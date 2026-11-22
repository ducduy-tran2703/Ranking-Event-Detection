# Lỗi còn gặp: chatbot RAG tool calling

Đọc kèm [rag-tool-calling.md](rag-tool-calling.md). Cập nhật 22/11/2026, nhánh `feat/rag-tool-calling`. Lỗi 1, 2, 3, 7 **đã sửa** (mục dưới); còn lại ở bảng cuối.
Quy trình sửa: viết test tái hiện trước (TDD), rồi chạy lại E2E ít nhất 2 lần.

## Cách tái hiện chung (E2E)

Cần Postgres (migration 001–010), Qdrant, BM25, Modal đã deploy với tool calling. Kịch bản 7 lượt trong **một**
cuộc trò chuyện, tài khoản thử `e2e-rag-tool@example.invalid`, đi đúng đường worker chat
(`chat.ask` → `ChatWorker.run_once` → `ToolCallingPipeline`), bật `tool_calling.enabled` chỉ trong lần chạy:

1. Mình là kế toán, có thông tư thuế nào mới không?
2. Từ giờ gọi mình là chị Lan và xưng em nhé.
3. Có bao nhiêu bài của VnExpress đăng trong tháng 9/2026?
4. Tin nổi bật ngày 10/9/2026 là gì?
5. U23 Việt Nam thắng U23 Philippines với tỷ số bao nhiêu?
6. Còn trận tiếp theo của họ thì sao?
7. Xin chào, cảm ơn em nhé

Script lần trước nằm ở scratchpad của phiên (không theo Git); viết lại theo mô tả trên. Kết quả xem trong
`rag_messages.trace` (`tool_rounds`, `query_ner`, `validation`).

## Đã sửa ở lượt 2 (22/11/2026) — E2E 2 lần, 7/7 lượt đúng cả hai lần

Report (không theo Git): `data/rag/reports/e2e-tool-calling-20261122-fix-01.json`, `…-fix-02.json`.
Script: scratchpad của phiên, viết lại theo "Cách tái hiện chung" ở trên (tài khoản thử, hồ sơ xoá trước mỗi lần chạy).

| Lượt | Lần 1 | Lần 2 |
|---|---|---|
| 1 kế toán + thông tư thuế | answered, nghề vào `pending` | answered, nghề vào `pending` |
| 2 gọi chị Lan / xưng em | smalltalk, lưu xưng hô | smalltalk, lưu xưng hô |
| 3 số bài VnExpress tháng 9 | answered 2.086 [data] | answered 2.086 [data] |
| 4 tin nổi bật 10/9 | answered, 5 sự kiện liệt kê từng dòng | như lần 1 |
| 5 tỷ số U23 | answered 2-0, ngày 18-9 | như lần 1 |
| 6 trận tiếp theo | answered (nội dung mỏng: "mở toang cánh cửa đi tiếp") | answered: gặp U23 Uzbekistan 12h ngày 22-9 |
| 7 chào/cảm ơn | smalltalk | smalltalk |

- **Lỗi 1 — mang nhầm ngày (sửa bằng code, không dựa vào prompt)** — `tools.py`:
  - Ngày do model tự đặt chỉ dùng khi câu hiện tại có mốc thời gian (`has_time_reference`: ngày/tháng/năm/tuần/
    hôm/mới/gần đây…, dạng `10/9`, năm `20xx`; không dùng "có chữ số" vì `U23`). Áp cho `search_news`,
    `count_articles`, `top_events`. Bộ lọc giao diện không bị đụng tới.
  - `search_news` lọc theo ngày model đặt mà rỗng → code tự tìm lại toàn kho, báo model trong `note`.
  - Mọi chỉnh sửa ghi ở `trace.tool_rounds[].tool_calls[].adjustments`. E2E lần 1 lượt 1 thấy thật
    `dropped_model_dates` (trước khi thêm "mới" vào danh sách mốc; lần 2 giữ ngày đúng ý "thông tư mới").
  - Lượt Gemma **không gọi tool dữ liệu nào** rồi kết luận `insufficient_evidence` → code tự `search_news` với
    câu hỏi trước + câu hiện tại rồi sinh lại (`trace.fallback_search`). Chưa kích hoạt trong 2 lần E2E (Gemma đã tự
    tìm ở lượt 6), mới kiểm bằng test.
  - Lịch sử hội thoại không còn đưa câu "Chưa đủ bằng chứng…" của lượt trước vào prompt (thay bằng câu nhắc tra cứu
    lại) — nghi là nguyên nhân lượt 6 cũ không gọi tool.
- **Lỗi 2 — câu trả lời chỉ có lời chào** — `generation._is_hollow`: ý chung < 2 từ với mọi quote nó dẫn → code
  liệt kê các quote đã kiểm dưới ý đó (`- quote [n]`), không thêm chữ ngoài quote. Áp cho cả pipeline snapshot.
  Web hiển thị xuống dòng (`.chat-answer p { white-space: pre-line }`).
- **Lỗi 3** — `/api/rag/status` trả `single_turn = not tool_calling.enabled`.
- **Lỗi 7** — vòng tool giữ Qwen sống (`keep_alive`) từ lần `search_news` đầu tới hết lượt; `trace.keepalive`
  (E2E: 1–2 ping/lượt có tìm kiếm, 0 lỗi).
- Thêm: agent trả sớm `insufficient_evidence` khi bộ lọc ngày giao diện nằm ngoài kho (như pipeline snapshot).
- **Tool calling bật mặc định** (`tool_calling.enabled: true`).

Vẫn là smoke chức năng (một kịch bản, 2 lần chạy), **chưa phải đánh giá chất lượng** — xem việc #5.

## Lỗi/việc còn dở khác

| # | Mức | Mô tả | Hướng xử lý |
|---|---|---|---|
| 4 | Trung bình | Web chưa có trang **Hồ sơ** (xem/sửa/xác nhận nghề đang chờ); hiện chỉ có dòng nhắc trong câu trả lời | Thêm trang gọi `/api/rag/profile*` qua `apps/web/src/api/` |
| 5 | Trung bình | Chưa có tập đánh giá: chọn tool đúng, chất lượng trả lời, tác dụng NER boost (0,008/0,003 chưa đo), cá nhân hoá | Dựng bộ câu hỏi theo `docs/plan-rag.md` bước 9; báo kèm baseline + CI |
| 6 | Thấp | `RAGChatMessage` không trả `profile_update` (chỉ có trong `trace`) → web không biết lượt nào đổi hồ sơ | Thêm trường vào schema nếu web cần |
| 8 | Thấp | `smalltalk` chỉ được kiểm bằng luật "không chữ số, không URL, chưa tra cứu"; câu chào có thể vẫn nêu sự thật bằng chữ | Theo dõi; nếu gặp thì siết (ví dụ giới hạn độ dài/từ khoá) |
| 13 | Thấp | Câu trả lời đúng nguồn nhưng có thể mỏng (E2E lần 1 lượt 6); `_is_hollow` chỉ bắt ý chung < 2 từ với quote | Theo dõi trong tập đánh giá |
| 9 | Thấp | Mỗi vòng Gemma thường chỉ gọi 1 tool; câu cần nhiều tool tốn nhiều vòng (giới hạn 3) | Theo dõi trong tập đánh giá |
| 10 | Môi trường | `uv.lock` ghim PyTorch CPU; `uv sync` trên máy GPU thay mất bản CUDA | Cấu hình index CUDA trong `pyproject.toml`/`uv.lock` (quyết định của nhóm) |
| 11 | Dọn dẹp | DB máy dev còn tài khoản thử `e2e-rag-tool@example.invalid` (admin) + các cuộc trò chuyện E2E | Xoá khi không cần (người dùng quyết định) |
| 12 | Dọn dẹp | `storage/`, `.qdrant-initialized` ở gốc repo (Qdrant chạy nhầm thư mục) — untracked | Xoá sau khi chủ máy kiểm tra |

## Đã sửa trong phiên 22/11 (để không sửa lại)

- Lộ kênh suy nghĩ `<|channel>thought…<channel|>` trong content → lọc ở `ModelClient.chat` (không bật reasoning parser).
- Bỏ sót `update_user_profile` khi câu vừa giới thiệu vừa hỏi tin → luật prompt; đo 6/6 câu × 3 lần chạy.
- Sự kiện 92 bài bị loại do quote chép lệch câu dữ liệu dài → rút gọn câu dữ liệu `top_events`.
- Xưng hô không đều giữa các lượt → luật xưng hô bắt buộc ở lượt cuối (gây ra lỗi 2).
- Trace không ghi NER của `search_news` → `trace.query_ner` mỗi lần tìm.
- `profile.categories` ghi "Khoa học - Công nghệ" (gạch ngắn) ≠ DB "Khoa học – Công nghệ" (gạch dài) → đã sửa.
