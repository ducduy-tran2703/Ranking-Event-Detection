-- 002_events.sql — tầng Sự kiện trong Postgres: vector bài, sự kiện, thành viên, lịch sử tên, điểm xu hướng,
-- lần chạy worker; kèm 2 bảng phụ của tầng Thu thập (ánh xạ chuyên mục, ảnh chụp "Xem nhiều").
-- Chỉ tính năng Postgres ≥ 14, không extension: vector lưu bytea float32 (gom cụm vẫn tính bằng numpy).
-- ĐÃ ÁP thì KHÔNG SỬA file này — đổi schema bằng file 003_….sql mới (xem src/eventrank/common/db.py).
--
-- Nạp kết quả một lần chạy pipeline (data/runs/<run_id>/): `python -m eventrank.serving.db_import`.
-- Worker gom cụm liên tục (gán nhanh + gom lại 48h, giữ event_id) sẽ ghi vào CÙNG các bảng này.

-- ---------------------------------------------------------------------- bảng phụ tầng Thu thập
-- Chuyên mục nguyên văn của từng báo → tên chuyên mục chung (cùng luật `norm_category` của serving/store.py).
CREATE TABLE category_map (
    source        text NOT NULL REFERENCES sources (source),
    category_raw  text NOT NULL,                      -- như articles.category
    category_std  text NOT NULL,                      -- "Thế giới", "Sức khỏe", …
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, category_raw)
);

-- Ảnh chụp hộp "Xem nhiều" của từng báo mỗi giờ: mốc đối chiếu duy nhất để đánh giá điểm xu hướng.
CREATE TABLE most_read_snapshots (
    snapshot_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source       text NOT NULL REFERENCES sources (source),
    captured_at  timestamptz NOT NULL,
    rank         smallint NOT NULL CHECK (rank >= 1),
    url          text NOT NULL,
    article_id   char(64) REFERENCES articles (article_id),   -- NULL khi bài chưa có trong DB
    title        text,
    UNIQUE (source, captured_at, rank)
);
CREATE INDEX most_read_snapshots_article_idx ON most_read_snapshots (article_id);

-- ---------------------------------------------------------------------- lần chạy worker
-- Mỗi vòng xử lý (hoặc một lần nạp run offline: step = import). Để tái lập và để trang theo dõi hệ thống.
CREATE TABLE worker_runs (
    run_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    step         text NOT NULL
                 CHECK (step IN ('import', 'embed', 'assign', 'recluster', 'name', 'trend', 'notify')),
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    status       text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'failed')),
    app_now      timestamptz,                       -- giờ hệ thống lúc chạy (app_now(): thật hoặc phát lại)
    versions     jsonb NOT NULL DEFAULT '{}',       -- model/algo/naming/trend version, commit git, run_id nguồn
    stats        jsonb NOT NULL DEFAULT '{}',       -- số bài, số sự kiện, thời gian từng phần
    error        text
);
CREATE INDEX worker_runs_step_started_idx ON worker_runs (step, started_at DESC);

-- ---------------------------------------------------------------------- vector
-- Vector của bài theo từng mô hình. content_hash khác articles.content_hash → bài đã sửa, phải tính lại
-- (worker tìm bằng anti-join theo (article_id, content_hash), không theo mốc updated_at).
CREATE TABLE article_embeddings (
    article_id     char(64) NOT NULL REFERENCES articles (article_id),
    model_version  text NOT NULL,                     -- bkai_ft_v1_s44, …
    content_hash   char(64) NOT NULL,
    dim            smallint NOT NULL CHECK (dim > 0),
    vec            bytea NOT NULL,                    -- float32 little-endian, đã chuẩn hoá L2
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (article_id, model_version),
    CHECK (octet_length(vec) = dim * 4)
);

-- ---------------------------------------------------------------------- sự kiện
-- Đơn vị phân tích chính. event_id ổn định giữa các vòng gom cụm (bookmark, thông báo trỏ vào nó);
-- giữ dạng web đang dùng: E<ngày bài đầu>-<8 ký tự đầu article_id bài đầu>.
-- Đánh dấu, KHÔNG xoá: gộp → status = merged + merged_into; editor ẩn → status = hidden.
CREATE TABLE events (
    event_id           text PRIMARY KEY CHECK (event_id ~ '^E\d{8}-[0-9a-f]{8}$'),
    status             text NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open', 'closed', 'merged', 'hidden')),   -- closed: quá 48h không có bài mới
    merged_into        text REFERENCES events (event_id),
    first_seen         timestamptz NOT NULL,
    last_seen          timestamptz NOT NULL,
    size               integer NOT NULL CHECK (size >= 1),
    n_sources          integer NOT NULL CHECK (n_sources >= 1),
    sources            jsonb NOT NULL DEFAULT '{}',   -- {"vnexpress": 3, "tuoitre": 2}
    medoid_article_id  char(64) REFERENCES articles (article_id),
    medoid_title       text,
    -- Tên ĐANG HIỂN THỊ, đã áp luật ẩn tên của cửa sổ tập test đặt tên (serving/store.py): sự kiện bị ẩn
    -- → display_name = tiêu đề bài medoid, name_hidden = true, tên mô hình KHÔNG có ở bất kỳ bảng nào.
    display_name       text NOT NULL CHECK (display_name <> ''),
    name_source        text NOT NULL CHECK (name_source IN ('model', 'medoid', 'title', 'editor')),
    name_hidden        boolean NOT NULL DEFAULT false,
    category_std       text,                          -- chuyên mục gặp nhiều nhất trong các bài
    is_stable          boolean NOT NULL DEFAULT false, -- qua ≥ 1 vòng đối chiếu ID và đủ số báo (worker đặt)
    notified_at        timestamptz,                   -- đã qua cổng thông báo; NULL = chưa
    hidden_reason      text,                          -- editor ẩn sự kiện: lý do
    -- Tóm tắt điểm xu hướng (của trend_version ghi ở cột dưới), để sắp "nổi bật" không phải cộng lại:
    peak_score         real,                          -- điểm cao nhất
    peak_at            timestamptz,
    total_score        real,                          -- Σ_t score · step_hours
    top10_hours        real,                          -- số giờ nằm trong top 10
    algo_version       text NOT NULL,
    model_version      text NOT NULL,
    trend_version      text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CHECK (last_seen >= first_seen),
    CHECK (n_sources <= size),
    CHECK ((status = 'merged') = (merged_into IS NOT NULL)),
    CHECK (merged_into IS DISTINCT FROM event_id)
);
CREATE INDEX events_status_last_seen_idx ON events (status, last_seen DESC);
CREATE INDEX events_first_seen_idx ON events (first_seen);
CREATE INDEX events_total_score_idx ON events (total_score DESC NULLS LAST);
CREATE INDEX events_not_notified_idx ON events (event_id) WHERE notified_at IS NULL;
-- Mọi cột khoá ngoại trỏ vào events đều có chỉ mục: không có thì xoá/gộp một sự kiện phải quét cả bảng con
-- (đo 04/11/2026: nạp lại 20 nghìn sự kiện > 2 phút chưa xong, so với 15 s khi nạp lần đầu).
CREATE INDEX events_merged_into_idx ON events (merged_into) WHERE merged_into IS NOT NULL;

-- Mỗi bài thuộc đúng MỘT sự kiện tại một thời điểm (PK = article_id).
CREATE TABLE event_articles (
    article_id   char(64) PRIMARY KEY REFERENCES articles (article_id),
    event_id     text NOT NULL REFERENCES events (event_id),
    assigned_at  timestamptz NOT NULL DEFAULT now(),
    method       text NOT NULL CHECK (method IN ('fast', 'recluster', 'import')),
    similarity   real,                                -- cosine trung bình với cụm lúc gán
    is_medoid    boolean NOT NULL DEFAULT false
);
CREATE INDEX event_articles_event_idx ON event_articles (event_id);
CREATE UNIQUE INDEX event_articles_one_medoid_idx ON event_articles (event_id) WHERE is_medoid;

-- Mọi lần một bài đổi sự kiện (from_event NULL = lần gán đầu). Đo "số lần đổi ID" (tong-hop 10.1) và giải
-- thích khi sự kiện bị gộp/tách.
CREATE TABLE event_assignment_log (
    log_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    article_id     char(64) NOT NULL REFERENCES articles (article_id),
    from_event     text REFERENCES events (event_id),
    to_event       text NOT NULL REFERENCES events (event_id),
    reason         text NOT NULL CHECK (reason IN ('import', 'fast', 'recluster', 'merge', 'split', 'editor')),
    worker_run_id  bigint REFERENCES worker_runs (run_id),
    at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX event_assignment_log_article_idx ON event_assignment_log (article_id, at);
CREATE INDEX event_assignment_log_run_idx ON event_assignment_log (worker_run_id);
CREATE INDEX event_assignment_log_to_idx ON event_assignment_log (to_event);
CREATE INDEX event_assignment_log_from_idx ON event_assignment_log (from_event) WHERE from_event IS NOT NULL;

-- Lịch sử tên. Đặt lại tên khi sự kiện lớn lên đáng kể; editor sửa tay. Sự kiện bị ẩn tên (cửa sổ tập
-- test đặt tên 14–15/09/2026 + tên gần trùng): CHỈ ghi dòng medoid, không ghi tên mô hình.
CREATE TABLE event_names (
    name_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id        text NOT NULL REFERENCES events (event_id),
    name            text NOT NULL CHECK (name <> ''),
    source          text NOT NULL CHECK (source IN ('model', 'medoid', 'title', 'editor')),
    naming_version  text,                             -- vit5_v1_s42, …
    input_hash      text,                             -- khoá đệm như data/naming/cache
    size_at_naming  integer,                          -- số bài lúc đặt tên
    checks          jsonb NOT NULL DEFAULT '{}',      -- hậu kiểm: lý do rơi về medoid, tên mô hình bị loại, ẩn tên
    is_current      boolean NOT NULL DEFAULT true,
    created_by      bigint,                           -- user sửa tay; FK tới users thêm ở migration tài khoản
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX event_names_current_idx ON event_names (event_id) WHERE is_current;
CREATE INDEX event_names_event_idx ON event_names (event_id, created_at DESC);

-- ---------------------------------------------------------------------- xu hướng
-- Điểm của MỌI sự kiện ứng viên tại mỗi mốc (không chỉ top-K): trang chi tiết vẽ đường điểm không phải
-- tính lại. Đặc trưng chỉ dùng bài có published_at ≤ t (trending/score.py).
CREATE TABLE trend_scores (
    trend_version   text NOT NULL,                    -- t2, …
    t               timestamptz NOT NULL,             -- mốc giờ
    event_id        text NOT NULL REFERENCES events (event_id),
    score           real NOT NULL,
    rank            integer NOT NULL CHECK (rank >= 1),   -- thứ hạng tại t trong mọi ứng viên
    n_articles      integer NOT NULL,                 -- số bài của sự kiện đến t
    n_articles_3h   integer NOT NULL,                 -- số bài trong cửa sổ (t − W, t]
    n_sources       smallint NOT NULL,                -- số báo đến t
    n_sources_eff   real NOT NULL,                    -- số nguồn hiệu dụng (báo "chép" tiêu đề = 0,5)
    velocity        real NOT NULL,                    -- vận tốc đã chuẩn hoá theo mức nền
    PRIMARY KEY (trend_version, t, event_id)
);
CREATE INDEX trend_scores_rank_idx ON trend_scores (trend_version, t, rank);
CREATE INDEX trend_scores_event_idx ON trend_scores (event_id, t);

-- Mức nền số bài theo giờ trong ngày (giờ Việt Nam), trung bình = 1; dùng chuẩn hoá điểm xu hướng.
CREATE TABLE trend_baselines (
    trend_version  text NOT NULL,
    hour_of_day    smallint NOT NULL CHECK (hour_of_day BETWEEN 0 AND 23),
    value          real NOT NULL CHECK (value > 0),
    computed_from  date,
    computed_to    date,                              -- khoảng [from, to) đã dùng để tính
    PRIMARY KEY (trend_version, hour_of_day)
);
