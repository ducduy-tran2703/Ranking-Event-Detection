-- 009_rag_chat_cancel.sql — người dùng dừng một lượt hỏi đang chờ/đang chạy: thêm trạng thái 'cancelled'.
-- Lượt bị dừng giải phóng hàng đợi ngay; nếu pipeline vẫn đang gọi mô hình, kết quả về sau bị bỏ (worker chỉ ghi
-- kết quả khi lượt còn 'running'). ĐÃ ÁP thì KHÔNG SỬA file này.

ALTER TABLE rag_messages DROP CONSTRAINT rag_messages_status_check;
ALTER TABLE rag_messages ADD CONSTRAINT rag_messages_status_check
    CHECK (status IN ('queued', 'running', 'answered', 'insufficient_evidence', 'unsupported_query',
                      'invalid_generation', 'failed', 'cancelled'));
