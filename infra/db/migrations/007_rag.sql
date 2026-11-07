-- 007_rag.sql — NER, chunk và trạng thái index RAG; chỉ giữ phiên bản hiện hành.
-- Không lưu vector retrieval: Qdrant giữ vector, Tantivy giữ index BM25 trên disk.
-- ĐÃ ÁP thì KHÔNG SỬA file này; thay đổi schema bằng migration mới.

CREATE TABLE article_ner (
    article_id      char(64) PRIMARY KEY REFERENCES articles (article_id),
    canonical_text  text NOT NULL CHECK (length(canonical_text) > 0),
    text_hash       char(64) NOT NULL CHECK (text_hash ~ '^[0-9a-f]{64}$'),
    ner_version     text NOT NULL CHECK (length(btrim(ner_version)) > 0),
    entities        jsonb NOT NULL DEFAULT '[]'::jsonb
                    CHECK (jsonb_typeof(entities) = 'array'),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE article_ner IS
    'NER hiện hành của bài. Offset entity dùng [start_char,end_char) trên canonical_text chuẩn NFC.';
COMMENT ON COLUMN article_ner.text_hash IS
    'SHA256 UTF-8 của canonical_text, khác articles.content_hash (hợp đồng của tầng ingest).';
COMMENT ON COLUMN article_ner.entities IS
    'Mảng {text,label,start_char,end_char}; kiểm nhãn, offset và slice khi nhập dữ liệu.';

CREATE TABLE rag_chunks (
    chunk_id          uuid PRIMARY KEY,
    article_id        char(64) NOT NULL REFERENCES article_ner (article_id),
    chunk_index       integer NOT NULL CHECK (chunk_index >= 0),
    text              text NOT NULL CHECK (length(text) > 0),
    start_char        integer NOT NULL CHECK (start_char >= 0),
    end_char          integer NOT NULL CHECK (end_char > start_char),
    chunking_version  text NOT NULL CHECK (length(btrim(chunking_version)) > 0),
    UNIQUE (article_id, chunking_version, chunk_index),
    CHECK (char_length(text) = end_char - start_char)
);
COMMENT ON TABLE rag_chunks IS
    'Chunk nguyên văn; UUID tái tạo được và dùng làm point ID Qdrant. Không lưu entity hay event_id lặp.';
COMMENT ON COLUMN rag_chunks.text IS
    'Phải bằng canonical_text[start_char:end_char] (offset Python từ 0); importer kiểm slice trước khi ghi.';

CREATE TABLE rag_index_status (
    chunk_id        uuid PRIMARY KEY REFERENCES rag_chunks (chunk_id),
    index_version   text NOT NULL CHECK (length(btrim(index_version)) > 0),
    bm25_status     text NOT NULL DEFAULT 'pending'
                    CHECK (bm25_status IN ('pending', 'ready', 'failed')),
    qdrant_status   text NOT NULL DEFAULT 'pending'
                    CHECK (qdrant_status IN ('pending', 'ready', 'failed')),
    error           text,
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX rag_index_status_pending_idx ON rag_index_status (updated_at)
    WHERE bm25_status <> 'ready' OR qdrant_status <> 'ready';
COMMENT ON TABLE rag_index_status IS
    'Trạng thái index hiện hành. Tên collection, đường dẫn BM25 và model nằm trong cấu hình index_version.';
COMMENT ON COLUMN rag_index_status.error IS
    'Lỗi gần nhất, ghi rõ nhánh bm25/qdrant; không chứa khóa hoặc thông tin xác thực.';

-- Quy ước cho importer/worker (chưa triển khai ở migration):
-- * cập nhật updated_at tường minh mỗi lần UPDATE;
-- * NER/nội dung thay đổi: xử lý lại chunk + reset trạng thái trong cùng transaction,
--   đồng thời dọn point/index cũ qua worker (FK mặc định RESTRICT, không tự xoá dây chuyền);
-- * đổi index_version: reset CẢ HAI nhánh về pending; chỉ ready sau khi ghi bền thành công;
-- * event_id/URL/nguồn/ngày lấy qua article_id → articles/event_articles, không coi mapping là bất biến.
