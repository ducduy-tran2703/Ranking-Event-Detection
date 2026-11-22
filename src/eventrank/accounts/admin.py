"""Quản trị: người dùng (đổi vai trò, mở khoá), báo sai, thư hệ thống (email_outbox), khoá API cho crawler.

Mọi thao tác thay đổi ghi audit_logs. Hình dạng JSON khớp `apps/web/src/api/admin.ts` (AdminUser, Feedback, Mail,
ApiToken). Phân quyền ở lớp API: báo sai — editor + admin; còn lại — admin.
"""
from __future__ import annotations

from typing import Any

import psycopg

from eventrank.accounts import security as S
from eventrank.accounts.auth import USER_COLS, AccountError, CurrentUser, audit, user_public

ROLES = ("user", "editor", "admin")
MAIL_KIND = {"verify_email": "verify", "reset_password": "reset"}
TOKEN_PREFIX = "er_"


def _user_id(raw: str) -> int:
    if not raw.isdigit():
        raise AccountError(404, "Không tìm thấy người dùng.")
    return int(raw)


def users(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return [{**user_public(r), "locked_until": r[6]} for r in conn.execute(
        f"SELECT {USER_COLS}, CASE WHEN u.locked_until > now() THEN u.locked_until END FROM users u "
        "WHERE u.deleted_at IS NULL ORDER BY u.created_at, u.user_id")]


def set_role(conn: psycopg.Connection, actor: CurrentUser, user_id: str, role: str, ip: str | None = None) -> None:
    uid = _user_id(user_id)
    if role not in ROLES:
        raise AccountError(400, "Vai trò không hợp lệ.")
    if uid == actor.user_id and role != "admin":
        raise AccountError(400, "Không tự hạ quyền của chính mình (tránh khoá mất trang quản trị).")
    with conn.transaction():
        old = conn.execute("SELECT role FROM users WHERE user_id = %s AND deleted_at IS NULL FOR UPDATE",
                           (uid,)).fetchone()
        if old is None:
            raise AccountError(404, "Không tìm thấy người dùng.")
        conn.execute("UPDATE users SET role = %s, updated_at = now() WHERE user_id = %s", (role, uid))
        audit(conn, actor.user_id, "user.role_change", "user", str(uid), {"from": old[0], "to": role}, ip)


def unlock(conn: psycopg.Connection, actor: CurrentUser, user_id: str, ip: str | None = None) -> None:
    uid = _user_id(user_id)
    # locked_until = now(): hết khoá ngay VÀ các lần sai trước đó không còn được đếm (xem auth.login).
    if not conn.execute("UPDATE users SET locked_until = now(), updated_at = now() WHERE user_id = %s "
                        "AND deleted_at IS NULL", (uid,)).rowcount:
        raise AccountError(404, "Không tìm thấy người dùng.")
    audit(conn, actor.user_id, "user.unlock", "user", str(uid), ip=ip)


# ---------------------------------------------------------------------- báo sai
def feedback(conn: psycopg.Connection, limit: int = 200) -> list[dict[str, Any]]:
    return [{"id": str(rid), "event_id": eid, "event_name": name, "kind": kind, "note": msg, "who": who or "khách",
             "at": at, "status": status}
            for rid, eid, name, kind, msg, who, at, status in conn.execute(
                "SELECT f.report_id, f.event_id, e.display_name, f.kind, f.message, u.display_name, f.created_at, "
                "f.status FROM feedback_reports f JOIN events e USING (event_id) LEFT JOIN users u ON u.user_id = "
                "f.user_id ORDER BY (f.status = 'open') DESC, f.created_at DESC LIMIT %s", (limit,))]


def resolve_feedback(conn: psycopg.Connection, actor: CurrentUser, report_id: str, status: str,
                     ip: str | None = None) -> None:
    if not report_id.isdigit() or not conn.execute(
            "UPDATE feedback_reports SET status = %s, resolved_by = %s, resolved_at = now() WHERE report_id = %s",
            (status, actor.user_id, int(report_id))).rowcount:
        raise AccountError(404, "Không tìm thấy báo sai.")
    audit(conn, actor.user_id, "feedback.resolve", "feedback", report_id, {"status": status}, ip)


# ---------------------------------------------------------------------- thư hệ thống
def outbox(conn: psycopg.Connection, limit: int = 100) -> list[dict[str, Any]]:
    """Thư chưa gửi thật (bản demo). `token` có trong payload cho tới khi tiến trình gửi thư xoá nó; `used` = token đã
    dùng hoặc bị token mới thay."""
    return [{"id": str(mid), "at": at, "to": to, "kind": MAIL_KIND.get(tpl, tpl), "token": payload.get("token", ""),
             "used": bool(used), "expires_at": payload.get("expires_at")}
            for mid, at, to, tpl, payload, used in conn.execute(
                "SELECT m.email_id, m.created_at, m.to_email, m.template, m.payload, t.used_at IS NOT NULL "
                "FROM email_outbox m LEFT JOIN auth_tokens t ON t.token_hash = m.payload->>'token_hash' "
                "WHERE m.template IN ('verify_email', 'reset_password') ORDER BY m.created_at DESC, m.email_id DESC "
                "LIMIT %s", (limit,))]


# ---------------------------------------------------------------------- khoá API
def tokens(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return [{"id": str(tid), "label": name, "source": source or "", "prefix": prefix, "created_at": created,
             "revoked": revoked is not None}
            for tid, name, source, prefix, created, revoked in conn.execute(
                "SELECT token_id, name, source, prefix, created_at, revoked_at FROM api_tokens "
                "ORDER BY created_at DESC, token_id DESC")]


def create_token(conn: psycopg.Connection, actor: CurrentUser, label: str, source: str, scope: str = "ingest:write",
                 ip: str | None = None) -> str:
    """Trả khoá ĐẦY ĐỦ — chỉ một lần; DB giữ sha256 + 10 ký tự đầu."""
    name = " ".join((label or "").split())[:80] or "Không tên"
    src = (source or "").strip().lower() or None
    if src and not conn.execute("SELECT EXISTS (SELECT 1 FROM sources WHERE source = %s)", (src,)).fetchone()[0]:
        raise AccountError(400, f"Không có báo '{src}' trong danh sách nguồn.")
    if scope not in ("ingest:write", "read"):
        raise AccountError(400, "Phạm vi khoá không hợp lệ.")
    token = TOKEN_PREFIX + S.new_token(30)
    with conn.transaction():
        tid = conn.execute("INSERT INTO api_tokens (name, prefix, token_hash, scopes, source, created_by) "
                           "VALUES (%s, %s, %s, %s, %s, %s) RETURNING token_id",
                           (name, token[:10], S.sha256_hex(token), [scope], src, actor.user_id)).fetchone()[0]
        audit(conn, actor.user_id, "api_token.create", "api_token", str(tid), {"name": name, "source": src,
                                                                               "scope": scope}, ip)
    return token


def revoke_token(conn: psycopg.Connection, actor: CurrentUser, token_id: str, ip: str | None = None) -> None:
    if not token_id.isdigit() or not conn.execute(
            "UPDATE api_tokens SET revoked_at = coalesce(revoked_at, now()) WHERE token_id = %s",
            (int(token_id),)).rowcount:
        raise AccountError(404, "Không tìm thấy khoá API.")
    audit(conn, actor.user_id, "api_token.revoke", "api_token", token_id, ip=ip)
