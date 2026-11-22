-- 008_rag_chat.sql — khung chat hỏi đáp RAG trên web: cuộc trò chuyện + từng lượt hỏi/đáp của người dùng.
-- Mỗi dòng rag_messages là MỘT lượt (câu hỏi + câu trả lời) và cũng là một job trong hàng đợi của API
-- (queued → running → kết quả). Pipeline RAG trả lời từng câu độc lập (single-turn), không dùng lịch sử.
-- ĐÃ ÁP thì KHÔNG SỬA file này; thay đổi schema bằng migration mới.

CREATE TABLE rag_conversations (
    conversation_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id          bigint NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    title            text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 200),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX rag_conversations_user_idx ON rag_conversations (user_id, updated_at DESC);
COMMENT ON TABLE rag_conversations IS
    'Cuộc trò chuyện hỏi đáp của một người; tiêu đề = câu hỏi đầu (cắt ngắn). Xoá người dùng → xoá theo.';

CREATE TABLE rag_messages (
    message_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id  bigint NOT NULL REFERENCES rag_conversations (conversation_id) ON DELETE CASCADE,
    user_id          bigint NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    question         text NOT NULL CHECK (length(btrim(question)) BETWEEN 1 AND 2048),
    filters          jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(filters) = 'object'),
    status           text NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued', 'running', 'answered', 'insufficient_evidence',
                                       'unsupported_query', 'invalid_generation', 'failed')),
    answer           text,
    sources          jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(sources) = 'array'),
    retrieval_mode   text CHECK (retrieval_mode IN ('hybrid', 'bm25_only', 'dense_only')),
    degraded         boolean,
    error            text,
    trace            jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    started_at       timestamptz,
    finished_at      timestamptz
);
CREATE INDEX rag_messages_conversation_idx ON rag_messages (conversation_id, message_id);
CREATE INDEX rag_messages_user_time_idx ON rag_messages (user_id, created_at);
CREATE INDEX rag_messages_queue_idx ON rag_messages (message_id) WHERE status IN ('queued', 'running');
COMMENT ON TABLE rag_messages IS
    'Một lượt hỏi/đáp = một job hàng đợi. sources: citation đã kiểm (quote nguyên văn, URL từ DB) + event_id nếu bài thuộc sự kiện.';
COMMENT ON COLUMN rag_messages.error IS
    'Câu thông báo an toàn cho người dùng khi status = failed; không chứa URL dịch vụ, khoá hay đường dẫn máy.';
COMMENT ON COLUMN rag_messages.trace IS
    'Trace pipeline (request_id, nhánh truy xuất, context, generator) để gỡ lỗi; API không trả cho người dùng.';
