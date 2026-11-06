-- 004_user_features.sql — tính năng người dùng: lưu sự kiện, theo dõi sự kiện, đăng ký chủ đề, báo sai.
-- ĐÃ ÁP thì KHÔNG SỬA file này. Chưa làm: event_views (lượt xem, cho cá nhân hoá).

-- Sự kiện người dùng lưu để đọc sau.
CREATE TABLE event_bookmarks (
    user_id     bigint NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    event_id    text NOT NULL REFERENCES events (event_id),
    note        text NOT NULL DEFAULT '' CHECK (length(note) <= 500),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, event_id)
);
CREATE INDEX event_bookmarks_event_idx ON event_bookmarks (event_id);

-- Theo dõi một sự kiện để được báo khi có diễn biến mới (worker giai đoạn 2 gửi).
CREATE TABLE event_follows (
    user_id             bigint NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    event_id            text NOT NULL REFERENCES events (event_id),
    notify              boolean NOT NULL DEFAULT true,
    last_notified_size  integer,                       -- chỉ báo lại khi số bài tăng đáng kể
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, event_id)
);
CREATE INDEX event_follows_event_idx ON event_follows (event_id);

-- Đăng ký chủ đề: có sự kiện mới khớp thì báo. Tối đa 50 mỗi người (kiểm ở code).
CREATE TABLE topic_subscriptions (
    subscription_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id          bigint NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    kind             text NOT NULL CHECK (kind IN ('keyword', 'category', 'source', 'entity')),
    value            text NOT NULL CHECK (length(value) BETWEEN 1 AND 100),   -- NFC, đã bỏ khoảng trắng thừa
    notify           boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX topic_subscriptions_unique_idx ON topic_subscriptions (user_id, kind, lower(value));
CREATE INDEX topic_subscriptions_match_idx ON topic_subscriptions (kind, lower(value));

-- Người dùng (hoặc khách) báo tên sai, bài lẫn sự kiện khác, hai sự kiện trùng. Vừa sửa lỗi hiển thị, vừa là nguồn
-- nhãn người cho đánh giá. Khách gửi được, giới hạn theo IP (IP giữ 90 ngày, cleanup xoá).
CREATE TABLE feedback_reports (
    report_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      bigint REFERENCES users (user_id) ON DELETE SET NULL,    -- NULL = khách
    event_id     text NOT NULL REFERENCES events (event_id),
    kind         text NOT NULL CHECK (kind IN ('wrong_name', 'stray_article', 'duplicate', 'other')),
    message      text NOT NULL DEFAULT '' CHECK (length(message) <= 1000),
    status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'rejected')),
    resolved_by  bigint REFERENCES users (user_id) ON DELETE SET NULL,
    resolved_at  timestamptz,
    ip           inet,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX feedback_reports_status_idx ON feedback_reports (status, created_at DESC);
CREATE INDEX feedback_reports_event_idx ON feedback_reports (event_id);
CREATE INDEX feedback_reports_ip_idx ON feedback_reports (ip, created_at);
