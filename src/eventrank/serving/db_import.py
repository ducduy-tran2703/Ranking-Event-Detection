"""Nạp kết quả một lần chạy pipeline sự kiện (`data/runs/<run_id>/`) vào Postgres (migration 002_events.sql).

    uv run --group embed python -m eventrank.serving.db_import [RUN_DIR] [--replace] [--no-embeddings]
    make db-import-run [ARGS="data/runs/2026-11-03_v2 --replace"]

RUN_DIR mặc định = run đầy đủ mới nhất (`store.find_run_dir`, như API). Cần migration 002 đã áp và bài của run đã có
trong bảng `articles` (`python -m eventrank.ingest import`): bài thiếu → dừng, không ghi gì.

Ghi gì (một transaction cho cả tầng sự kiện; lỗi giữa chừng → rollback, không để DB nửa vời):
- `events`, `event_articles` (method = import), `event_assignment_log` (lần gán đầu, reason = import),
  `event_names` (một tên hiện hành mỗi sự kiện), `trend_scores` (MỌI ứng viên mỗi mốc, không chỉ top-K),
  `trend_baselines`, `category_map`; `worker_runs` một dòng step = import (versions gồm run_id nguồn).
- `article_embeddings` (transaction riêng, bỏ được bằng --no-embeddings): vector từ đệm của bước gom cụm
  (`<cache_dir>/emb_<model_version>.npz`), kèm content_hash hiện tại của bài.

**Ẩn tên:** sự kiện được dựng bằng `EventStore` — đúng luật API đang dùng (cửa sổ tập test đặt tên 14–15/09 + tên gần
trùng). Sự kiện bị ẩn chỉ có tên medoid trong DB; tên mô hình bị loại (`ten_mo_hinh`) KHÔNG được ghi cho sự kiện nào
(có thể gần trùng một tên bí mật). Không cho nạp khi cửa sổ = off: DB lưu lâu dài và đi qua mọi endpoint.

**Điểm xu hướng:** tính lại bằng `trending.score_at` cùng cấu hình + mức nền của run (như trang chi tiết), rồi đối chiếu
top-K mỗi mốc với `xu_huong.csv`: lệch → dừng (DB không được kể khác file của run).

**Nạp lại:** cùng run_id → thay toàn bộ tầng sự kiện (idempotent). Run khác → phải `--replace` (xoá tầng sự kiện cũ, kể
cả lịch sử gán; bảng nào khác trỏ vào `events` — bookmark, thông báo — sẽ chặn bằng khoá ngoại, đúng ý: khi đã có người
dùng thì không được thay cả lớp sự kiện, worker phải cập nhật tăng dần).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

from eventrank.common import db
from eventrank.serving import store as ES
from eventrank.trending import score as trending

CLOSED_AFTER = timedelta(hours=48)   # sự kiện không có bài mới quá 48h trước bài muộn nhất của run → closed
MANIFEST_KEYS = ("run_id", "created_at", "versions", "config", "range", "steps", "git")
EVENT_TABLES = ("trend_scores", "event_names", "event_assignment_log", "event_articles", "events")


class RunImportError(RuntimeError):
    """Run không nạp được (thiếu bài, lệch xu hướng, đã có run khác…). Thông báo không chứa URL DB."""


def _ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _copy(conn: psycopg.Connection, table: str, cols: list[str], types: list[str], rows: Iterable[tuple]) -> int:
    n = 0
    with conn.cursor() as cur, cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
        cp.set_types(types)
        for r in rows:
            cp.write_row(r)
            n += 1
    return n


def _current_run(conn: psycopg.Connection) -> str | None:
    """run_id nguồn của lần nạp thành công gần nhất (None nếu tầng sự kiện rỗng)."""
    if conn.execute("SELECT NOT EXISTS (SELECT 1 FROM events)").fetchone()[0]:
        return None
    row = conn.execute("SELECT versions->>'run_id' FROM worker_runs WHERE step = 'import' AND status = 'ok' "
                       "ORDER BY run_id DESC LIMIT 1").fetchone()
    return row[0] if row else "(không rõ)"


def _fallback_reasons(run_dir: Path, keep: set[str]) -> dict[str, str]:
    """event_id → lý do rơi về medoid / rút gọn tiêu đề, CHỈ cho sự kiện không bị ẩn. Không đọc cột ten_mo_hinh."""
    path = run_dir / "ten_su_kien.csv"
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["event_id"]: r["ly_do_fallback"] for r in csv.DictReader(f)
                if r["event_id"] in keep and r.get("ly_do_fallback")}


def trend_rows(es: ES.EventStore, arts: list[dict], log: Callable[[str], None] = print) -> list[dict]:
    """Điểm của MỌI ứng viên tại mỗi mốc của run; top-K phải khớp xu_huong.csv (es.trend)."""
    cfg, idx = es.cfg, trending.EventIndex(arts)
    out, bad = [], []
    for k in range(1, es.n_steps + 1):
        t = es._t(k)
        rows = trending.score_at(idx, t, cfg, es.baseline)
        ref = es.trend.get(k, [])
        top = [(r["event_id"], round(r["score"], 6)) for r in rows[:int(cfg["top_k"])]]
        if top != [(r["event_id"], round(r["score"], 6)) for r in ref]:
            bad.append(t.isoformat())
        out += [{"t": t, "rank": i, **r} for i, r in enumerate(rows, 1)]
    if bad:
        raise RunImportError(f"điểm xu hướng tính lại lệch xu_huong.csv ở {len(bad)} mốc (đầu tiên {bad[0]}) — "
                           "cấu hình/mức nền của run không tái lập được; chạy lại bước trend của run")
    log(f"xu hướng: {len(out)} dòng ứng viên trên {es.n_steps} mốc, top-K khớp xu_huong.csv")
    return out


def load_embeddings(path: Path, model_version: str) -> tuple[list[str], np.ndarray]:
    z = np.load(path, allow_pickle=True)
    if str(z["path"]) != model_version:
        raise RunImportError(f"{path.name}: đệm của mô hình {str(z['path'])!r}, không phải {model_version!r}")
    E = np.asarray(z["E"], dtype="<f4")
    norms = np.linalg.norm(E, axis=1)
    if len(E) and float(np.abs(norms - 1).max()) > 1e-3:
        raise RunImportError(f"{path.name}: vector chưa chuẩn hoá L2 (|‖v‖ − 1| tối đa {np.abs(norms - 1).max():.4f})")
    return [str(i) for i in z["ids"]], E


def import_run(conn: psycopg.Connection, run_dir: str | Path, *, replace: bool = False,
               hide_window: tuple[datetime, datetime] | None = None, embeddings: Path | None | bool = True,
               log: Callable[[str], None] = print) -> dict[str, Any]:
    """Nạp `run_dir` vào DB. `embeddings`: True = đệm mặc định của run, đường dẫn .npz, False/None = bỏ qua.
    Trả thống kê (cũng ghi vào worker_runs.stats)."""
    t0 = time.perf_counter()
    run_dir = Path(run_dir)
    hide_window = hide_window or ES.parse_hide_window(ES.DEFAULT_HIDE_WINDOW)   # None = mặc định, không bao giờ tắt
    es = ES.EventStore(run_dir, hide_window)
    versions = {**es.manifest.get("versions", {}), "run_id": es.run_id, "git": es.manifest.get("git"),
                # cấu hình để API dựng lại đúng lưới mốc/tham số (serving.db_store); KHÔNG chép xu_huong_moi_nhat (có tên)
                "manifest": {k: es.manifest[k] for k in MANIFEST_KEYS if k in es.manifest}}
    for k in ("algo_version", "model_version", "trend_version"):
        if not versions.get(k):
            raise RunImportError(f"manifest.json của {run_dir.name} thiếu versions.{k}")

    # bài của run phải có sẵn trong articles (khoá ngoại); báo số thiếu thay cho lỗi FK khó đọc
    aids = [a["article_id"] for xs in es.articles.values() for a in xs]
    missing = conn.execute("SELECT count(*) FROM unnest(%s::text[]) AS x(id) "
                           "WHERE NOT EXISTS (SELECT 1 FROM articles WHERE article_id = x.id)", (aids,)).fetchone()[0]
    if missing:
        raise RunImportError(f"{missing}/{len(aids)} bài của run chưa có trong bảng articles — nạp Silver vào DB trước "
                           "(python -m eventrank.ingest import)")
    cur_run = _current_run(conn)
    if cur_run not in (None, es.run_id) and not replace:
        raise RunImportError(f"DB đang chứa sự kiện của run {cur_run}; thêm --replace để thay bằng {es.run_id}")

    # vector (nếu có): để tính similarity lúc gán và ghi article_embeddings
    emb_path = None
    if embeddings is True:
        cache_dir = ES.ROOT / ((es.manifest.get("config", {}).get("clustering") or {}).get("cache_dir")
                               or "data/events/cache")
        emb_path = cache_dir / f"emb_{versions['model_version']}.npz"
        if not emb_path.is_file():
            log(f"không có đệm vector {ES.rel_label(emb_path)} — bỏ qua article_embeddings và similarity")
            emb_path = None
    elif embeddings:
        emb_path = Path(embeddings)
    vec: dict[str, np.ndarray] = {}
    if emb_path:
        ids, E = load_embeddings(emb_path, versions["model_version"])
        vec = dict(zip(ids, E, strict=True))

    arts = [{"event_id": eid, "ts": a["ts"], "source": a["source"], "title": a["title"]}
            for eid, xs in es.articles.items() for a in xs]
    trend = trend_rows(es, arts, log)
    data_end = max(a["ts"] for a in arts)
    run_id = conn.execute("INSERT INTO worker_runs (step, app_now, versions) VALUES ('import', app_now(), %s) "
                          "RETURNING run_id", (json.dumps(versions, ensure_ascii=False),)).fetchone()[0]
    stats: dict[str, Any] = {"run_dir": ES.rel_label(run_dir)}
    try:
        with conn.transaction():
            if cur_run is not None:
                # DELETE theo thứ tự con → cha: FK từ bảng bookmark/thông báo RỖNG không chặn
                # nạp lại (TRUNCATE vẫn chặn). Có dòng tham chiếu → lỗi FK, rollback toàn bộ;
                # không CASCADE, không xoá dữ liệu người dùng. Tên bảng là hằng số nội bộ.
                for table in EVENT_TABLES:
                    conn.execute(f"DELETE FROM {table}")
                conn.execute("DELETE FROM trend_baselines WHERE trend_version = %s", (versions["trend_version"],))
            stats.update(_write_events(conn, es, versions, vec, data_end, run_id, run_dir))
            stats["trend_scores"] = _copy(
                conn, "trend_scores",
                ["trend_version", "t", "event_id", "score", "rank", "n_articles", "n_articles_3h", "n_sources",
                 "n_sources_eff", "velocity"],
                ["text", "timestamptz", "text", "float4", "int4", "int4", "int4", "int2", "float4", "float4"],
                ((versions["trend_version"], r["t"], r["event_id"], r["score"], r["rank"], r["so_bai_den_t"],
                  r["so_bai_3h"], r["so_bao"], r["n_nguon_hd"], r["van_toc"]) for r in trend))
            lo, hi = trending.day(es.cfg["baseline_start"]).date(), trending.day(es.cfg["baseline_end"]).date()
            stats["trend_baselines"] = _copy(
                conn, "trend_baselines", ["trend_version", "hour_of_day", "value", "computed_from", "computed_to"],
                ["text", "int2", "float4", "date", "date"],
                ((versions["trend_version"], h, v, lo, hi) for h, v in enumerate(es.baseline)))
            stats["category_map"] = _sync_category_map(conn)
        if vec:
            stats["article_embeddings"] = write_embeddings(conn, versions["model_version"], vec)
    except Exception as e:
        conn.execute("UPDATE worker_runs SET status = 'failed', finished_at = now(), error = %s WHERE run_id = %s",
                     (f"{e.__class__.__name__}: {e}"[:2000], run_id))
        raise
    stats["seconds"] = round(time.perf_counter() - t0, 1)
    conn.execute("UPDATE worker_runs SET status = 'ok', finished_at = now(), stats = %s WHERE run_id = %s",
                 (json.dumps(stats, ensure_ascii=False), run_id))
    stats["worker_run_id"] = run_id
    return stats


def _write_events(conn: psycopg.Connection, es: ES.EventStore, versions: dict, vec: dict[str, np.ndarray],
                  data_end: float, run_id: int, run_dir: Path) -> dict[str, int]:
    medoid = {eid: next((a["article_id"] for a in xs if a["is_medoid"]), None) for eid, xs in es.articles.items()}
    n_events = _copy(
        conn, "events",
        ["event_id", "status", "first_seen", "last_seen", "size", "n_sources", "sources", "medoid_article_id",
         "medoid_title", "display_name", "name_source", "name_hidden", "category_std", "peak_score", "peak_at",
         "total_score", "top10_hours", "algo_version", "model_version", "trend_version"],
        ["text", "text", "timestamptz", "timestamptz", "int4", "int4", "jsonb", "text", "text", "text", "text",
         "bool", "text", "float4", "timestamptz", "float4", "float4", "text", "text", "text"],
        ((e.event_id, "closed" if data_end - e.last_ts > CLOSED_AFTER.total_seconds() else "open",
          _ts(e.first_seen), _ts(e.last_seen), e.size, e.n_sources, Jsonb(e.sources),
          medoid.get(e.event_id), e.medoid_title or None, e.ten, "medoid" if e.ten_bi_an else e.nguon_ten,
          e.ten_bi_an, e.chuyen_muc, e.diem_cao_nhat, _ts(e.luc_cao_nhat), e.tong_diem,
          float(e.so_gio_trong_top10) if e.tong_diem is not None else None, versions["algo_version"],
          versions["model_version"], versions["trend_version"]) for e in es.events.values()))

    def similarity(eid: str, aid: str) -> float | None:
        xs = es.articles[eid]
        if len(xs) < 2 or aid not in vec:
            return None
        others = [vec[a["article_id"]] for a in xs if a["article_id"] != aid and a["article_id"] in vec]
        return float(np.mean(np.stack(others) @ vec[aid])) if others else None

    members = [(eid, a) for eid, xs in es.articles.items() for a in xs]
    n_arts = _copy(conn, "event_articles", ["article_id", "event_id", "method", "similarity", "is_medoid"],
                   ["text", "text", "text", "float4", "bool"],
                   ((a["article_id"], eid, "import", similarity(eid, a["article_id"]), a["is_medoid"])
                    for eid, a in members))
    n_log = _copy(conn, "event_assignment_log", ["article_id", "to_event", "reason", "worker_run_id"],
                  ["text", "text", "text", "int8"],
                  ((a["article_id"], eid, "import", run_id) for eid, a in members))
    reasons = _fallback_reasons(run_dir, {e.event_id for e in es.events.values() if not e.ten_bi_an})
    naming_version = versions.get("naming_version")
    n_names = _copy(
        conn, "event_names", ["event_id", "name", "source", "naming_version", "size_at_naming", "checks"],
        ["text", "text", "text", "text", "int4", "jsonb"],
        ((e.event_id, e.ten, "medoid" if e.ten_bi_an else e.nguon_ten,
          None if e.ten_bi_an else naming_version, e.size,
          Jsonb({"an_ten": True} if e.ten_bi_an else
                ({"ly_do_fallback": reasons[e.event_id]} if e.event_id in reasons else {})))
         for e in es.events.values()))
    return {"events": n_events, "events_hidden_name": sum(e.ten_bi_an for e in es.events.values()),
            "event_articles": n_arts, "event_assignment_log": n_log, "event_names": n_names}


def _sync_category_map(conn: psycopg.Connection) -> int:
    pairs = conn.execute("SELECT DISTINCT source, category FROM articles WHERE category <> ''").fetchall()
    rows = [(s, c, ES.norm_category(c)) for s, c in pairs if ES.norm_category(c)]
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO category_map (source, category_raw, category_std) VALUES (%s, %s, %s) "
                        "ON CONFLICT (source, category_raw) DO UPDATE SET category_std = EXCLUDED.category_std, "
                        "updated_at = now() WHERE category_map.category_std <> EXCLUDED.category_std", rows)
    return len(rows)


def write_embeddings(conn: psycopg.Connection, model_version: str, vec: dict[str, np.ndarray]) -> int:
    """Thay vector của `model_version` cho các bài có trong DB (kèm content_hash hiện tại). Trả số vector đã ghi."""
    hashes = dict(conn.execute("SELECT article_id, content_hash FROM articles WHERE article_id = ANY(%s)",
                               (list(vec),)).fetchall())
    with conn.transaction():
        conn.execute("DELETE FROM article_embeddings WHERE model_version = %s AND article_id = ANY(%s)",
                     (model_version, list(hashes)))
        return _copy(conn, "article_embeddings", ["article_id", "model_version", "content_hash", "dim", "vec"],
                     ["text", "text", "text", "int2", "bytea"],
                     ((aid, model_version, h, len(vec[aid]), np.asarray(vec[aid], dtype="<f4").tobytes())
                      for aid, h in hashes.items()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eventrank.serving.db_import",
                                 description="Nạp một lần chạy pipeline sự kiện (data/runs/<run_id>/) vào Postgres")
    ap.add_argument("run_dir", nargs="?", help="mặc định: run đầy đủ mới nhất trong data/runs/")
    ap.add_argument("--replace", action="store_true", help="thay tầng sự kiện của một run KHÁC đang có trong DB")
    ap.add_argument("--no-embeddings", action="store_true", help="không ghi article_embeddings")
    ap.add_argument("--db-env", default="DATABASE_URL",
                    help="TÊN biến môi trường chứa URL (không truyền URL trên dòng lệnh)")
    a = ap.parse_args(argv)
    run_dir = Path(a.run_dir) if a.run_dir else ES.find_run_dir()
    if run_dir is None:
        print(f"LỖI: {ES.NO_RUN_MESSAGE}", file=sys.stderr)
        return 1
    run_dir = run_dir if run_dir.is_absolute() else ES.ROOT / run_dir
    raw_window = os.environ.get("EVENTS_HIDE_NAMES_WINDOW", "")
    try:
        if raw_window.strip().lower() == ES.HIDE_OFF:
            raise RunImportError("EVENTS_HIDE_NAMES_WINDOW=off: không nạp khi tắt ẩn tên — tên mô hình của cửa sổ "
                                 "tập test sẽ nằm lâu dài trong DB")
        with db.connect(env=a.db_env) as conn:
            pending = [r["name"] for r in db.status(conn) if r["state"] != "applied"]
            if pending:
                raise RunImportError(f"migration chưa áp: {', '.join(pending)} — chạy `make db-migrate` trước")
            stats = import_run(conn, run_dir, replace=a.replace, embeddings=not a.no_embeddings,
                               hide_window=ES.parse_hide_window(raw_window))
    except (db.DatabaseConfigError, RunImportError, ES.RunNotFound, ES.HideWindowError) as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 1
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
