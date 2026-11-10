"""Kết quả pipeline sự kiện đọc từ Postgres (tầng sự kiện, migration 002_events.sql) — cùng giao diện với `EventStore`.

    EVENTS_BACKEND=db      API đọc DATABASE_URL lúc khởi động (mặc định `files`: thư mục data/runs/<run_id>/)

Chỉ DỮ LIỆU đến từ DB: sự kiện (`events`), bài (`event_articles` ⋈ `articles`), top-K xu hướng mỗi mốc (`trend_scores`),
cấu hình của run (`worker_runs.versions.manifest`, lần nạp `import` thành công gần nhất). MỌI logic truy vấn (lọc, sắp,
mốc mặc định, chuỗi điểm trang chi tiết, thống kê) dùng chung `EventStore._index` → web trả đúng như bản đọc CSV. Đọc
một lần lúc khởi động vào RAM (~20 nghìn sự kiện, vài giây) trong MỘT transaction REPEATABLE READ (thấy một trạng thái
nhất quán kể cả khi đang có lần nạp khác); DB đổi → API tự nạp lại nền (`apps/api/event_reload.py`).

- **Tên:** `events.display_name` đã áp luật ẩn tên lúc nạp (DB không chứa tên mô hình bị ẩn). Cửa sổ ẩn tên của API vẫn
  áp THÊM: sự kiện giao cửa sổ → tên = tiêu đề bài medoid (đặt cửa sổ rộng hơn lúc nạp vẫn an toàn; `off` không làm hiện
  lại tên đã ẩn vì DB không có).
- **Sự kiện** `status` merged/hidden (gộp, editor ẩn) không được phục vụ.
- **URL bài:** từ bảng `articles` (không cần Silver).
- **Bản đồ 2D:** vẫn là file `ban_do/` trong thư mục run gốc nếu có ở máy (`worker_runs.stats.run_dir`); không có thì
  không có ngày nào (trang hiển thị "chưa có bản đồ").
- **Số thực:** điểm lưu `real` (float4) → làm tròn như CSV (score 6 chữ số, vận tốc 4), lệch bản CSV ở chữ số thứ ~7.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

import psycopg

from eventrank.common import db
from eventrank.serving import store as ES

NO_DB_MESSAGE = ("Postgres chưa có sự kiện: áp migration (`make db-migrate`) rồi nạp một lần chạy pipeline "
                 "(`make db-import-run`), sau đó khởi động lại API.")
BACKENDS = ("files", "db")
CHANGE_STEPS = ("import", "recluster", "name", "trend")   # bước làm đổi dữ liệu web hiển thị


def _vn(dt: datetime | None) -> str | None:
    return dt.astimezone(ES.VN).isoformat() if dt else None


def _r(x: float | None, nd: int) -> float | None:
    return round(float(x), nd) if x is not None else None


class DbEventStore(ES.EventStore):
    """Tầng sự kiện trong Postgres, nạp vào RAM. Truy vấn: kế thừa nguyên `EventStore`."""

    def __init__(self, conn: psycopg.Connection, hide_window: tuple[datetime, datetime] | None,
                 default_min_sources: int | None = None, default_min_articles: int | None = None):
        t0 = time.perf_counter()
        with conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            if conn.execute("SELECT to_regclass('public.events') IS NULL").fetchone()[0]:
                raise ES.RunNotFound(NO_DB_MESSAGE)
            row = conn.execute("SELECT run_id, finished_at, versions, stats FROM worker_runs WHERE step = 'import' "
                               "AND status = 'ok' ORDER BY run_id DESC LIMIT 1").fetchone()
            if row is None or not conn.execute("SELECT EXISTS (SELECT 1 FROM events)").fetchone()[0]:
                raise ES.RunNotFound(NO_DB_MESSAGE)
            self.worker_run_id, self.imported_at, versions, stats = row
            manifest = versions.get("manifest")
            if not manifest:
                raise ES.RunNotFound("Lần nạp trong Postgres thiếu cấu hình run (bản db_import cũ) — nạp lại: "
                                     "`make db-import-run`, rồi khởi động lại API.")
            self.manifest: dict = manifest
            self.run_id = manifest.get("run_id") or versions.get("run_id") or f"db-{self.worker_run_id}"
            rd = stats.get("run_dir")                    # chỉ để đọc bản đồ ban_do/ nếu thư mục run còn ở máy
            self.run_dir = ES.ROOT / rd if rd else ES.ROOT / "data/runs" / self.run_id
            self.hide_window = hide_window
            if hide_window is None:
                ES.log.warning("DB: cửa sổ ẩn tên tắt — tên đã ẩn lúc nạp vẫn ẩn (DB không lưu tên mô hình bị ẩn)")
            self._load_events(conn)
            article_rows = self._load_articles(conn)
            trend_rows = self._load_trend(conn, versions.get("trend_version") or manifest.get("versions", {})
                                          .get("trend_version"))
            self.data_version = self.current_version(conn)
        self._extend_trend_grid(trend_rows)
        self._index(article_rows, trend_rows, default_min_sources, default_min_articles)
        self.load_seconds = round(time.perf_counter() - t0, 2)

    # ------------------------------------------------------------------ nạp
    @classmethod
    def from_env(cls) -> DbEventStore:
        """DATABASE_URL + EVENTS_HIDE_NAMES_WINDOW (như bản đọc file)."""
        window = ES.parse_hide_window(os.environ.get("EVENTS_HIDE_NAMES_WINDOW"))
        with db.connect() as conn:
            return cls(conn, window)

    @staticmethod
    def current_version(conn: psycopg.Connection) -> int | None:
        """run_id lớn nhất của các bước làm đổi dữ liệu hiển thị; khác `data_version` đang nạp → cần nạp lại."""
        return conn.execute("SELECT max(run_id) FROM worker_runs WHERE status = 'ok' AND step = ANY(%s)",
                            (list(CHANGE_STEPS),)).fetchone()[0]

    def _load_events(self, conn: psycopg.Connection) -> None:
        self.events: dict[str, ES.Event] = {}
        self.n_hidden_window = self.n_hidden_near = 0
        for (eid, name, source, name_hidden, size, n_sources, sources, first, last, medoid, total, peak, peak_at,
             top10) in conn.execute(
                "SELECT event_id, display_name, name_source, name_hidden, size, n_sources, sources, first_seen, "
                "last_seen, medoid_title, total_score, peak_score, peak_at, top10_hours FROM events "
                "WHERE status IN ('open', 'closed') ORDER BY first_seen, event_id"):
            first_s, last_s = _vn(first), _vn(last)
            in_win = self._in_window({"first_seen": first_s, "last_seen": last_s})
            hidden = bool(name_hidden) or in_win
            medoid = medoid or ""
            ten = (medoid or "(tên đang ẩn)") if hidden and not name_hidden else name
            if hidden:
                self.n_hidden_window += in_win
                self.n_hidden_near += not in_win
            self.events[eid] = ES.Event(
                event_id=eid, ten=ten, nguon_ten="an" if hidden else source, ten_bi_an=hidden, size=size,
                n_sources=n_sources, sources={str(k): int(v) for k, v in (sources or {}).items()},
                first_seen=first_s, last_seen=last_s, first_ts=first.timestamp(), last_ts=last.timestamp(),
                medoid_title=medoid, tong_diem=_r(total, 6), diem_cao_nhat=_r(peak, 6), luc_cao_nhat=_vn(peak_at),
                so_gio_trong_top10=int(top10 or 0), key=ES.fold(f"{ten} {medoid}"))

    def _load_articles(self, conn: psycopg.Connection) -> list[dict[str, Any]]:
        """Dòng bài cùng cột bai_su_kien.csv; URL giữ riêng cho trang chi tiết."""
        rows, self._url = [], {}
        for eid, aid, published, source, category, title, is_medoid, url in conn.execute(
                "SELECT ea.event_id, a.article_id, a.published_at, a.source, a.category, a.title, ea.is_medoid, a.url "
                "FROM event_articles ea JOIN articles a USING (article_id) JOIN events e USING (event_id) "
                "WHERE e.status IN ('open', 'closed') "
                "ORDER BY ea.event_id, a.published_at, a.article_id"):  # bài cùng giờ: thứ tự như bai_su_kien.csv
            rows.append({"event_id": eid, "article_id": aid, "published_at": _vn(published), "source": source,
                         "category": category, "title": title, "is_medoid": "1" if is_medoid else "0"})
            self._url[aid] = url
        return rows

    def _load_trend(self, conn: psycopg.Connection, trend_version: str | None) -> list[dict[str, Any]]:
        """Top-K mỗi mốc, cùng cột xu_huong.csv. tuoi_gio = giờ từ bài đầu của sự kiện tới t (như trending.score)."""
        top_k = int({**ES.trending.DEFAULTS, **(self.manifest.get("config", {}).get("trending") or {})}["top_k"])
        out = []
        for t, rank, eid, score, n, n3, n_src, n_eff, vel in conn.execute(
                "SELECT t, rank, event_id, score, n_articles, n_articles_3h, n_sources, n_sources_eff, velocity "
                "FROM trend_scores WHERE trend_version = %s AND rank <= %s ORDER BY t, rank", (trend_version, top_k)):
            e = self.events.get(eid)
            out.append({"t": _vn(t), "hang": rank, "event_id": eid, "score": round(score, 6), "so_bai_den_t": n,
                        "so_bai_3h": n3, "so_bao": n_src, "n_nguon_hd": round(n_eff, 4), "van_toc": round(vel, 4),
                        "tuoi_gio": round((t.timestamp() - e.first_ts) / 3600, 2) if e else 0.0})
        return out

    def _extend_trend_grid(self, trend_rows: list[dict[str, Any]]) -> None:
        """Worker thêm mốc giờ sau lần nạp run: kéo dài lưới mốc tới mốc mới nhất có trong DB."""
        if not trend_rows:
            return
        last = max(r["t"] for r in trend_rows)
        trend = self.manifest.setdefault("steps", {}).setdefault("trend", {})
        current = trend.get("end") or ES.trending.day(self.manifest.get("config", {}).get("trending", {}).get(
            "end", ES.trending.DEFAULTS["end"])).isoformat()
        if datetime.fromisoformat(last) > datetime.fromisoformat(current):
            trend["end"] = last

    # ------------------------------------------------------------------ khác bản đọc file
    def run_info(self) -> dict[str, Any]:
        info = super().run_info()
        at = _vn(self.imported_at)[:16].replace("T", " ")
        info["ghi_chu"] = [*info["ghi_chu"], f"Nguồn dữ liệu: Postgres (lần nạp #{self.worker_run_id}, {at})."]
        return info

    def get_event(self, event_id: str, urls=None) -> dict[str, Any] | None:
        """URL bài lấy từ bảng articles (bỏ qua `urls` của Silver)."""
        return super().get_event(event_id, urls=lambda ids: {i: self._url[i] for i in ids if self._url.get(i)})


def event_store_from_env() -> ES.EventStore:
    """`EVENTS_BACKEND` = files (mặc định: thư mục run) | db (Postgres, DATABASE_URL)."""
    backend = (os.environ.get("EVENTS_BACKEND") or "files").strip().lower()
    if backend not in BACKENDS:
        raise ES.RunNotFound(f"EVENTS_BACKEND={backend!r} không hợp lệ (chọn {' | '.join(BACKENDS)}).")
    if backend == "files":
        return ES.EventStore.from_env()
    try:
        return DbEventStore.from_env()
    except db.DatabaseConfigError as exc:                # thông báo không chứa URL/mật khẩu
        raise ES.RunNotFound(f"EVENTS_BACKEND=db: {exc}") from exc
    except psycopg.OperationalError as exc:              # chi tiết (host, cổng) chỉ ở log server
        raise ES.RunNotFound("EVENTS_BACKEND=db: không kết nối được Postgres (DATABASE_URL) — Postgres có đang "
                             "chạy không?") from exc
