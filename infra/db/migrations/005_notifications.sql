-- 005_notifications.sql — hộp thư thông báo trên web + hàng đợi email.
-- ĐÃ ÁP thì KHÔNG SỬA file này. Chưa làm: push_devices, notification_deliveries (cổng thông báo + mobile).

-- Hộp thư (chuông) của từng người.
CREATE TABLE notifications (
    notification_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id          bigint NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    kind             text NOT NULL CHECK (kind IN ('event_new', 'event_update', 'topic_match', 'system')),
    event_id         text REFERENCES events (event_id),
    body             text NOT NULL,                    -- tên sự kiện trong đây là tên ĐÃ HIỂN THỊ (đã áp ẩn tên)
    created_at       timestamptz NOT NULL DEFAULT now(),
    read_at          timestamptz
);
CREATE INDEX notifications_user_idx ON notifications (user_id, created_at DESC);
CREATE INDEX notifications_unread_idx ON notifications (user_id) WHERE read_at IS NULL;
-- Cột trỏ vào events phải có chỉ mục (xoá/gộp sự kiện kiểm FK qua đây — xem 002_events.sql).
CREATE INDEX notifications_event_idx ON notifications (event_id) WHERE event_id IS NOT NULL;

-- Hàng đợi email: ghi cùng giao dịch với nghiệp vụ, tiến trình riêng gửi đi. Link chứa token chỉ nằm trong `payload`
-- tới khi gửi; gửi xong phải xoá token khỏi payload. Bản demo CHƯA gửi thư: thư nằm ở đây, quản trị viên xem được
-- (trang Quản trị › Thư hệ thống) và link được ghi vào log máy chủ.
CREATE TABLE email_outbox (
    email_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    to_email    text NOT NULL,
    template    text NOT NULL CHECK (template IN ('verify_email', 'reset_password', 'digest')),
    payload     jsonb NOT NULL DEFAULT '{}',
    status      text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'failed')),
    attempts    smallint NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    sent_at     timestamptz,
    error       text
);
CREATE INDEX email_outbox_status_idx ON email_outbox (status, created_at);
