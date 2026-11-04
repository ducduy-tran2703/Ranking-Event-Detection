-- 001_ingest.sql — tầng Thu thập trong Postgres: nguồn, bài báo (hợp đồng Silver), lần cào, đồng hồ.
-- Chỉ tính năng Postgres ≥ 14, không extension (không pgvector). Bảng sự kiện: migration sau (giai đoạn 2).
-- ĐÃ ÁP thì KHÔNG SỬA file này — đổi schema bằng file 002_….sql mới (xem src/eventrank/common/db.py).

-- Nguồn tin. Nạp từ configs/sources.yaml bằng `python -m eventrank.ingest sources sync`.
CREATE TABLE sources (
    source        text PRIMARY KEY CHECK (source ~ '^[a-z0-9_]+$'),   -- viết thường, không dấu
    display_name  text NOT NULL,
    homepage      text,
    enabled       boolean NOT NULL DEFAULT false,   -- false: `ingest run` từ chối chạy crawler
    crawler       text,                             -- "module:Lớp", NULL = chưa có crawler
    notes         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Bài báo: đúng hợp đồng Silver (docs/tong-hop.md mục 5.3) + cột vận hành.
-- Idempotent theo article_id (INSERT … ON CONFLICT), chỉ UPDATE khi content_hash đổi.
-- Đánh dấu, KHÔNG xoá: bài ngắn/thiếu sapo → quality_flags; gần trùng giữa các báo → dup_group_id.
CREATE TABLE articles (
    article_id     char(64) PRIMARY KEY CHECK (article_id ~ '^[0-9a-f]{64}$'),  -- sha256(url)
    url            text NOT NULL UNIQUE CHECK (url LIKE 'https://%'),
    source         text NOT NULL REFERENCES sources (source),
    category       text NOT NULL,                     -- chuyên mục nguyên văn trên trang báo
    title          text NOT NULL CHECK (title <> ''),
    sapo           text NOT NULL,                     -- '' được phép, kèm cờ missing_sapo
    author         text CHECK (author <> ''),         -- không có thì NULL, không ghi chuỗi rỗng
    published_at   timestamptz NOT NULL,              -- giờ đăng gốc, luôn có múi giờ
    content_text   text NOT NULL,                     -- '' được phép, kèm cờ no_body
    crawled_at     timestamptz NOT NULL DEFAULT now(),  -- lần ĐẦU vào DB, không đổi khi cập nhật
    updated_at     timestamptz NOT NULL DEFAULT now(),  -- lần cuối nội dung đổi
    ingested_via   text NOT NULL,                     -- import_jsonl | replay | crawler:<tên> (lần ghi cuối)
    parser_version text,
    content_hash   char(64) NOT NULL,                 -- sha256 các trường nội dung đã chuẩn hoá
    quality_flags  text[] NOT NULL DEFAULT '{}',
    dup_group_id   text                               -- giai đoạn sau (MinHash): đánh dấu, không xoá
);
CREATE INDEX articles_published_at_idx ON articles (published_at);
CREATE INDEX articles_source_published_idx ON articles (source, published_at);
-- Worker giai đoạn 2 lấy "bài mới/đổi từ lần trước" theo updated_at.
CREATE INDEX articles_updated_at_idx ON articles (updated_at);

-- Mỗi lần một crawler (hoặc một lần import JSONL) chạy cho một nguồn: giám sát "crawler chết âm
-- thầm" (bẫy 10, mục 6.5) — RSS không lấy lại được quá khứ, nên phải thấy ngay khi một báo ngừng.
CREATE TABLE crawl_runs (
    run_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source         text NOT NULL REFERENCES sources (source),
    crawler        text NOT NULL,                     -- tên crawler hoặc import_jsonl
    parser_version text,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    -- running: đang chạy (để lâu không xong = tiến trình đã chết); blocked: báo chặn (403 liên tiếp,
    -- robots.txt) → dừng, báo người dùng, KHÔNG vượt chặn.
    status         text NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running', 'ok', 'failed', 'blocked')),
    n_seen         integer NOT NULL DEFAULT 0,
    n_new          integer NOT NULL DEFAULT 0,
    n_updated      integer NOT NULL DEFAULT 0,
    n_unchanged    integer NOT NULL DEFAULT 0,
    n_rejected     integer NOT NULL DEFAULT 0,
    reject_reasons jsonb NOT NULL DEFAULT '{}',       -- {"published_at_naive": 3, …}
    error          text
);
CREATE INDEX crawl_runs_source_started_idx ON crawl_runs (source, started_at DESC);

-- "Bây giờ" của cả hệ thống — đúng MỘT dòng. real: giờ thật; replay: giờ giả lập do
-- `ingest replay` đẩy tới (phát lại Silver thay crawler). Worker/API giai đoạn 2 đọc app_now().
CREATE TABLE app_clock (
    id         boolean PRIMARY KEY DEFAULT true CHECK (id),
    mode       text NOT NULL DEFAULT 'real' CHECK (mode IN ('real', 'replay')),
    sim_now    timestamptz,
    speed      double precision NOT NULL DEFAULT 1 CHECK (speed > 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (mode = 'real' OR sim_now IS NOT NULL)
);
INSERT INTO app_clock DEFAULT VALUES;

CREATE FUNCTION app_now() RETURNS timestamptz LANGUAGE sql STABLE AS $$
    SELECT CASE WHEN mode = 'replay' THEN sim_now ELSE now() END FROM app_clock
$$;
