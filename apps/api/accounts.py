"""API tài khoản: /api/auth/*, /api/me/*, /api/admin/*, POST /api/events/{id}/feedback.

Hợp đồng khớp lớp giả lập của web (apps/web/src/api/{auth,me,admin}.ts) → web chỉ cần `VITE_AUTH_MOCK=0`.
Nghiệp vụ ở `eventrank.accounts`; ở đây chỉ có HTTP: pool kết nối, cookie, CSRF, phân quyền, mã lỗi.

- Cần Postgres (`DATABASE_URL`, migration 003–006). Thiếu → các endpoint này trả 503, phần còn lại của API vẫn chạy.
- Cookie `er_session` (HttpOnly, SameSite=Lax) giữ token phiên; cookie `csrf_token` (đọc được bằng JS) — mọi POST/PUT/
  DELETE của người đã đăng nhập phải gửi lại nó trong header `X-CSRF-Token` (không khớp → 403).
- `Secure` cho cookie: `COOKIE_SECURE=1|0`; không đặt → tự bật khi yêu cầu đến qua HTTPS (kể cả `X-Forwarded-Proto`).
- IP người dùng: `request.client.host`; sau Cloudflare Tunnel/reverse proxy đặt `TRUST_PROXY_HEADERS=1` để đọc
  `CF-Connecting-IP` / `X-Forwarded-For` (không đặt khi API mở thẳng ra ngoài — header giả được).
- Mã lỗi web đang hiểu: 401 chưa đăng nhập / sai thông tin, 423 tài khoản đang khoá, 400 dữ liệu không hợp lệ,
  403 sai CSRF hoặc thiếu quyền, 429 quá nhiều yêu cầu.
"""
from __future__ import annotations

import ipaddress
import os
import secrets
import threading
from collections.abc import Iterator
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from psycopg_pool import ConnectionPool

from apps.api import schemas
from eventrank.accounts import admin as A
from eventrank.accounts import auth as AU
from eventrank.accounts import me as M
from eventrank.accounts.auth import AccountError, CurrentUser, NewSession
from eventrank.common import db

SESSION_COOKIE = "er_session"
CSRF_COOKIE = "csrf_token"
EVENT_ID = r"^E\d{8}-[0-9a-f]{8}$"
NO_DB = ("Tài khoản cần Postgres: đặt DATABASE_URL, chạy `make db-migrate` (migration 003–006) rồi khởi động lại API.")
_pool_lock = threading.Lock()

router = APIRouter()


# ---------------------------------------------------------------------- kết nối
def _pool(request: Request) -> ConnectionPool:
    """Pool tạo lười ở yêu cầu đầu tiên (test truyền `db_url` qua create_app; chạy thật đọc DATABASE_URL)."""
    st = request.app.state
    if getattr(st, "db_pool", None) is None:
        with _pool_lock:
            if getattr(st, "db_pool", None) is None:
                try:
                    url = getattr(st, "db_url", None) or db.database_url()
                except db.DatabaseConfigError as exc:
                    raise HTTPException(503, NO_DB) from exc
                st.db_pool = ConnectionPool(url, min_size=1, max_size=10, open=True, timeout=10,
                                            kwargs={"autocommit": True, "application_name": "eventrank-api"})
    return st.db_pool


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    try:
        with _pool(request).connection() as conn:
            yield conn
    except AccountError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    except psycopg.errors.UndefinedTable as exc:       # DB chưa áp 003–006
        raise HTTPException(503, NO_DB) from exc
    except psycopg.OperationalError as exc:
        raise HTTPException(503, "Không kết nối được Postgres (DATABASE_URL).") from exc


Conn = Annotated[psycopg.Connection, Depends(get_conn)]


def client_ip(request: Request) -> str | None:
    raw = None
    if os.environ.get("TRUST_PROXY_HEADERS", "").strip() in ("1", "true", "yes"):
        raw = request.headers.get("cf-connecting-ip") or (request.headers.get("x-forwarded-for") or "").split(",")[0]
    raw = (raw or "").strip() or (request.client.host if request.client else None)
    try:
        return str(ipaddress.ip_address(raw)) if raw else None
    except ValueError:                                   # "testclient" của TestClient, header rác
        return None


def _secure(request: Request) -> bool:
    flag = os.environ.get("COOKIE_SECURE", "").strip().lower()
    if flag in ("1", "true", "yes", "0", "false", "no"):
        return flag in ("1", "true", "yes")
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"


def _set_session(request: Request, response: Response, s: NewSession) -> None:
    kw: dict[str, Any] = {"samesite": "lax", "secure": _secure(request), "path": "/", "max_age": s.max_age}
    response.set_cookie(SESSION_COOKIE, s.token, httponly=True, **kw)
    response.set_cookie(CSRF_COOKIE, s.csrf_token, httponly=False, **kw)


def _clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


# ---------------------------------------------------------------------- người dùng hiện tại
def optional_user(request: Request, conn: Conn) -> CurrentUser | None:
    return AU.session_user(conn, request.cookies.get(SESSION_COOKIE))


def _csrf_ok(request: Request, user: CurrentUser) -> bool:
    return secrets.compare_digest(request.headers.get("x-csrf-token", ""), user.csrf_token)


def current_user(request: Request, user: Annotated[CurrentUser | None, Depends(optional_user)]) -> CurrentUser:
    if user is None:
        raise HTTPException(401, "Bạn cần đăng nhập.")
    if request.method not in ("GET", "HEAD", "OPTIONS") and not _csrf_ok(request, user):
        raise HTTPException(403, "Thiếu hoặc sai mã CSRF — hãy tải lại trang rồi thử lại.")
    return user


User = Annotated[CurrentUser, Depends(current_user)]


def require_role(*roles: str):
    def dep(user: User) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(403, "Bạn không có quyền vào khu này.")
        return user
    return Depends(dep)


Admin = Annotated[CurrentUser, require_role("admin")]
Editor = Annotated[CurrentUser, require_role("editor", "admin")]
Ip = Annotated[str | None, Depends(client_ip)]


def _run(fn, *args, **kw):
    """Gọi nghiệp vụ, đổi AccountError → HTTPException (đã ở trong get_conn nhưng lỗi trước yield thì không)."""
    try:
        return fn(*args, **kw)
    except AccountError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


# ---------------------------------------------------------------------- /api/auth
@router.post("/api/auth/register", status_code=204)
def register(body: schemas.RegisterBody, request: Request, response: Response, conn: Conn, ip: Ip) -> None:
    """Tạo tài khoản + thư xác minh và đăng nhập luôn. Email đã có tài khoản: cùng phản hồi 204, không đăng nhập."""
    s = _run(AU.register, conn, body.display_name, body.email, body.password, ip, request.headers.get("user-agent"))
    if s is not None:
        _set_session(request, response, s)


@router.post("/api/auth/login", response_model=schemas.AccountUser)
def login(body: schemas.LoginBody, request: Request, response: Response, conn: Conn, ip: Ip) -> dict[str, Any]:
    user, s = _run(AU.login, conn, body.email, body.password, body.remember, ip, request.headers.get("user-agent"))
    _set_session(request, response, s)
    return user


@router.get("/api/auth/me", response_model=schemas.AccountUser)
def auth_me(user: User) -> dict[str, Any]:
    return user.public()


@router.post("/api/auth/logout", status_code=204)
def logout(response: Response, conn: Conn, user: User) -> None:
    AU.logout(conn, user)
    _clear_session(response)


@router.post("/api/auth/logout-all", status_code=204)
def logout_all(response: Response, conn: Conn, user: User) -> None:
    AU.logout_all(conn, user.user_id)
    _clear_session(response)


@router.post("/api/auth/verify-email", status_code=204)
def verify_email(body: schemas.TokenBody, conn: Conn) -> None:
    _run(AU.verify_email, conn, body.token)


@router.post("/api/auth/forgot-password", status_code=204)
def forgot_password(body: schemas.EmailBody, conn: Conn, ip: Ip) -> None:
    """Luôn 204 — không cho biết email có tài khoản hay không."""
    AU.forgot_password(conn, body.email, ip)


@router.post("/api/auth/reset-password", status_code=204)
def reset_password(body: schemas.ResetPasswordBody, response: Response, conn: Conn, ip: Ip) -> None:
    """Đặt mật khẩu mới → đăng xuất mọi thiết bị (kể cả trình duyệt này)."""
    _run(AU.reset_password, conn, body.token, body.password, ip)
    _clear_session(response)


@router.post("/api/auth/change-password", status_code=204)
def change_password(body: schemas.ChangePasswordBody, conn: Conn, user: User, ip: Ip) -> None:
    """Giữ phiên hiện tại, thu hồi các phiên khác."""
    _run(AU.change_password, conn, user, body.old_password, body.new_password, ip)


# ---------------------------------------------------------------------- /api/me
@router.get("/api/me/notifications", response_model=list[schemas.Notification])
def my_notifications(conn: Conn, user: User) -> list[dict[str, Any]]:
    return M.notifications(conn, user.user_id)


@router.post("/api/me/notifications/read", status_code=204)
def my_notifications_read(conn: Conn, user: User) -> None:
    M.mark_all_read(conn, user.user_id)


@router.get("/api/me/follows", response_model=list[schemas.FollowItem])
def my_follows(conn: Conn, user: User) -> list[dict[str, Any]]:
    return M.follows(conn, user.user_id)


@router.post("/api/me/follows", status_code=204)
def my_follow(body: schemas.EventRef, conn: Conn, user: User) -> None:
    _run(M.follow, conn, user.user_id, body.event_id)


@router.put("/api/me/follows/{event_id}", status_code=204)
def my_follow_update(body: schemas.FollowUpdate, conn: Conn, user: User,
                     event_id: Annotated[str, Path(pattern=EVENT_ID)]) -> None:
    _run(M.set_follow_notify, conn, user.user_id, event_id, body.notify)


@router.delete("/api/me/follows/{event_id}", status_code=204)
def my_unfollow(conn: Conn, user: User, event_id: Annotated[str, Path(pattern=EVENT_ID)]) -> None:
    M.unfollow(conn, user.user_id, event_id)


@router.get("/api/me/bookmarks", response_model=list[schemas.BookmarkItem])
def my_bookmarks(conn: Conn, user: User) -> list[dict[str, Any]]:
    return M.bookmarks(conn, user.user_id)


@router.post("/api/me/bookmarks", status_code=204)
def my_bookmark(body: schemas.BookmarkBody, conn: Conn, user: User) -> None:
    _run(M.bookmark, conn, user.user_id, body.event_id, body.note)


@router.delete("/api/me/bookmarks/{event_id}", status_code=204)
def my_unbookmark(conn: Conn, user: User, event_id: Annotated[str, Path(pattern=EVENT_ID)]) -> None:
    M.unbookmark(conn, user.user_id, event_id)


@router.get("/api/me/subscriptions", response_model=list[schemas.Subscription])
def my_subscriptions(conn: Conn, user: User) -> list[dict[str, Any]]:
    return M.subscriptions(conn, user.user_id)


@router.post("/api/me/subscriptions", status_code=204)
def my_subscribe(body: schemas.SubscriptionBody, conn: Conn, user: User) -> None:
    _run(M.subscribe, conn, user.user_id, body.kind, body.value)


@router.delete("/api/me/subscriptions/{sub_id}", status_code=204)
def my_unsubscribe(conn: Conn, user: User, sub_id: Annotated[int, Path(ge=1)]) -> None:
    M.unsubscribe(conn, user.user_id, sub_id)


@router.get("/api/me/settings", response_model=schemas.Settings)
def my_settings(conn: Conn, user: User) -> dict[str, Any]:
    return M.settings(conn, user.user_id)


@router.put("/api/me/settings", response_model=schemas.Settings)
def my_settings_update(body: schemas.SettingsPatch, conn: Conn, user: User) -> dict[str, Any]:
    return M.update_settings(conn, user.user_id, body.model_dump(exclude_none=True))


@router.get("/api/me/sessions", response_model=list[schemas.SessionInfo])
def my_sessions(conn: Conn, user: User) -> list[dict[str, Any]]:
    return M.sessions(conn, user)


@router.delete("/api/me/sessions/{session_id}", status_code=204)
def my_revoke_session(response: Response, conn: Conn, user: User,
                      session_id: Annotated[int, Path(ge=1)]) -> None:
    M.revoke_session(conn, user.user_id, session_id)
    if session_id == user.session_id:
        _clear_session(response)


@router.delete("/api/me", status_code=204)
def my_delete(response: Response, conn: Conn, user: User, ip: Ip) -> None:
    M.delete_account(conn, user, ip)
    _clear_session(response)


@router.post("/api/events/{event_id}/feedback", status_code=204)
def event_feedback(body: schemas.FeedbackBody, request: Request, conn: Conn, ip: Ip,
                   user: Annotated[CurrentUser | None, Depends(optional_user)],
                   event_id: Annotated[str, Path(pattern=EVENT_ID)]) -> None:
    """Báo sai — khách gửi được. Đang đăng nhập và gửi đúng CSRF thì gắn tên người gửi."""
    uid = user.user_id if user is not None and _csrf_ok(request, user) else None
    _run(M.feedback, conn, event_id, body.kind, body.note, uid, ip)


# ---------------------------------------------------------------------- /api/admin
@router.get("/api/admin/users", response_model=list[schemas.AdminUser])
def admin_users(conn: Conn, _: Admin) -> list[dict[str, Any]]:
    return A.users(conn)


@router.put("/api/admin/users/{user_id}", status_code=204)
def admin_set_role(body: schemas.RoleBody, conn: Conn, actor: Admin, ip: Ip, user_id: str) -> None:
    _run(A.set_role, conn, actor, user_id, body.role, ip)


@router.post("/api/admin/users/{user_id}/unlock", status_code=204)
def admin_unlock(conn: Conn, actor: Admin, ip: Ip, user_id: str) -> None:
    _run(A.unlock, conn, actor, user_id, ip)


@router.get("/api/admin/feedback", response_model=list[schemas.FeedbackItem])
def admin_feedback(conn: Conn, _: Editor) -> list[dict[str, Any]]:
    return A.feedback(conn)


@router.put("/api/admin/feedback/{report_id}", status_code=204)
def admin_resolve_feedback(body: schemas.FeedbackUpdate, conn: Conn, actor: Editor, ip: Ip, report_id: str) -> None:
    _run(A.resolve_feedback, conn, actor, report_id, body.status, ip)


@router.get("/api/admin/outbox", response_model=list[schemas.Mail])
def admin_outbox(conn: Conn, _: Admin) -> list[dict[str, Any]]:
    """Thư hệ thống của bản demo (chưa gửi thật) — có token để quản trị viên chuyển link cho người dùng."""
    return A.outbox(conn)


@router.get("/api/admin/api-tokens", response_model=list[schemas.ApiTokenInfo])
def admin_tokens(conn: Conn, _: Admin) -> list[dict[str, Any]]:
    return A.tokens(conn)


@router.post("/api/admin/api-tokens", response_model=schemas.ApiTokenCreated)
def admin_create_token(body: schemas.ApiTokenBody, conn: Conn, actor: Admin, ip: Ip) -> dict[str, str]:
    return {"token": _run(A.create_token, conn, actor, body.label, body.source, body.scope, ip)}


@router.delete("/api/admin/api-tokens/{token_id}", status_code=204)
def admin_revoke_token(conn: Conn, actor: Admin, ip: Ip, token_id: str) -> None:
    _run(A.revoke_token, conn, actor, token_id, ip)
