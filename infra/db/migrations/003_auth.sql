-- 003_auth.sql — tài khoản: người dùng, phiên đăng nhập, token email dùng một lần, lần thử đăng nhập, cài đặt.
-- Theo bản thiết kế database 04/11/2026 (pbl/thiet-ke-database.html). Code: src/eventrank/accounts/.
-- ĐÃ ÁP thì KHÔNG SỬA file này — đổi schema bằng file số mới.
--
-- Không lưu bí mật dạng đọc được: mật khẩu băm Argon2id (dạng PHC); token phiên và token email chỉ lưu sha256.
-- Dữ liệu cá nhân (IP, User-Agent, lần thử đăng nhập) có hạn lưu — dọn bằng `python -m eventrank.accounts cleanup`.
-- Chưa làm (migration sau): oauth_identities (đăng nhập Google), event_views.

CREATE TABLE users (
    user_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email              text NOT NULL CHECK (email = lower(email) AND email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    email_verified_at  timestamptz,                    -- NULL = chưa xác minh
    password_hash      text,                           -- Argon2id PHC; NULL = chỉ đăng nhập ngoài (chưa có)
    display_name       text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 60),
    role               text NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'editor', 'admin')),
    status             text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    locked_until       timestamptz,                    -- khoá tạm sau nhiều lần đăng nhập sai
    terms_accepted_at  timestamptz NOT NULL,           -- đồng ý điều khoản + xử lý dữ liệu cá nhân
    last_login_at      timestamptz,
    deleted_at         timestamptz,                    -- xoá mềm; sau 30 ngày ẩn danh hoá (cleanup)
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
-- Một email chỉ thuộc một tài khoản CÒN SỐNG; xoá tài khoản xong đăng ký lại được.
CREATE UNIQUE INDEX users_email_live_idx ON users (email) WHERE deleted_at IS NULL;

-- Phiên đăng nhập (cookie HttpOnly). Đăng xuất = đặt revoked_at, không xoá dòng (trang "thiết bị" + kiểm toán).
CREATE TABLE user_sessions (
    session_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       bigint NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    token_hash    char(64) NOT NULL UNIQUE,            -- sha256 của token trong cookie
    csrf_token    text NOT NULL,                       -- gửi lại trong header X-CSRF-Token cho POST/PUT/DELETE
    remember      boolean NOT NULL DEFAULT false,      -- true: trượt 30 ngày; false: trượt 12 giờ
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),  -- cập nhật tối đa mỗi 5 phút
    expires_at    timestamptz NOT NULL,                -- trượt, tối đa 90 ngày từ created_at
    revoked_at    timestamptz,
    ip            inet,
    user_agent    text
);
CREATE INDEX user_sessions_user_idx ON user_sessions (user_id);
CREATE INDEX user_sessions_expires_idx ON user_sessions (expires_at);

-- Token dùng một lần gửi qua email. Tạo token mới cùng mục đích → vô hiệu token cũ chưa dùng.
CREATE TABLE auth_tokens (
    token_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     bigint NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    purpose     text NOT NULL CHECK (purpose IN ('verify_email', 'reset_password')),
    token_hash  char(64) NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,                  -- verify 24 giờ, reset 1 giờ
    used_at     timestamptz                            -- đã dùng (hoặc bị vô hiệu) thì không dùng lại được
);
CREATE INDEX auth_tokens_user_idx ON auth_tokens (user_id, purpose);

-- Mỗi lần thử đăng nhập: chặn dò mật khẩu (theo email và theo IP). Giữ 30 ngày.
CREATE TABLE login_attempts (
    attempt_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email_tried  text NOT NULL,                        -- chữ thường
    ip           inet,
    succeeded    boolean NOT NULL,
    reason       text NOT NULL CHECK (reason IN ('ok', 'bad_password', 'unknown_email', 'locked', 'disabled')),
    at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX login_attempts_email_idx ON login_attempts (email_tried, at);
CREATE INDEX login_attempts_ip_idx ON login_attempts (ip, at);

-- Cài đặt cá nhân, một dòng mỗi người (tạo cùng lúc với tài khoản).
CREATE TABLE user_settings (
    user_id         bigint PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
    push_enabled    boolean NOT NULL DEFAULT true,
    email_digest    text NOT NULL DEFAULT 'off' CHECK (email_digest IN ('off', 'daily', 'weekly')),
    quiet_start     time NOT NULL DEFAULT '22:00',     -- giờ yên lặng (giờ Việt Nam): không gửi push
    quiet_end       time NOT NULL DEFAULT '07:00',
    hidden_sources  text[] NOT NULL DEFAULT '{}',      -- báo không muốn thấy
    updated_at      timestamptz NOT NULL DEFAULT now()
);
