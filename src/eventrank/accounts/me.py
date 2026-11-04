"""Mục "Của tôi": hộp thư, theo dõi / lưu sự kiện, đăng ký chủ đề, cài đặt, thiết bị đăng nhập, xoá tài khoản; báo sai.

Hình dạng JSON khớp `apps/web/src/api/mockdb.ts` (Follow, Bookmark, Subscription, Notification, Settings, Session).
Tên sự kiện trả ra là `events.display_name` — tên ĐÃ áp luật ẩn tên lúc nạp (serving/db_import.py).
"""
from __future__ import annotations

import unicodedata
from typing import Any

import psycopg

from eventrank.accounts import security as S
from eventrank.accounts.auth import AccountError, CurrentUser, audit, logout_all

MAX_TOPICS = 50
FEEDBACK_PER_IP_HOUR = 20
NOTIFICATION_LIMIT = 100
KIND_LABEL = {"system": "Hệ thống", "event_new": "Sự kiện mới", "event_update": "Diễn biến mới",
              "topic_match": "Chủ đề bạn đăng ký"}
SETTINGS_COLS = {"push": "push_enabled", "digest": "email_digest", "quiet_from": "quiet_start", "quiet_to": "quiet_end",
                 "hidden_sources": "hidden_sources"}
SNAPSHOT = "e.event_id, e.display_name, e.size, e.n_sources, e.category_std"


def _snapshot(row: tuple) -> dict[str, Any]:
    eid, name, size, n_sources, cat = row[:5]
    return {"event_id": eid, "ten": name, "size": size, "n_sources": n_sources, "chuyen_muc": cat}


def _require_event(conn: psycopg.Connection, event_id: str) -> None:
    if not conn.execute("SELECT EXISTS (SELECT 1 FROM events WHERE event_id = %s AND status IN ('open', 'closed'))",
                        (event_id,)).fetchone()[0]:
        raise AccountError(404, "Không tìm thấy sự kiện.")


# ---------------------------------------------------------------------- hộp thư
def notifications(conn: psycopg.Connection, user_id: int) -> list[dict[str, Any]]:
    return [{"id": str(nid), "kind": KIND_LABEL.get(kind, kind), "text": body, "event_id": eid, "at": at,
             "read": read_at is not None}
            for nid, kind, body, eid, at, read_at in conn.execute(
                "SELECT notification_id, kind, body, event_id, created_at, read_at FROM notifications WHERE user_id = %s "
                "ORDER BY created_at DESC, notification_id DESC LIMIT %s", (user_id, NOTIFICATION_LIMIT))]


def mark_all_read(conn: psycopg.Connection, user_id: int) -> None:
    conn.execute("UPDATE notifications SET read_at = now() WHERE user_id = %s AND read_at IS NULL", (user_id,))


# ---------------------------------------------------------------------- theo dõi / lưu
def follows(conn: psycopg.Connection, user_id: int) -> list[dict[str, Any]]:
    return [{**_snapshot(r), "notify": r[5], "at": r[6]} for r in conn.execute(
        f"SELECT {SNAPSHOT}, f.notify, f.created_at FROM event_follows f JOIN events e USING (event_id) "
        "WHERE f.user_id = %s ORDER BY f.created_at DESC", (user_id,))]


def follow(conn: psycopg.Connection, user_id: int, event_id: str) -> None:
    _require_event(conn, event_id)
    conn.execute("INSERT INTO event_follows (user_id, event_id, last_notified_size) "
                 "SELECT %s, event_id, size FROM events WHERE event_id = %s ON CONFLICT DO NOTHING", (user_id, event_id))


def unfollow(conn: psycopg.Connection, user_id: int, event_id: str) -> None:
    conn.execute("DELETE FROM event_follows WHERE user_id = %s AND event_id = %s", (user_id, event_id))


def set_follow_notify(conn: psycopg.Connection, user_id: int, event_id: str, notify: bool) -> None:
    if not conn.execute("UPDATE event_follows SET notify = %s WHERE user_id = %s AND event_id = %s",
                        (notify, user_id, event_id)).rowcount:
        raise AccountError(404, "Bạn chưa theo dõi sự kiện này.")


def bookmarks(conn: psycopg.Connection, user_id: int) -> list[dict[str, Any]]:
    return [{**_snapshot(r), "note": r[5], "at": r[6]} for r in conn.execute(
        f"SELECT {SNAPSHOT}, b.note, b.created_at FROM event_bookmarks b JOIN events e USING (event_id) "
        "WHERE b.user_id = %s ORDER BY b.created_at DESC", (user_id,))]


def bookmark(conn: psycopg.Connection, user_id: int, event_id: str, note: str = "") -> None:
    _require_event(conn, event_id)
    conn.execute("INSERT INTO event_bookmarks (user_id, event_id, note) VALUES (%s, %s, %s) "
                 "ON CONFLICT (user_id, event_id) DO UPDATE SET note = EXCLUDED.note",
                 (user_id, event_id, (note or "").strip()[:500]))


def unbookmark(conn: psycopg.Connection, user_id: int, event_id: str) -> None:
    conn.execute("DELETE FROM event_bookmarks WHERE user_id = %s AND event_id = %s", (user_id, event_id))


# ---------------------------------------------------------------------- chủ đề
def subscriptions(conn: psycopg.Connection, user_id: int) -> list[dict[str, Any]]:
    return [{"id": str(sid), "kind": kind, "value": value, "at": at} for sid, kind, value, at in conn.execute(
        "SELECT subscription_id, kind, value, created_at FROM topic_subscriptions WHERE user_id = %s "
        "ORDER BY created_at, subscription_id", (user_id,))]


def subscribe(conn: psycopg.Connection, user_id: int, kind: str, value: str) -> None:
    v = " ".join(unicodedata.normalize("NFC", value or "").split())
    if not v:
        raise AccountError(400, "Hãy nhập từ khoá.")
    if len(v) > 100:
        raise AccountError(400, "Chủ đề dài tối đa 100 ký tự.")
    with conn.transaction():
        conn.execute("SELECT 1 FROM users WHERE user_id = %s FOR UPDATE", (user_id,))     # đếm + thêm không chạy đua
        if conn.execute("SELECT count(*) FROM topic_subscriptions WHERE user_id = %s",
                        (user_id,)).fetchone()[0] >= MAX_TOPICS:
            raise AccountError(400, f"Tối đa {MAX_TOPICS} chủ đề.")
        conn.execute("INSERT INTO topic_subscriptions (user_id, kind, value) VALUES (%s, %s, %s) "
                     "ON CONFLICT (user_id, kind, lower(value)) DO NOTHING", (user_id, kind, v))


def unsubscribe(conn: psycopg.Connection, user_id: int, subscription_id: int) -> None:
    conn.execute("DELETE FROM topic_subscriptions WHERE user_id = %s AND subscription_id = %s",
                 (user_id, subscription_id))


# ---------------------------------------------------------------------- cài đặt, thiết bị, tài khoản
def settings(conn: psycopg.Connection, user_id: int) -> dict[str, Any]:
    conn.execute("INSERT INTO user_settings (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
    push, digest, qs, qe, hidden = conn.execute(
        "SELECT push_enabled, email_digest, quiet_start, quiet_end, hidden_sources FROM user_settings "
        "WHERE user_id = %s", (user_id,)).fetchone()
    return {"push": push, "digest": digest, "quiet_from": qs.strftime("%H:%M"), "quiet_to": qe.strftime("%H:%M"),
            "hidden_sources": list(hidden)}


def update_settings(conn: psycopg.Connection, user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    """`patch`: các khoá của Settings (đã kiểm kiểu ở lớp API); khoá lạ bị bỏ qua."""
    sets = [(SETTINGS_COLS[k], v) for k, v in patch.items() if k in SETTINGS_COLS and v is not None]
    if sets:
        settings(conn, user_id)                            # bảo đảm có dòng
        conn.execute("UPDATE user_settings SET " + ", ".join(f"{c} = %s" for c, _ in sets) + ", updated_at = now() "
                     "WHERE user_id = %s", [v for _, v in sets] + [user_id])
    return settings(conn, user_id)


def sessions(conn: psycopg.Connection, user: CurrentUser) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT session_id, user_agent, created_at, last_seen_at FROM user_sessions WHERE user_id = %s "
                        "AND revoked_at IS NULL AND expires_at > now() ORDER BY last_seen_at DESC", (user.user_id,))
    out = [{"id": str(sid), "device": S.device_label(ua), "created_at": created, "last_seen": seen,
            "current": sid == user.session_id} for sid, ua, created, seen in rows]
    return sorted(out, key=lambda s: not s["current"])     # phiên hiện tại lên đầu (sort ổn định)


def revoke_session(conn: psycopg.Connection, user_id: int, session_id: int) -> None:
    conn.execute("UPDATE user_sessions SET revoked_at = now() WHERE user_id = %s AND session_id = %s "
                 "AND revoked_at IS NULL", (user_id, session_id))


def delete_account(conn: psycopg.Connection, user: CurrentUser, ip: str | None = None) -> None:
    """Xoá mềm: khoá đăng nhập + thu hồi mọi phiên ngay; sau 30 ngày `cleanup` xoá dữ liệu cá nhân và ẩn danh email."""
    with conn.transaction():
        conn.execute("UPDATE users SET deleted_at = now(), updated_at = now() WHERE user_id = %s AND deleted_at IS NULL",
                     (user.user_id,))
        logout_all(conn, user.user_id)
        audit(conn, user.user_id, "user.delete", "user", str(user.user_id), ip=ip)


# ---------------------------------------------------------------------- báo sai
def feedback(conn: psycopg.Connection, event_id: str, kind: str, note: str, user_id: int | None = None,
             ip: str | None = None) -> None:
    """Khách gửi được; tối đa 20 báo/giờ từ một IP (khách) hoặc một tài khoản."""
    _require_event(conn, event_id)
    if user_id is not None:
        n = conn.execute("SELECT count(*) FROM feedback_reports WHERE user_id = %s AND created_at > now() - "
                         "interval '1 hour'", (user_id,)).fetchone()[0]
    elif ip:
        n = conn.execute("SELECT count(*) FROM feedback_reports WHERE user_id IS NULL AND ip = %s AND created_at > "
                         "now() - interval '1 hour'", (ip,)).fetchone()[0]
    else:
        n = 0
    if n >= FEEDBACK_PER_IP_HOUR:
        raise AccountError(429, "Bạn đã gửi nhiều báo sai trong một giờ. Hãy thử lại sau.")
    conn.execute("INSERT INTO feedback_reports (user_id, event_id, kind, message, ip) VALUES (%s, %s, %s, %s, %s)",
                 (user_id, event_id, kind, (note or "").strip()[:1000], ip))
