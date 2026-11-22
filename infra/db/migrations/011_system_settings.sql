-- 011_system_settings.sql — cài đặt hệ thống chỉnh trên web khi đang chạy (không sửa YAML, không khởi động lại)
-- + bước 'rag_sync' trong worker_runs (bộ lập lịch đồng bộ RAG trong tiến trình API ghi mỗi lượt một dòng)
-- + cột article_ner.source_updated_at (bài nào cần đồng bộ RAG lại; xem cuối file).
-- Mỗi khối cài đặt một dòng: key = tên khối ('rag_sync', 'event_worker'), value = JSON đã kiểm bằng Pydantic ở module
-- sở hữu (eventrank.rag.auto_sync, eventrank.serving.worker_settings). Thiếu dòng → code dùng mặc định.
-- Lịch cào báo KHÔNG nằm ở đây: dịch vụ crawler tự giữ trong data/state/schedule.json (API chỉ chuyển tiếp).
-- ĐÃ ÁP thì KHÔNG SỬA file này; thay đổi schema bằng migration mới.

CREATE TABLE IF NOT EXISTS system_settings (
    key         text PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]{0,63}$'),
    value       jsonb NOT NULL CHECK (jsonb_typeof(value) = 'object'),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  bigint NULL REFERENCES users (user_id) ON DELETE SET NULL
);
COMMENT ON TABLE system_settings IS
    'Cài đặt chạy-khi-đang-chạy theo khối (rag_sync, event_worker). Đọc lại mỗi vòng nên đổi có hiệu lực ngay.';
COMMENT ON COLUMN system_settings.updated_by IS 'Quản trị viên đổi lần cuối; xoá tài khoản thì để NULL.';

-- CHECK đặt trong CREATE TABLE của 002 nên Postgres tự đặt tên worker_runs_step_check.
ALTER TABLE worker_runs DROP CONSTRAINT IF EXISTS worker_runs_step_check;
ALTER TABLE worker_runs ADD CONSTRAINT worker_runs_step_check
    CHECK (step IN ('import', 'embed', 'assign', 'recluster', 'name', 'trend', 'notify', 'rag_sync'));

-- Đồng bộ RAG biết NER của bài đang ứng với BẢN NÀO của bài: `source_updated_at` = đúng giá trị `articles.updated_at`
-- đọc DƯỚI KHOÁ ghi lúc kiểm hash văn bản (sync) / lúc khoá dòng FOR UPDATE (prepare). Bài chờ = giá trị hiện tại KHÁC
-- giá trị đã ghi (so bằng, không so lớn hơn: crawler ghi cả lô trong một transaction nên `articles.updated_at` là giờ
-- bắt đầu lô, có thể SỚM hơn `article_ner.updated_at` của lượt sync commit xen giữa → so `>` bỏ sót bài vĩnh viễn).
-- Sink chỉ đổi `updated_at` khi `content_hash` đổi, nên hai cột này đổi cùng nhau.
ALTER TABLE article_ner ADD COLUMN IF NOT EXISTS source_updated_at timestamptz;
COMMENT ON COLUMN article_ner.source_updated_at IS
    'articles.updated_at của bản bài đã dùng để chạy NER/chunk; khác giá trị hiện tại → bài chờ đồng bộ RAG lại. '
    'NULL (dòng cũ chưa backfill) → dùng tiêu chí cũ articles.updated_at > article_ner.updated_at.';
-- Backfill. GIẢ ĐỊNH: dòng NER mà `article_ner.updated_at >= articles.updated_at` là NER của bản bài hiện tại (đúng tiêu
-- chí "đã xong" của code trước 011; sai lệch duy nhất là đúng khe tranh chấp nói trên, rất hiếm). Dòng còn lại để NULL nên
-- vẫn là bài chờ như trước. Không tính lại hash văn bản trong SQL: canonical text ghép bằng Python (strip + NFC).
UPDATE article_ner n SET source_updated_at = a.updated_at
FROM articles a
WHERE a.article_id = n.article_id AND n.source_updated_at IS NULL AND n.updated_at >= a.updated_at;
