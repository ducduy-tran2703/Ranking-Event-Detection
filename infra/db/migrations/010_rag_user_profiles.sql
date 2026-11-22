-- 010_rag_user_profiles.sql — hồ sơ cá nhân hoá chatbot RAG (tool calling) + trạng thái 'smalltalk'.
-- Hồ sơ chỉ đổi CÁCH trả lời (xưng hô, giọng, độ dài) và tin ưu tiên khi hỏi chung chung; không đổi sự thật/trích dẫn.
-- Không lưu tuổi, giới tính, địa chỉ hay dữ liệu nhạy cảm. Người dùng xem/sửa/xoá qua /api/rag/profile.
-- ĐÃ ÁP thì KHÔNG SỬA file này; thay đổi schema bằng migration mới.

CREATE TABLE rag_user_profiles (
    user_id            bigint PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
    persona            text CHECK (persona IN ('pho_thong', 'doanh_nhan', 'ke_toan', 'nha_dau_tu', 'sinh_vien',
                                               'giao_vien', 'can_bo_cong_chuc', 'nha_bao', 'lap_trinh_vien',
                                               'khac')),
    occupation_text    text CHECK (length(btrim(occupation_text)) BETWEEN 1 AND 60),
    address_user       text CHECK (length(btrim(address_user)) BETWEEN 1 AND 30),
    address_self       text CHECK (length(btrim(address_self)) BETWEEN 1 AND 30),
    tone               text CHECK (tone IN ('than_thien', 'trang_trong', 'ngan_gon')),
    answer_length      text CHECK (answer_length IN ('ngan', 'vua', 'chi_tiet')),
    interests          text[] NOT NULL DEFAULT '{}' CHECK (cardinality(interests) <= 10),
    -- Thay đổi nghề/nhóm người dùng do chatbot suy ra phải được người dùng xác nhận trước khi áp:
    -- {"persona": "...", "occupation_text": "...", "message_id": 123}; '{}' = không có gì chờ.
    pending            jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(pending) = 'object'),
    source_message_id  bigint REFERENCES rag_messages (message_id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE rag_user_profiles IS
    'Hồ sơ chatbot của một người: nhóm/nghề, xưng hô, giọng, độ dài, chuyên mục quan tâm. Xoá người dùng → xoá theo.';
COMMENT ON COLUMN rag_user_profiles.source_message_id IS
    'Lượt chat gần nhất làm thay đổi hồ sơ (truy vết vì sao chatbot ghi nhận).';

-- Câu chào/cảm ơn/xác nhận hồ sơ không cần bằng chứng tin tức: trả lời ngắn, không có nguồn.
ALTER TABLE rag_messages DROP CONSTRAINT rag_messages_status_check;
ALTER TABLE rag_messages ADD CONSTRAINT rag_messages_status_check
    CHECK (status IN ('queued', 'running', 'answered', 'insufficient_evidence', 'unsupported_query',
                      'invalid_generation', 'smalltalk', 'failed', 'cancelled'));
