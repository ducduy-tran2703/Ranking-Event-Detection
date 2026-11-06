-- 006_admin.sql — nhật ký quản trị + khoá API cho máy khác (crawler gửi bài qua API thay vì nối thẳng DB).
-- ĐÃ ÁP thì KHÔNG SỬA file này.

-- Hành động quan trọng: đăng nhập, đổi/đặt lại mật khẩu, đổi quyền, mở khoá, tạo/thu hồi khoá API, xử lý báo sai.
-- `details` không bao giờ chứa mật khẩu hay token. IP bỏ sau 90 ngày, dòng giữ 1 năm (cleanup).
CREATE TABLE audit_logs (
    audit_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_user_id  bigint REFERENCES users (user_id) ON DELETE SET NULL,
    actor_kind     text NOT NULL DEFAULT 'user' CHECK (actor_kind IN ('user', 'system', 'api_token')),
    action         text NOT NULL,                     -- user.login, user.password_reset, user.role_change, …
    target_type    text,
    target_id      text,
    details        jsonb NOT NULL DEFAULT '{}',
    ip             inet,
    at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_logs_actor_idx ON audit_logs (actor_user_id, at);
CREATE INDEX audit_logs_target_idx ON audit_logs (target_type, target_id);
CREATE INDEX audit_logs_at_idx ON audit_logs (at);

-- Khoá API: token đầy đủ chỉ hiện MỘT lần lúc tạo; DB giữ sha256 + 10 ký tự đầu để nhận diện.
CREATE TABLE api_tokens (
    token_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    prefix        text NOT NULL,
    token_hash    char(64) NOT NULL UNIQUE,
    scopes        text[] NOT NULL CHECK (scopes <@ ARRAY['ingest:write', 'read']::text[] AND cardinality(scopes) > 0),
    source        text REFERENCES sources (source),   -- chỉ được ghi bài của một báo
    created_by    bigint REFERENCES users (user_id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_used_at  timestamptz,
    expires_at    timestamptz,
    revoked_at    timestamptz
);
