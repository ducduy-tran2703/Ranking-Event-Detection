"""Băm mật khẩu, sinh/băm token, luật mật khẩu và email, nhãn thiết bị. Không phụ thuộc DB.

- Mật khẩu: Argon2id (argon2-cffi, tham số mặc định của thư viện: t=3, m=64 MiB, p=4 — ~50 ms/lần). Lưu dạng PHC.
- Token (phiên, email, khoá API): 32 byte ngẫu nhiên (`secrets`), DB chỉ lưu sha256 hex → lộ DB không lộ phiên.
- Email không tồn tại vẫn chạy một lần Argon2 trên băm giả (`verify_dummy`) để thời gian phản hồi như nhau.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_PH = PasswordHasher()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD, MAX_PASSWORD = 8, 256                  # giới hạn trên: chặn băm chuỗi khổng lồ (DoS)
# Cùng danh sách với web (apps/web/src/api/auth.ts) + vài mật khẩu phổ biến tiếng Việt.
COMMON_PASSWORDS = frozenset({
    "12345678", "123456789", "1234567890", "password", "matkhau123", "11111111", "qwertyui", "abc12345", "iloveyou",
    "88888888", "00000000", "password1", "qwerty123", "matkhau", "anhyeuem", "123123123", "12341234",
})


def normalize_email(email: str) -> str:
    return unicodedata.normalize("NFC", (email or "").strip()).lower()


def valid_email(email: str) -> bool:
    return len(email) <= 254 and bool(EMAIL_RE.match(email))


def password_problem(pw: str) -> str | None:
    """Thông báo lỗi (tiếng Việt) nếu mật khẩu mới không đạt, không thì None. Cùng luật với web."""
    if len(pw) < MIN_PASSWORD:
        return f"Mật khẩu cần ít nhất {MIN_PASSWORD} ký tự."
    if len(pw) > MAX_PASSWORD:
        return f"Mật khẩu dài tối đa {MAX_PASSWORD} ký tự."
    if pw.lower() in COMMON_PASSWORDS:
        return "Mật khẩu quá phổ biến, hãy chọn mật khẩu khác."
    return None


def hash_password(pw: str) -> str:
    return _PH.hash(pw)


def verify_password(stored: str | None, pw: str) -> tuple[bool, bool]:
    """(đúng?, cần băm lại?). Băm hỏng/thiếu → (False, False), vẫn tốn thời gian như băm thật."""
    if not stored:
        verify_dummy(pw)
        return False, False
    try:
        _PH.verify(stored, pw)
    except (VerificationError, InvalidHashError):
        return False, False
    return True, _PH.check_needs_rehash(stored)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _PH.hash("eventrank-khong-co-tai-khoan")


def verify_dummy(pw: str) -> None:
    try:
        _PH.verify(_dummy_hash(), pw)
    except VerificationError:
        pass


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def device_label(user_agent: str | None) -> str:
    """"Chrome trên Windows" — cùng luật với deviceLabel() của web."""
    ua = user_agent or ""
    browser = ("Edge" if "Edg/" in ua else "Firefox" if "Firefox/" in ua else "Chrome" if "Chrome/" in ua
               else "Safari" if "Safari/" in ua else "Trình duyệt")
    os_ = ("Windows" if "Windows" in ua else "Android" if "Android" in ua else "iOS" if re.search(r"iPhone|iPad", ua)
           else "macOS" if "Mac OS X" in ua else "Linux" if "Linux" in ua else "máy không rõ")
    return f"{browser} trên {os_}"
