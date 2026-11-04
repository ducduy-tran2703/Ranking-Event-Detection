"""Đăng ký, đăng nhập, phiên, token email, đổi/đặt lại mật khẩu (bảng 003 + email_outbox + audit_logs).

Luật (theo thiết kế database 04/11/2026, mục "Luồng chức năng" và "Bảo mật"):
- Không lộ email nào đã đăng ký: đăng ký email đã có, quên mật khẩu với email lạ, đăng nhập sai email hay sai mật khẩu
  đều trả cùng kiểu phản hồi; email lạ vẫn chạy Argon2 trên băm giả để thời gian như nhau.
- Sai mật khẩu 5 lần trong 15 phút → khoá tài khoản 15 phút (423); quá 30 lần sai/15 phút từ một IP → 429.
- Phiên: token 32 byte trong cookie HttpOnly, DB lưu sha256; "giữ đăng nhập" trượt 30 ngày, không thì 12 giờ; tối đa
  90 ngày. Đặt lại mật khẩu → thu hồi MỌI phiên; đổi mật khẩu → thu hồi mọi phiên KHÁC.
- Token email dùng một lần (xác minh 24 giờ, đặt lại 1 giờ); token mới cùng mục đích vô hiệu token cũ.
- Bản demo chưa gửi thư: thư nằm trong email_outbox (trang Quản trị › Thư hệ thống) và link được ghi vào log máy chủ.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from eventrank.accounts import security as S

# Logger con của uvicorn → link thư demo hiện ngay trên terminal của `make dev` (ngoài uvicorn: logger thường).
mail_log = logging.getLogger("uvicorn.error.eventrank.mail")

MAX_FAILED = 5
LOCK = timedelta(minutes=15)
WINDOW = timedelta(minutes=15)
IP_MAX_FAILED = 30
SESSION_REMEMBER = timedelta(days=30)
SESSION_SHORT = timedelta(hours=12)
SESSION_MAX = timedelta(days=90)
TOUCH_EVERY = timedelta(minutes=5)
TTL = {"verify_email": timedelta(hours=24), "reset_password": timedelta(hours=1)}
LINK_PATH = {"verify_email": "/verify-email", "reset_password": "/reset-password"}
FORGOT_MAX_PER_HOUR = 3

GENERIC_LOGIN = "Email hoặc mật khẩu không đúng. Sai 5 lần liên tiếp, tài khoản bị khoá 15 phút."
BAD_LINK = {"verify_email": "Link xác minh không hợp lệ hoặc đã hết hạn.",
            "reset_password": "Link đặt lại mật khẩu không hợp lệ hoặc đã hết hạn."}
USER_COLS = "u.user_id, u.email, u.display_name, u.role, u.email_verified_at IS NOT NULL, u.created_at"


class AccountError(Exception):
    """Lỗi nghiệp vụ có mã HTTP; `detail` (tiếng Việt) được trả thẳng cho người dùng nên không chứa bí mật."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass(frozen=True)
class NewSession:
    token: str                 # chỉ nằm trong cookie, không bao giờ ghi DB/log
    csrf_token: str
    max_age: int | None        # None = cookie phiên trình duyệt


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    email: str
    display_name: str
    role: str
    email_verified: bool
    created_at: datetime
    session_id: int
    csrf_token: str

    def public(self) -> dict[str, Any]:
        return user_public((self.user_id, self.email, self.display_name, self.role, self.email_verified,
                            self.created_at))


def user_public(row: tuple) -> dict[str, Any]:
    uid, email, name, role, verified, created = row[:6]
    return {"id": str(uid), "email": email, "display_name": name, "role": role, "email_verified": bool(verified),
            "created_at": created}


def audit(conn: psycopg.Connection, actor_user_id: int | None, action: str, target_type: str | None = None,
          target_id: str | None = None, details: dict | None = None, ip: str | None = None,
          actor_kind: str = "user") -> None:
    conn.execute("INSERT INTO audit_logs (actor_user_id, actor_kind, action, target_type, target_id, details, ip) "
                 "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                 (actor_user_id, actor_kind, action, target_type, target_id, Jsonb(details or {}), ip))


def _create_session(conn: psycopg.Connection, user_id: int, remember: bool, ip: str | None,
                    user_agent: str | None) -> NewSession:
    token, csrf = S.new_token(), S.new_token()
    ttl = SESSION_REMEMBER if remember else SESSION_SHORT
    conn.execute("INSERT INTO user_sessions (user_id, token_hash, csrf_token, remember, expires_at, ip, user_agent) "
                 "VALUES (%s, %s, %s, %s, now() + %s, %s, %s)",
                 (user_id, S.sha256_hex(token), csrf, remember, ttl, ip, (user_agent or "")[:300] or None))
    return NewSession(token, csrf, int(ttl.total_seconds()) if remember else None)


def _issue_email(conn: psycopg.Connection, user_id: int, email: str, purpose: str) -> None:
    """Token dùng một lần + thư trong email_outbox. Gọi trong transaction của nghiệp vụ."""
    conn.execute("UPDATE auth_tokens SET used_at = now() WHERE user_id = %s AND purpose = %s AND used_at IS NULL",
                 (user_id, purpose))
    token = S.new_token()
    token_hash = S.sha256_hex(token)
    expires = conn.execute("INSERT INTO auth_tokens (user_id, purpose, token_hash, expires_at) "
                           "VALUES (%s, %s, %s, now() + %s) RETURNING expires_at",
                           (user_id, purpose, token_hash, TTL[purpose])).fetchone()[0]
    link = f"{os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')}{LINK_PATH[purpose]}?token={token}"
    conn.execute("INSERT INTO email_outbox (to_email, template, payload) VALUES (%s, %s, %s)",
                 (email, purpose, Jsonb({"token": token, "token_hash": token_hash, "link": link,
                                         "expires_at": expires.isoformat()})))
    mail_log.info("thư %s cho %s (bản demo chưa gửi thư thật): %s", purpose, email, link)


# ---------------------------------------------------------------------- đăng ký / đăng nhập
def register(conn: psycopg.Connection, display_name: str, email: str, password: str, ip: str | None = None,
             user_agent: str | None = None) -> NewSession | None:
    """Tạo tài khoản + cài đặt + thư xác minh, đăng nhập luôn (dùng được trong lúc chờ xác minh). Email đã có tài
    khoản → None, không báo khác đi (người gọi trả cùng phản hồi)."""
    name = " ".join((display_name or "").split())
    email = S.normalize_email(email)
    if not (1 <= len(name) <= 60) or not S.valid_email(email):
        raise AccountError(400, "Hãy nhập tên hiển thị (tối đa 60 ký tự) và một email hợp lệ.")
    if problem := S.password_problem(password):
        raise AccountError(400, problem)
    pw_hash = S.hash_password(password)                   # băm TRƯỚC khi biết email có chưa → thời gian như nhau
    with conn.transaction():
        row = conn.execute("INSERT INTO users (email, password_hash, display_name, terms_accepted_at) "
                           "VALUES (%s, %s, %s, now()) ON CONFLICT (email) WHERE deleted_at IS NULL DO NOTHING "
                           "RETURNING user_id", (email, pw_hash, name)).fetchone()
        if row is None:
            return None
        uid = row[0]
        conn.execute("INSERT INTO user_settings (user_id) VALUES (%s)", (uid,))
        conn.execute("INSERT INTO notifications (user_id, kind, body) VALUES (%s, 'system', %s)",
                     (uid, "Chào mừng bạn. Hãy mở link xác minh trong email để hoàn tất."))
        _issue_email(conn, uid, email, "verify_email")
        audit(conn, uid, "user.register", "user", str(uid), ip=ip)
        return _create_session(conn, uid, False, ip, user_agent)


def login(conn: psycopg.Connection, email: str, password: str, remember: bool = False, ip: str | None = None,
          user_agent: str | None = None) -> tuple[dict[str, Any], NewSession]:
    email = S.normalize_email(email)
    if ip and conn.execute("SELECT count(*) FROM login_attempts WHERE ip = %s AND NOT succeeded AND at > now() - %s",
                           (ip, WINDOW)).fetchone()[0] >= IP_MAX_FAILED:
        S.verify_dummy(password)
        raise AccountError(429, "Quá nhiều lần đăng nhập sai từ địa chỉ này. Hãy thử lại sau 15 phút.")

    def attempt(ok: bool, reason: str) -> None:
        conn.execute("INSERT INTO login_attempts (email_tried, ip, succeeded, reason) VALUES (%s, %s, %s, %s)",
                     (email[:254], ip, ok, reason))

    row = conn.execute(f"SELECT {USER_COLS}, u.password_hash, u.status, coalesce(u.locked_until > now(), false) "
                       "FROM users u WHERE u.email = %s AND u.deleted_at IS NULL", (email,)).fetchone()
    if row is None:
        S.verify_dummy(password)
        attempt(False, "unknown_email")
        raise AccountError(401, GENERIC_LOGIN)
    uid, pw_hash, status, locked = row[0], row[6], row[7], row[8]
    if locked:
        S.verify_dummy(password)
        attempt(False, "locked")
        raise AccountError(423, GENERIC_LOGIN)
    ok, rehash = S.verify_password(pw_hash, password)
    if status != "active":
        attempt(False, "disabled")
        raise AccountError(401, GENERIC_LOGIN)
    if not ok:
        attempt(False, "bad_password")
        # Đếm lần sai từ mốc muộn nhất trong: 15 phút trước, lần đăng nhập đúng gần nhất, lúc khoá/mở khoá gần nhất.
        n = conn.execute(
            "SELECT count(*) FROM login_attempts WHERE email_tried = %s AND reason = 'bad_password' AND at > greatest("
            "now() - %s, (SELECT coalesce(max(at), '-infinity') FROM login_attempts WHERE email_tried = %s AND succeeded),"
            " (SELECT coalesce(locked_until, '-infinity') FROM users WHERE user_id = %s))",
            (email, WINDOW, email, uid)).fetchone()[0]
        if n >= MAX_FAILED:
            conn.execute("UPDATE users SET locked_until = now() + %s WHERE user_id = %s", (LOCK, uid))
            audit(conn, uid, "user.locked", "user", str(uid), {"failed": n}, ip, "system")
        raise AccountError(401, GENERIC_LOGIN)
    with conn.transaction():
        if rehash:
            conn.execute("UPDATE users SET password_hash = %s WHERE user_id = %s", (S.hash_password(password), uid))
        conn.execute("UPDATE users SET last_login_at = now() WHERE user_id = %s", (uid,))
        attempt(True, "ok")
        audit(conn, uid, "user.login", "user", str(uid), ip=ip)
        session = _create_session(conn, uid, remember, ip, user_agent)
    return user_public(row), session


def session_user(conn: psycopg.Connection, token: str | None) -> CurrentUser | None:
    """Người dùng của cookie phiên (None nếu không có / hết hạn / bị thu hồi / tài khoản đã xoá hay bị khoá hẳn).
    Cập nhật last_seen + trượt hạn tối đa mỗi 5 phút (không ghi DB mỗi request)."""
    if not token or len(token) > 200:
        return None
    row = conn.execute(
        f"SELECT s.session_id, s.csrf_token, s.remember, s.last_seen_at < now() - %s, {USER_COLS} "
        "FROM user_sessions s JOIN users u USING (user_id) WHERE s.token_hash = %s AND s.revoked_at IS NULL "
        "AND s.expires_at > now() AND u.deleted_at IS NULL AND u.status = 'active'",
        (TOUCH_EVERY, S.sha256_hex(token))).fetchone()
    if row is None:
        return None
    sid, csrf, remember, stale = row[:4]
    if stale:
        conn.execute("UPDATE user_sessions SET last_seen_at = now(), expires_at = least(created_at + %s, now() + %s) "
                     "WHERE session_id = %s", (SESSION_MAX, SESSION_REMEMBER if remember else SESSION_SHORT, sid))
    uid, email, name, role, verified, created = row[4:]
    return CurrentUser(uid, email, name, role, bool(verified), created, sid, csrf)


def logout(conn: psycopg.Connection, user: CurrentUser) -> None:
    conn.execute("UPDATE user_sessions SET revoked_at = now() WHERE session_id = %s AND revoked_at IS NULL",
                 (user.session_id,))


def logout_all(conn: psycopg.Connection, user_id: int, keep_session_id: int | None = None) -> int:
    return conn.execute("UPDATE user_sessions SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL "
                        "AND session_id IS DISTINCT FROM %s", (user_id, keep_session_id)).rowcount


# ---------------------------------------------------------------------- token email / mật khẩu
def _use_token(conn: psycopg.Connection, token: str, purpose: str) -> int:
    row = conn.execute("UPDATE auth_tokens SET used_at = now() WHERE token_hash = %s AND purpose = %s "
                       "AND used_at IS NULL AND expires_at > now() RETURNING user_id",
                       (S.sha256_hex(token or ""), purpose)).fetchone()
    if row is None:
        raise AccountError(400, BAD_LINK[purpose])
    return row[0]


def verify_email(conn: psycopg.Connection, token: str) -> None:
    with conn.transaction():
        uid = _use_token(conn, token, "verify_email")
        conn.execute("UPDATE users SET email_verified_at = coalesce(email_verified_at, now()), updated_at = now() "
                     "WHERE user_id = %s", (uid,))
        audit(conn, uid, "user.verify_email", "user", str(uid))


def forgot_password(conn: psycopg.Connection, email: str, ip: str | None = None) -> None:
    """Luôn im lặng (người gọi trả cùng phản hồi). Tối đa 3 thư đặt lại mỗi giờ cho một tài khoản."""
    email = S.normalize_email(email)
    row = conn.execute("SELECT user_id FROM users WHERE email = %s AND deleted_at IS NULL AND status = 'active'",
                       (email,)).fetchone()
    if row is None:
        return
    uid = row[0]
    if conn.execute("SELECT count(*) FROM auth_tokens WHERE user_id = %s AND purpose = 'reset_password' "
                    "AND created_at > now() - interval '1 hour'", (uid,)).fetchone()[0] >= FORGOT_MAX_PER_HOUR:
        return
    with conn.transaction():
        _issue_email(conn, uid, email, "reset_password")
        audit(conn, uid, "user.password_reset_request", "user", str(uid), ip=ip)


def reset_password(conn: psycopg.Connection, token: str, password: str, ip: str | None = None) -> None:
    if problem := S.password_problem(password):
        raise AccountError(400, problem)
    pw_hash = S.hash_password(password)
    with conn.transaction():
        uid = _use_token(conn, token, "reset_password")
        # Mở khoá tạm: người dùng vừa chứng minh sở hữu email (đặt mốc = now để không đếm lần sai cũ).
        conn.execute("UPDATE users SET password_hash = %s, updated_at = now(), locked_until = CASE WHEN "
                     "locked_until > now() THEN now() ELSE locked_until END WHERE user_id = %s", (pw_hash, uid))
        logout_all(conn, uid)
        audit(conn, uid, "user.password_reset", "user", str(uid), ip=ip)


def change_password(conn: psycopg.Connection, user: CurrentUser, old_password: str, new_password: str,
                    ip: str | None = None) -> None:
    stored = conn.execute("SELECT password_hash FROM users WHERE user_id = %s", (user.user_id,)).fetchone()[0]
    if not S.verify_password(stored, old_password)[0]:
        raise AccountError(400, "Mật khẩu hiện tại không đúng.")
    if problem := S.password_problem(new_password):
        raise AccountError(400, problem)
    pw_hash = S.hash_password(new_password)
    with conn.transaction():
        conn.execute("UPDATE users SET password_hash = %s, updated_at = now() WHERE user_id = %s", (pw_hash, user.user_id))
        n = logout_all(conn, user.user_id, keep_session_id=user.session_id)
        audit(conn, user.user_id, "user.password_change", "user", str(user.user_id), {"revoked_sessions": n}, ip)
