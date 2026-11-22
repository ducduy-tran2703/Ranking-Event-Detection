# Lỗi còn gặp: chatbot RAG tool calling

Đọc kèm [rag-tool-calling.md](rag-tool-calling.md). Cập nhật 22/11/2026, nhánh `feat/rag-tool-calling`.
Mọi lỗi dưới đây **tái hiện ổn định**: E2E lần 4 và 5 (Gemma `temperature=0`) cho kết quả giống hệt nhau.
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

## Lỗi 1 (NẶNG): mang nhầm bộ lọc ngày của câu trước

- **Triệu chứng:** lượt 5 hỏi tỷ số U23 ngay sau lượt 4 hỏi "ngày 10/9/2026". Gemma gọi
  `search_news(query="U23 Việt Nam thắng U23 Philippines tỷ số", date_from="2026-09-10", date_to="2026-09-10")`
  → 0 kết quả (trận đá 18/9) → `insufficient_evidence`. Lượt 6 ("còn trận tiếp theo") không gọi tool → cũng
  `insufficient_evidence`. Người dùng nhận "không biết" dù kho có tin.
- **Đã thử, KHÔNG hiệu quả:** luật trong prompt "chỉ đặt date_from/date_to khi CÂU HIỆN TẠI nêu ngày";
  ghi chú trong kết quả tool "bộ lọc ngày có thể sai, hãy gọi lại không có date_from/date_to" — Gemma dừng luôn,
  không gọi lại.
- Lần 1–2 không gặp vì lịch sử khác (câu trả lời lượt 4 khác) → lỗi phụ thuộc ngữ cảnh hội thoại.
- **Hướng sửa (bằng code, không dựa vào prompt):** trong `tools.search_news`, nếu ngày do **model** tự đặt
  (không phải bộ lọc giao diện) và kết quả rỗng → code tự tìm lại không lọc ngày, ghi vào trace. Có thể thêm chốt:
  câu hiện tại không có số/từ chỉ thời gian ("ngày", "tháng", "hôm", "tuần", "năm") thì bỏ ngày model đặt.
  Cân nhắc thêm: lượt không gọi tool nào mà câu hỏi không phải chào hỏi → tự chạy `search_news(câu hỏi)`.

## Lỗi 2 (NHẸ): câu trả lời "tin nổi bật" chỉ có lời chào + dãy trích dẫn

- **Triệu chứng:** lượt 4 trả `"Chị Lan ơi, vào ngày 10/9/2026, có các sự kiện nổi bật sau: [1][2][3][4][5]"`.
  Tên sự kiện chỉ nằm trong danh sách nguồn (đã sửa để nguồn mang tiêu đề bài thật), không nằm trong câu trả lời.
- **Nguyên nhân:** luật xưng hô bắt buộc ở lượt cuối (thêm để sửa lỗi "không gọi chị Lan") khiến Gemma gom cả
  câu trả lời vào một claim chào hỏi. Đã viết lại luật ("lời gọi chỉ là mở đầu, mỗi sự kiện là một claim riêng")
  — **không hiệu quả**.
- Validator không bắt được vì mọi quote đều đúng nguyên văn; claim chỉ thiếu nội dung.
- **Hướng sửa:** trong `generation.validate_answer`/`agent`, nếu text của claim gần như không chứa từ nào của các
  quote nó dẫn (chỉ lời chào) → tự liệt kê các quote đã kiểm dưới claim đó, mỗi quote kèm `[n]`. Nội dung vẫn có
  căn cứ, chỉ do code trình bày. Hoặc: với `top_events`, ghép danh sách sự kiện bằng code từ bằng chứng.

## Lỗi/việc còn dở khác

| # | Mức | Mô tả | Hướng xử lý |
|---|---|---|---|
| 3 | Trung bình | `GET /api/rag/status` vẫn trả `single_turn: true` kể cả khi bật tool calling (đã nhớ 3 lượt trước) | Lấy từ `tool_calling.enabled` |
| 4 | Trung bình | Web chưa có trang **Hồ sơ** (xem/sửa/xác nhận nghề đang chờ); hiện chỉ có dòng nhắc trong câu trả lời | Thêm trang gọi `/api/rag/profile*` qua `apps/web/src/api/` |
| 5 | Trung bình | Chưa có tập đánh giá: chọn tool đúng, chất lượng trả lời, tác dụng NER boost (0,008/0,003 chưa đo), cá nhân hoá | Dựng bộ câu hỏi theo `docs/plan-rag.md` bước 9; báo kèm baseline + CI |
| 6 | Thấp | `RAGChatMessage` không trả `profile_update` (chỉ có trong `trace`) → web không biết lượt nào đổi hồ sơ | Thêm trường vào schema nếu web cần |
| 7 | Thấp | Vòng tool không giữ Qwen sống khi chờ Gemma (pipeline cũ có `keep_alive`) → `search_news` ở vòng 2–3 có thể chờ Qwen cold start | Bọc vòng tool bằng `keep_alive` sau lần `search_news` đầu |
| 8 | Thấp | `smalltalk` chỉ được kiểm bằng luật "không chữ số, không URL, chưa tra cứu"; câu chào có thể vẫn nêu sự thật bằng chữ | Theo dõi; nếu gặp thì siết (ví dụ giới hạn độ dài/từ khoá) |
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
