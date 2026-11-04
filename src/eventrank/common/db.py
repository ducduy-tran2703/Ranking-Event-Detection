"""Kết nối Postgres và bộ áp migration SQL thuần (không ORM, không alembic).

    uv run --group embed python -m eventrank.common.db status    # đã áp / chưa áp / bị sửa
    uv run --group embed python -m eventrank.common.db migrate   # áp file chưa áp, theo số

Postgres là nơi lưu chính của hệ thống chạy liên tục (bài báo, lần cào, đồng hồ; giai đoạn sau: sự
kiện, tên, điểm). Chỉ dùng tính năng Postgres ≥ 14, KHÔNG pgvector (vector lưu `bytea`) — để chạy
được trên Postgres cài sẵn (apt) lẫn `postgres:16` trong infra/docker-compose.yml.

Migration = file `infra/db/migrations/NNN_<tên>.sql` (NNN ba chữ số, tên chữ thường/số/gạch dưới).
- Mỗi file chạy trong MỘT transaction cùng dòng ghi vào `schema_migrations` (tên file, sha256, thời
  điểm): lỗi giữa file → rollback cả file, không ghi nhận, sửa rồi chạy lại. Vì vậy KHÔNG dùng
  lệnh không chạy được trong transaction (`CREATE INDEX CONCURRENTLY`, `VACUUM`).
- Chạy lại không làm gì. File ĐÃ áp mà nội dung đổi (sha256 khác) → báo lỗi: sửa schema bằng file
  MỚI, không sửa file cũ (máy khác đã áp bản cũ, sửa file cũ làm các DB lệch nhau âm thầm).
- File mới có số NHỎ hơn file đã áp (hai nhánh cùng thêm migration) → từ chối: đánh số lại rồi áp.
- Khoá advisory quanh cả lần áp: worker và API cùng gọi `migrate` lúc khởi động không giẫm nhau.

`DATABASE_URL` đọc từ môi trường / `.env`; thiếu → lỗi rõ ràng, KHÔNG in giá trị (URL chứa mật
khẩu).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = ROOT / "infra/db/migrations"
_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
_LOCK_KEY = 0x6576656E7472616E   # "eventran": khoá advisory riêng cho bộ áp migration


class DatabaseConfigError(RuntimeError):
    """Thiếu/sai cấu hình kết nối. Thông báo không bao giờ chứa URL (có mật khẩu)."""


class MigrationError(RuntimeError):
    pass


def database_url(env: str = "DATABASE_URL") -> str:
    load_dotenv()
    url = os.environ.get(env, "").strip()
    if not url:
        raise DatabaseConfigError(
            f"Thiếu biến môi trường {env}. Đặt trong .env, ví dụ "
            f"{env}=postgresql://eventrank:<mật khẩu>@127.0.0.1:5432/eventrank "
            "(xem .env.example và docs/tong-hop.md mục 16.5).")
    # Chấp nhận URL postgresql:// hoặc chuỗi "host=… dbname=…" của libpq.
    if not url.startswith(("postgresql://", "postgres://")) and "://" in url:
        raise DatabaseConfigError(f"{env} không phải URL Postgres (postgresql://…); "
                                  f"độ dài hiện tại {len(url)} ký tự")
    return url


def connect(url: str | None = None, *, env: str = "DATABASE_URL") -> psycopg.Connection:
    """Kết nối AUTOCOMMIT: mỗi lệnh tự commit, cần nhiều lệnh nguyên tử thì bọc
    `with conn.transaction():`. Tránh kiểu transaction ngầm để lâu (giữ khoá, chặn migration)."""
    return psycopg.connect(url or database_url(env), autocommit=True,
                           application_name="eventrank")


# ---------------------------------------------------------------------- migration
@dataclass(frozen=True)
class Migration:
    number: int
    name: str
    path: Path
    sha256: str

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


def discover_migrations(directory: Path | str = MIGRATIONS_DIR) -> list[Migration]:
    """Mọi `*.sql` trong thư mục, theo số. Tên sai mẫu hay trùng số → lỗi (không lặng lẽ bỏ qua:
    một file bị bỏ qua là một bảng thiếu trên máy người khác)."""
    out: dict[int, Migration] = {}
    for p in sorted(Path(directory).glob("*.sql")):
        m = _NAME.match(p.name)
        if not m:
            raise MigrationError(f"Tên migration sai mẫu NNN_<tên>.sql: {p.name}")
        num = int(m.group(1))
        if num in out:
            raise MigrationError(f"Trùng số migration {m.group(1)}: {out[num].name}, {p.name}")
        out[num] = Migration(num, p.name, p, hashlib.sha256(p.read_bytes()).hexdigest())
    return [out[k] for k in sorted(out)]


def _ensure_table(conn: psycopg.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   text PRIMARY KEY,
            sha256     char(64) NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )""")


def _applied(conn: psycopg.Connection) -> dict[str, tuple[str, Any]]:
    return {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT filename, sha256, applied_at FROM schema_migrations")}


def status(conn: psycopg.Connection,
           directory: Path | str = MIGRATIONS_DIR) -> list[dict[str, Any]]:
    """Mỗi migration một dòng: state = applied | pending | modified | missing (đã áp nhưng file
    không còn — thường do đổi nhánh git)."""
    _ensure_table(conn)
    applied = _applied(conn)
    rows = []
    for m in discover_migrations(directory):
        if m.name not in applied:
            rows.append({"name": m.name, "state": "pending", "applied_at": None})
            continue
        sha, at = applied.pop(m.name)
        rows.append({"name": m.name, "state": "applied" if sha == m.sha256 else "modified",
                     "applied_at": at})
    rows += [{"name": n, "state": "missing", "applied_at": at}
             for n, (_, at) in sorted(applied.items())]
    return rows


def migrate(conn: psycopg.Connection, directory: Path | str = MIGRATIONS_DIR) -> list[str]:
    """Áp các file chưa áp theo thứ tự; trả về tên các file vừa áp ([] nếu không có gì)."""
    conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_KEY,))
    try:
        st = status(conn, directory)
        bad = [r["name"] for r in st if r["state"] == "modified"]
        if bad:
            raise MigrationError(f"Migration đã áp nhưng file đã bị sửa: {', '.join(bad)}. "
                                 "Đừng sửa file đã áp — thêm file migration mới.")
        last_applied = max((r["name"] for r in st if r["state"] in ("applied", "missing")),
                           default="")
        pending = [r["name"] for r in st if r["state"] == "pending"]
        early = [n for n in pending if n < last_applied]
        if early:
            raise MigrationError(
                f"Migration {', '.join(early)} có số nhỏ hơn {last_applied} đã áp (hai nhánh "
                "cùng thêm migration?). Đánh số lại file mới cho lớn hơn rồi chạy lại.")
        by_name = {m.name: m for m in discover_migrations(directory)}
        done = []
        for name in pending:
            m = by_name[name]
            try:
                with conn.transaction():
                    conn.execute(m.sql.encode())   # bytes: không tham số → nhiều lệnh một lần
                    conn.execute("INSERT INTO schema_migrations (filename, sha256) "
                                 "VALUES (%s, %s)", (m.name, m.sha256))
            except psycopg.Error as e:
                raise MigrationError(f"Lỗi khi áp {m.name} (đã rollback cả file): "
                                     f"{e.__class__.__name__}: {e}".strip()) from e
            done.append(name)
        return done
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))


# ---------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eventrank.common.db",
                                 description="Áp / xem migration Postgres (infra/db/migrations/)")
    ap.add_argument("command", choices=["migrate", "status"])
    ap.add_argument("--db-env", default="DATABASE_URL",
                    help="TÊN biến môi trường chứa URL (không truyền URL trên dòng lệnh)")
    ap.add_argument("--dir", default=str(MIGRATIONS_DIR))
    a = ap.parse_args(argv)
    try:
        with connect(env=a.db_env) as conn:
            if a.command == "migrate":
                done = migrate(conn, a.dir)
                print("Đã áp: " + ", ".join(done) if done else "Không có migration mới.")
            for r in status(conn, a.dir):
                at = r["applied_at"].isoformat(timespec="seconds") if r["applied_at"] else ""
                print(f"  {r['state']:<8} {r['name']:<40} {at}")
            bad = [r for r in status(conn, a.dir) if r["state"] in ("modified", "missing")]
            return 1 if bad else 0
    except (DatabaseConfigError, MigrationError) as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
