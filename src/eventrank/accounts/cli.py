"""CLI tài khoản: tạo người dùng (admin đầu tiên), đổi vai trò, dọn dữ liệu cá nhân quá hạn lưu.

    uv run python -m eventrank.accounts create-user --email a@b.vn --name "Quản trị" --role admin
        (mật khẩu: biến môi trường ACCOUNT_PASSWORD nếu có, không thì hỏi — không truyền trên dòng lệnh)
    uv run python -m eventrank.accounts set-role --email a@b.vn --role editor
    uv run python -m eventrank.accounts cleanup

Đăng ký trên web luôn tạo vai trò `user`; admin/editor chỉ tạo được ở đây hoặc bởi admin trên trang Quản trị.
Hạn lưu (thiết kế database, mục Bảo mật): lần thử đăng nhập 30 ngày; phiên hết hạn/thu hồi 30 ngày; token email đã
dùng/hết hạn 7 ngày; IP ở báo sai và nhật ký quản trị 90 ngày; nhật ký quản trị 1 năm; tài khoản đã xoá 30 ngày rồi
xoá dữ liệu cá nhân + ẩn danh email.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

import psycopg

from eventrank.accounts import security as S
from eventrank.accounts.auth import audit
from eventrank.common import db

CLEANUP = [
    ("login_attempts", "DELETE FROM login_attempts WHERE at < now() - interval '30 days'"),
    ("user_sessions", "DELETE FROM user_sessions WHERE coalesce(revoked_at, expires_at) < now() - interval '30 days'"),
    ("auth_tokens", ("DELETE FROM auth_tokens WHERE (used_at IS NOT NULL OR expires_at < now()) "
                     "AND created_at < now() - interval '7 days'")),
    ("email_outbox (bỏ token)", ("UPDATE email_outbox SET payload = payload - 'token' - 'link' WHERE payload ? 'token' "
                                 "AND created_at < now() - interval '7 days'")),
    ("feedback_reports (bỏ IP)", ("UPDATE feedback_reports SET ip = NULL WHERE ip IS NOT NULL "
                                  "AND created_at < now() - interval '90 days'")),
    ("audit_logs (bỏ IP)", "UPDATE audit_logs SET ip = NULL WHERE ip IS NOT NULL AND at < now() - interval '90 days'"),
    ("audit_logs", "DELETE FROM audit_logs WHERE at < now() - interval '1 year'"),
]
EXPIRED_USERS = "SELECT user_id FROM users WHERE deleted_at < now() - interval '30 days' AND email NOT LIKE 'da-xoa-%%'"
PURGE_USER = [
    "DELETE FROM event_bookmarks WHERE user_id = %(u)s",
    "DELETE FROM event_follows WHERE user_id = %(u)s",
    "DELETE FROM topic_subscriptions WHERE user_id = %(u)s",
    "DELETE FROM notifications WHERE user_id = %(u)s",
    "DELETE FROM rag_conversations WHERE user_id = %(u)s",       # lịch sử hỏi đáp (008); rag_messages xoá theo
    "DELETE FROM user_sessions WHERE user_id = %(u)s",
    "DELETE FROM auth_tokens WHERE user_id = %(u)s",
    "DELETE FROM user_settings WHERE user_id = %(u)s",
    ("UPDATE users SET email = 'da-xoa-' || user_id || '@an-danh.invalid', display_name = 'Tài khoản đã xoá', "
     "password_hash = NULL, email_verified_at = NULL, updated_at = now() WHERE user_id = %(u)s"),
]


def create_user(conn: psycopg.Connection, email: str, name: str, password: str, role: str = "user") -> int:
    email = S.normalize_email(email)
    if not S.valid_email(email):
        raise ValueError(f"email không hợp lệ: {email!r}")
    if problem := S.password_problem(password):
        raise ValueError(problem)
    with conn.transaction():
        uid = conn.execute("INSERT INTO users (email, password_hash, display_name, role, email_verified_at, "
                           "terms_accepted_at) VALUES (%s, %s, %s, %s, now(), now()) RETURNING user_id",
                           (email, S.hash_password(password), " ".join(name.split()) or email, role)).fetchone()[0]
        conn.execute("INSERT INTO user_settings (user_id) VALUES (%s)", (uid,))
        audit(conn, None, "user.create_cli", "user", str(uid), {"role": role}, actor_kind="system")
    return uid


def cleanup(conn: psycopg.Connection) -> dict[str, int]:
    out = {}
    with conn.transaction():
        for label, sql in CLEANUP:
            out[label] = conn.execute(sql).rowcount
        users = [u for (u,) in conn.execute(EXPIRED_USERS).fetchall()]
        for u in users:
            for sql in PURGE_USER:
                conn.execute(sql, {"u": u})
        out["users (ẩn danh)"] = len(users)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eventrank.accounts", description=__doc__.split("\n")[0])
    ap.add_argument("--db-env", default="DATABASE_URL", help="TÊN biến môi trường chứa URL Postgres")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-user", help="tạo tài khoản (đã xác minh email)")
    c.add_argument("--email", required=True)
    c.add_argument("--name", default="")
    c.add_argument("--role", choices=["user", "editor", "admin"], default="user")
    r = sub.add_parser("set-role", help="đổi vai trò")
    r.add_argument("--email", required=True)
    r.add_argument("--role", choices=["user", "editor", "admin"], required=True)
    sub.add_parser("cleanup", help="dọn dữ liệu cá nhân quá hạn lưu")
    a = ap.parse_args(argv)
    try:
        with db.connect(env=a.db_env) as conn:
            if a.cmd == "create-user":
                pw = os.environ.get("ACCOUNT_PASSWORD") or getpass.getpass("Mật khẩu: ")
                uid = create_user(conn, a.email, a.name, pw, a.role)
                print(f"Đã tạo tài khoản #{uid} {S.normalize_email(a.email)} (vai trò {a.role}).")
            elif a.cmd == "set-role":
                n = conn.execute("UPDATE users SET role = %s, updated_at = now() WHERE email = %s AND deleted_at IS NULL",
                                 (a.role, S.normalize_email(a.email))).rowcount
                if not n:
                    print("LỖI: không có tài khoản với email này.", file=sys.stderr)
                    return 1
                audit(conn, None, "user.role_change_cli", "user", S.normalize_email(a.email), {"to": a.role},
                      actor_kind="system")
                print(f"Đã đổi vai trò thành {a.role}.")
            else:
                for k, v in cleanup(conn).items():
                    print(f"  {k:<28} {v}")
    except (db.DatabaseConfigError, ValueError) as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 1
    except psycopg.errors.UniqueViolation:
        print("LỖI: email này đã có tài khoản.", file=sys.stderr)
        return 1
    return 0
