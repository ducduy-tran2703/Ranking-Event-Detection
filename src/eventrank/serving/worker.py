"""Worker chạy liên tục: bài mới trong Postgres → embedding → gom lại + giữ event_id → đặt tên → xu hướng.

    uv run --group embed --with pyvi python -m eventrank.serving.worker --once
    uv run --group embed --with pyvi python -m eventrank.serving.worker --loop     (make worker)

Mỗi vòng làm theo TRẠNG THÁI trong DB (không nhớ gì trong RAM), nên chết giữa chừng thì vòng sau làm tiếp:
- `embed`: bài trong `pending_max_age_days` chưa có vector của content_hash hiện tại.
- `recluster`: chỉ chạy khi có bài chưa thuộc sự kiện nào. Gom agglo (configs/clustering.yaml) trên cửa sổ quanh bài mới,
  rồi `reconcile` khớp cụm với sự kiện cũ để `event_id` ổn định (bookmark, theo dõi, thông báo trỏ vào nó).
- `name`: sự kiện chưa có tên, vừa từ 1 lên ≥ 2 bài, hoặc lớn thêm ≥ `rename_growth` lần. Tên editor không bị đổi.
- `trend`: tính lại các mốc giờ gần nhất (bài có thể đến muộn hơn giờ đăng, cụm có thể đổi).

Khác thiết kế mục 9.1:
- KHÔNG có tầng "gán nhanh từng bài". Crawler chạy 30 phút một lần nên bài đến theo lô, gom lại cửa sổ chỉ mất vài giây → một
  tầng đối chiếu là đủ, không phải giữ hai đường gán.
- Mặc định KHÔNG khoá "cụm ≥ 3 bài chỉ lớn thêm" (`lock_min_size` rỗng): khoá làm B-Cubed F1 tụt (phát lại 14–15/09, 30 phút/nhịp,
  ngày 14/09: khoá ≥ 3 bài 0,949; ≥ 5 bài 0,957; không khoá 0,961). Đổi lại nhiều bài đổi sự kiện hơn (298 so với 73 lượt).
  Số trên tập test và cạm bẫy: docs/handoff/worker.md.

"Bây giờ" luôn lấy từ `app_now()`: cùng code chạy được với bài thật và với phát lại (`make ingest-replay`).
Tên mô hình KHÔNG được sinh cho sự kiện giao cửa sổ tập test đặt tên (EVENTS_HIDE_NAMES_WINDOW), như `db_import`.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import logging
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import yaml
from psycopg.types.json import Jsonb

from eventrank.clustering import pipeline as clustering
from eventrank.common import db
from eventrank.embeddings.encode import encode, head_text
from eventrank.ingest import clock
from eventrank.naming import predict as naming
from eventrank.naming.dataset import _PREFIX
from eventrank.serving import store as ES
from eventrank.serving.db_import import _copy, write_embeddings
from eventrank.trending import score as trending

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "configs/pipeline.yaml"
WORKER_DEFAULTS = {"interval_seconds": 300, "pending_max_age_days": 7, "lock_min_size": None, "min_lock_jaccard": 0.0,
                   "rename_growth": 1.5,
                   "rescore_hours": 6, "backfill_hours": 48, "closed_after_hours": 48}
_LOCK_KEY = 0x6576656E74776B72   # "eventwkr": chỉ một worker trên mỗi DB
HOUR = timedelta(hours=1)
NO_LOCK = 10**9                  # lock_min_size rỗng: không sự kiện nào đủ lớn để bị khoá


class WorkerError(RuntimeError):
    """Không chạy được worker (cấu hình, migration, đã có worker khác). Thông báo không chứa URL DB."""


@dataclass
class WorkerConfig:
    cluster: dict[str, Any]
    naming: dict[str, Any]
    trending: dict[str, Any]
    worker: dict[str, Any] = field(default_factory=lambda: dict(WORKER_DEFAULTS))
    hide_window: tuple[datetime, datetime] | None = None

    @property
    def versions(self) -> dict[str, str]:
        return {"algo_version": self.cluster["algo_version"], "model_version": self.cluster["model_version"],
                "naming_version": self.naming["naming_version"], "trend_version": self.trending["trend_version"]}


def load_config(path: str | Path = CONFIG) -> WorkerConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cluster_cfg = raw.get("clustering", {}).get("config") or "configs/clustering.yaml"
    raw_window = os.environ.get("EVENTS_HIDE_NAMES_WINDOW", "")
    if raw_window.strip().lower() == ES.HIDE_OFF:
        raise WorkerError("EVENTS_HIDE_NAMES_WINDOW=off: worker không chạy khi tắt ẩn tên tập test")
    return WorkerConfig(cluster=clustering.load_config(ROOT / cluster_cfg), naming=naming.load_config(path),
                        trending=trending.load_config(path), worker={**WORKER_DEFAULTS, **(raw.get("worker") or {})},
                        hide_window=ES.parse_hide_window(raw_window))


@contextmanager
def _step(conn: psycopg.Connection, name: str, cfg: WorkerConfig, now: datetime):
    """Một dòng `worker_runs` cho bước `name`; lỗi được ghi lại rồi ném tiếp."""
    run_id = conn.execute("INSERT INTO worker_runs (step, app_now, versions) VALUES (%s, %s, %s) RETURNING run_id",
                          (name, now, Jsonb(cfg.versions))).fetchone()[0]
    stats: dict[str, Any] = {}
    t0 = time.perf_counter()
    try:
        yield run_id, stats
    except Exception as e:
        conn.execute("UPDATE worker_runs SET status = 'failed', finished_at = now(), error = %s WHERE run_id = %s",
                     (f"{e.__class__.__name__}: {e}"[:2000], run_id))
        raise
    stats["seconds"] = round(time.perf_counter() - t0, 2)
    conn.execute("UPDATE worker_runs SET status = 'ok', finished_at = now(), stats = %s WHERE run_id = %s",
                 (Jsonb(stats), run_id))


# ---------------------------------------------------------------------- embedding
def embed_pending(conn: psycopg.Connection, cfg: WorkerConfig, now: datetime, encoder=None,
                  logf: Callable[[str], None] = print) -> int:
    """Encode bài trong khoảng chờ chưa có vector của content_hash hiện tại (bài bị sửa thì encode lại)."""
    mv = cfg.cluster["model_version"]
    rows = conn.execute(
        "SELECT a.article_id, a.title, a.sapo FROM articles a LEFT JOIN article_embeddings e "
        "ON e.article_id = a.article_id AND e.model_version = %s AND e.content_hash = a.content_hash "
        "WHERE e.article_id IS NULL AND a.published_at BETWEEN %s AND %s",
        (mv, now - timedelta(days=cfg.worker["pending_max_age_days"]), now)).fetchall()
    if not rows:
        return 0
    with _step(conn, "embed", cfg, now) as (_, stats):
        model = ROOT / cfg.cluster["model"]
        vec = encode({aid: head_text(clustering._clean(t), clustering._clean(s)) for aid, t, s in rows},
                     str(model) if model.exists() else cfg.cluster["model"], cfg.cluster["prep"],
                     encoder=encoder, log=logf)
        stats["n_articles"] = write_embeddings(conn, mv, vec)
    return len(rows)


# ---------------------------------------------------------------------- đối chiếu event_id
@dataclass
class Plan:
    assign: dict[str, tuple[str, str]] = field(default_factory=dict)  # article_id → (event_id mới, lý do)
    new_events: dict[str, str] = field(default_factory=dict)          # event_id mới → article_id bài đầu
    merges: dict[str, str] = field(default_factory=dict)              # sự kiện bị gộp → sự kiện nhận


def _new_id(members: list[str], day_of: Callable[[str], str], taken: set[str]) -> tuple[str, str]:
    """E<ngày bài đầu>-<8 ký tự article_id>; trùng id đã có (kể cả sự kiện đã gộp) thì thử bài tiếp theo của cụm, hết bài
    thì băm article_id kèm số đếm: vẫn đúng định dạng và xác định được từ dữ liệu."""
    for aid in members:
        eid = f"E{day_of(aid)}-{aid[:8]}"
        if eid not in taken:
            return eid, aid
    first = members[0]
    for n in itertools.count(1):
        eid = f"E{day_of(first)}-{hashlib.sha256(f'{first}:{n}'.encode()).hexdigest()[:8]}"
        if eid not in taken:
            return eid, first
    raise AssertionError("unreachable")


def reconcile(ids: list[str], labels: Iterable[int], prev: dict[str, str], sizes: dict[str, int],
              day_of: Callable[[str], str], lock_min_size: int = 3, taken_ids: Iterable[str] = (),
              min_lock_jaccard: float = 0.0) -> Plan:
    """Khớp cụm mới với sự kiện cũ. `ids` theo thứ tự thời gian; `prev`: article_id → event_id hiện tại (bài trong cửa
    sổ); `sizes`: event_id → tổng số bài (kể cả bài ngoài cửa sổ).

    - Sự kiện ≥ `lock_min_size` bài bị KHOÁ: chỉ lớn thêm, bài của nó không bị chuyển đi (trừ khi cả sự kiện bị gộp).
    - Cụm trùng sự kiện khoá với Jaccard ≥ `min_lock_jaccard` → nhận sự kiện khoá trùng nhiều bài nhất. Chỉ chạm vài bài
      thì KHÔNG nhập: bài đã khoá ở lại sự kiện của nó, phần còn lại xét như cụm thường. Cụm còn lại khớp sự kiện nhỏ
      theo Jaccard lớn nhất, một-một. Không khớp được → sự kiện mới.
    - Một sự kiện khoá khác nằm TRỌN trong cụm → gộp vào sự kiện được chọn (status = merged, không xoá).
    - Sự kiện nhỏ bị rút hết bài → đánh dấu gộp vào nơi nhận nhiều bài của nó nhất.
    """
    clusters: dict[int, list[str]] = {}
    for aid, lab in zip(ids, labels, strict=True):
        clusters.setdefault(int(lab), []).append(aid)
    in_window = Counter(prev.values())
    locked = {e for e in in_window if sizes[e] >= lock_min_size}
    target: dict[int, str] = {}
    overlaps: dict[int, Counter] = {}
    pairs = []
    for c, members in clusters.items():
        count = Counter(prev[a] for a in members if a in prev)
        overlaps[c] = count
        jaccard = {e: n / (len(members) + in_window[e] - n) for e, n in count.items()}
        hit = [e for e in count if e in locked and jaccard[e] >= min_lock_jaccard]
        if hit:
            target[c] = min(hit, key=lambda e: (-count[e], -sizes[e], e))
            continue
        pairs += [(-jaccard[e], -len(members), members[0], c, e) for e in count if e not in locked]
    used: set[str] = set()
    for _, _, _, c, e in sorted(pairs):                       # Jaccard giảm dần; hoà → cụm lớn hơn, cụm sớm hơn
        if c not in target and e not in used:
            target[c] = e
            used.add(e)

    plan = Plan()
    taken = set(taken_ids) | set(sizes)
    for c in sorted(clusters, key=lambda c: clusters[c][0]):
        movable = [a for a in clusters[c] if prev.get(a) not in locked]
        if c not in target and movable:                       # toàn bài đã khoá → không cần sự kiện nào cả
            target[c], first = _new_id(movable, day_of, taken)
            taken.add(target[c])
            plan.new_events[target[c]] = first
    for c, members in clusters.items():
        goal = target.get(c)
        if goal is None:
            continue
        for e in overlaps[c]:
            if e in locked and e != goal and sizes[e] == overlaps[c][e]:
                plan.merges[e] = goal
        for a in members:
            old = prev.get(a)
            if old == goal:
                continue
            if old in plan.merges:
                plan.assign[a] = (goal, "merge")
            elif old not in locked:
                plan.assign[a] = (goal, "recluster")

    goals = set(target.values())
    moved_out = Counter(prev[a] for a, _ in ((a, g) for a, g in plan.assign.items()) if a in prev)
    for e, n in in_window.items():
        if e in goals or e in plan.merges or n != sizes[e] or moved_out[e] != n:
            continue
        where = Counter(plan.assign[a][0] for a in prev if prev[a] == e)
        plan.merges[e] = min(where, key=lambda g: (-where[g], g))
    return plan


def _vn_day(ts: datetime) -> str:
    return ts.astimezone(ES.VN).strftime("%Y%m%d")


def recluster(conn: psycopg.Connection, cfg: WorkerConfig, now: datetime, logf: Callable[[str], None] = print) -> int:
    """Trả số bài mới đã gán. Không có bài chờ → không làm gì (sự kiện cũ không bị xáo trộn vô cớ)."""
    mv = cfg.cluster["model_version"]
    window = timedelta(hours=cfg.cluster["window_hours"])
    oldest = conn.execute(
        "SELECT min(a.published_at), count(*) FROM articles a "
        "JOIN article_embeddings v ON v.article_id = a.article_id AND v.model_version = %s "
        "AND v.content_hash = a.content_hash LEFT JOIN event_articles ea ON ea.article_id = a.article_id "
        "WHERE ea.article_id IS NULL AND a.published_at BETWEEN %s AND %s",
        (mv, now - timedelta(days=cfg.worker["pending_max_age_days"]), now)).fetchone()
    if not oldest[1]:
        return 0
    low = min(now - window, oldest[0] - window)
    rows = conn.execute(
        "SELECT a.article_id, a.published_at, v.vec, ea.event_id FROM articles a "
        "JOIN article_embeddings v ON v.article_id = a.article_id AND v.model_version = %s "
        "AND v.content_hash = a.content_hash LEFT JOIN event_articles ea ON ea.article_id = a.article_id "
        "WHERE a.published_at BETWEEN %s AND %s ORDER BY a.published_at, a.article_id", (mv, low, now)).fetchall()
    ids = [r[0] for r in rows]
    published = {r[0]: r[1] for r in rows}
    E = np.stack([np.frombuffer(r[2], dtype="<f4") for r in rows])
    times = np.array([r[1].timestamp() for r in rows])
    labels, _ = clustering.cluster(E, times, cfg.cluster)
    prev = {r[0]: r[3] for r in rows if r[3]}
    sizes = dict(conn.execute("SELECT event_id, size FROM events WHERE event_id = ANY(%s)",
                              (list(set(prev.values())),)).fetchall())
    day_of = lambda aid: _vn_day(published[aid])
    # Mọi id từ ngày đầu cửa sổ trở đi (gồm id dự phòng và sự kiện đã gộp): event_id mở đầu bằng ngày YYYYMMDD.
    taken = {r[0] for r in conn.execute("SELECT event_id FROM events WHERE substring(event_id, 2, 8) >= %s",
                                        (_vn_day(low),)).fetchall()}
    plan = reconcile(ids, labels, prev, sizes, day_of, cfg.worker["lock_min_size"] or NO_LOCK, taken,
                     cfg.worker["min_lock_jaccard"])
    with _step(conn, "recluster", cfg, now) as (run_id, stats), conn.transaction():
        _apply(conn, cfg, plan, prev, published, run_id, now)
        stats.update(n_window=len(ids), n_new_articles=int(oldest[1]), n_new_events=len(plan.new_events),
                     n_moved=sum(a in prev for a in plan.assign), n_merged=len(plan.merges))
    logf(f"gom lại {len(ids)} bài: {oldest[1]} bài mới, {len(plan.new_events)} sự kiện mới, "
         f"{sum(a in prev for a in plan.assign)} bài đổi sự kiện, gộp {len(plan.merges)} sự kiện")
    return int(oldest[1])


def _apply(conn: psycopg.Connection, cfg: WorkerConfig, plan: Plan, prev: dict[str, str],
           published: dict[str, datetime], run_id: int, now: datetime) -> None:
    v = cfg.versions
    titles = dict(conn.execute("SELECT article_id, title FROM articles WHERE article_id = ANY(%s)",
                               (list(plan.new_events.values()),)).fetchall())
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO events (event_id, first_seen, last_seen, size, n_sources, medoid_title, display_name, "
            "name_source, algo_version, model_version, trend_version) "
            "VALUES (%s, %s, %s, 1, 1, %s, %s, 'title', %s, %s, %s)",
            [(eid, published[a], published[a], titles[a], titles[a], v["algo_version"], v["model_version"],
              v["trend_version"]) for eid, a in plan.new_events.items()])
        touched = {g for g, _ in plan.assign.values()} | {prev[a] for a in plan.assign if a in prev}
        conn.execute("UPDATE event_articles SET is_medoid = false WHERE event_id = ANY(%s) AND is_medoid",
                     (list(touched),))
        cur.executemany(
            "INSERT INTO event_articles (article_id, event_id, method) VALUES (%s, %s, 'recluster') "
            "ON CONFLICT (article_id) DO UPDATE SET event_id = EXCLUDED.event_id, method = 'recluster', "
            "assigned_at = now()", [(a, g) for a, (g, _) in plan.assign.items()])
        cur.executemany(
            "INSERT INTO event_assignment_log (article_id, from_event, to_event, reason, worker_run_id) "
            "VALUES (%s, %s, %s, %s, %s)", [(a, prev.get(a), g, r, run_id) for a, (g, r) in plan.assign.items()])
    _apply_merges(conn, plan.merges)
    _refresh(conn, cfg, touched - set(plan.merges), now)


def _final(merges: dict[str, str], e: str) -> str:
    seen = set()
    while e in merges and e not in seen:
        seen.add(e)
        e = merges[e]
    return e


def _apply_merges(conn: psycopg.Connection, merges: dict[str, str]) -> None:
    """Đánh dấu gộp (không xoá) và chuyển bookmark/theo dõi sang sự kiện nhận; người đã lưu cả hai thì giữ dòng cũ."""
    for loser in merges:
        winner = _final(merges, loser)
        conn.execute("UPDATE events SET merged_into = %s WHERE merged_into = %s", (winner, loser))
        conn.execute("UPDATE events SET status = 'merged', merged_into = %s, updated_at = now() WHERE event_id = %s",
                     (winner, loser))
        conn.execute("DELETE FROM trend_scores WHERE event_id = %s", (loser,))
        for table in ("event_bookmarks", "event_follows"):
            conn.execute(f"UPDATE {table} t SET event_id = %s WHERE t.event_id = %s AND NOT EXISTS "
                         f"(SELECT 1 FROM {table} o WHERE o.user_id = t.user_id AND o.event_id = %s)",
                         (winner, loser, winner))


def _refresh(conn: psycopg.Connection, cfg: WorkerConfig, event_ids: set[str], now: datetime) -> None:
    """Tính lại số liệu tổng hợp, medoid, độ tương đồng của các sự kiện vừa đổi thành viên."""
    if not event_ids:
        return
    rows = conn.execute(
        "SELECT ea.event_id, a.article_id, a.published_at, a.source, a.category, a.title, v.vec "
        "FROM event_articles ea JOIN articles a ON a.article_id = ea.article_id "
        "LEFT JOIN article_embeddings v ON v.article_id = a.article_id AND v.model_version = %s "
        "WHERE ea.event_id = ANY(%s) ORDER BY ea.event_id, a.published_at, a.article_id",
        (cfg.cluster["model_version"], list(event_ids))).fetchall()
    grouped: dict[str, list[tuple]] = {}
    for r in rows:
        grouped.setdefault(r[0], []).append(r)
    closed_after = timedelta(hours=cfg.worker["closed_after_hours"])
    events, members = [], []
    for eid, xs in grouped.items():
        with_vec = [i for i, x in enumerate(xs) if x[6] is not None]
        medoid, sims = 0, {}
        if len(with_vec) > 1:
            X = np.stack([np.frombuffer(xs[i][6], dtype="<f4") for i in with_vec])
            avg = ((X @ X.T).sum(1) - 1) / (len(with_vec) - 1)
            medoid = with_vec[int(np.argmax(avg))]            # argmax lấy chỉ số đầu → hoà thì bài sớm hơn
            sims = {with_vec[k]: float(avg[k]) for k in range(len(with_vec))}
        counts = Counter(x[3] for x in xs)
        cats = Counter(c for c in (ES.norm_category(x[4]) for x in xs) if c)
        last = xs[-1][2]
        events.append((xs[0][2], last, len(xs), len(counts), Jsonb(dict(counts)), xs[medoid][1], xs[medoid][5],
                       min(cats.items(), key=lambda kv: (-kv[1], kv[0]))[0] if cats else None,
                       "closed" if now - last > closed_after else "open", eid))
        members += [(sims.get(i), i == medoid, x[1]) for i, x in enumerate(xs)]
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE events SET first_seen = %s, last_seen = %s, size = %s, n_sources = %s, sources = %s, "
            "medoid_article_id = %s, medoid_title = %s, category_std = %s, "
            "status = CASE WHEN status IN ('open', 'closed') THEN %s ELSE status END, updated_at = now() "
            "WHERE event_id = %s", events)
        cur.executemany("UPDATE event_articles SET similarity = %s, is_medoid = %s WHERE article_id = %s", members)


# ---------------------------------------------------------------------- đặt tên
def _needs_name(conn: psycopg.Connection, growth: float) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT e.event_id FROM events e LEFT JOIN event_names n ON n.event_id = e.event_id AND n.is_current "
        "WHERE e.status IN ('open', 'closed') AND (n.event_id IS NULL OR (n.source <> 'editor' AND NOT e.name_hidden "
        "AND e.size >= 2 AND (n.size_at_naming < 2 OR e.size >= n.size_at_naming * %s)))", (growth,)).fetchall()]


def name_events(conn: psycopg.Connection, cfg: WorkerConfig, now: datetime, generator=None,
                logf: Callable[[str], None] = print) -> int:
    event_ids = _needs_name(conn, cfg.worker["rename_growth"])
    if not event_ids:
        return 0
    grouped: dict[str, list[tuple]] = {}
    for r in conn.execute(
            "SELECT ea.event_id, a.article_id, a.published_at, a.source, a.title, a.sapo, ea.is_medoid "
            "FROM event_articles ea JOIN articles a ON a.article_id = ea.article_id WHERE ea.event_id = ANY(%s) "
            "ORDER BY ea.event_id, a.published_at, a.article_id", (event_ids,)):
        grouped.setdefault(r[0], []).append(r)
    jobs, hidden = [], []
    for eid, xs in grouped.items():
        if cfg.hide_window and xs[0][2] < cfg.hide_window[1] and xs[-1][2] >= cfg.hide_window[0]:
            hidden.append((eid, next((x[4] for x in xs if x[6]), xs[0][4]), len(xs)))
            continue
        first, last = xs[0][2].astimezone(ES.VN).isoformat(), xs[-1][2].astimezone(ES.VN).isoformat()
        jobs.append({"event_id": eid, "size": len(xs), "n_sources": len({x[3] for x in xs}), "first_seen": first,
                     "last_seen": last,
                     "articles": [{"id": x[1], "t": x[2].astimezone(ES.VN).isoformat(), "source": x[3],
                                   "title": _PREFIX.sub("", clustering._clean(x[4])), "sapo": clustering._clean(x[5]),
                                   "medoid": bool(x[6])} for x in xs]})
    with _step(conn, "name", cfg, now) as (_, stats):
        cache = naming._path(cfg.naming["cache_dir"]) / f"{cfg.naming['naming_version']}.jsonl"
        prepared = naming.prepare(jobs, cfg.naming)
        rows, info = naming.name_jobs(prepared, cfg.naming, generator, cache, logf) if prepared else ([], {})
        src = {j["event_id"]: naming.src_hash(j["src"]) for j in prepared}
        with conn.transaction():
            for r in rows:
                checks = {k: r[k] for k in ("ly_do_fallback", "ten_mo_hinh") if r[k]}
                _write_name(conn, r["event_id"], r["ten"], r["nguon"], cfg.naming["naming_version"], src[r["event_id"]],
                            checks, False)
            for eid, title, _ in hidden:
                _write_name(conn, eid, title, "medoid", None, None, {"an_ten": True}, True)
        stats.update(n_named=len(rows), n_hidden=len(hidden), n_generated=info.get("n_generated", 0))
    return len(rows) + len(hidden)


def _write_name(conn: psycopg.Connection, eid: str, name: str, source: str, version: str | None, input_hash: str | None,
                checks: dict, hidden: bool) -> None:
    conn.execute("UPDATE event_names SET is_current = false WHERE event_id = %s AND is_current", (eid,))
    conn.execute("INSERT INTO event_names (event_id, name, source, naming_version, input_hash, size_at_naming, checks) "
                 "SELECT %s, %s, %s, %s, %s, size, %s FROM events WHERE event_id = %s",
                 (eid, name, source, version, input_hash, Jsonb(checks), eid))
    conn.execute("UPDATE events SET display_name = %s, name_source = %s, name_hidden = %s, updated_at = now() "
                 "WHERE event_id = %s", (name, source, hidden, eid))


# ---------------------------------------------------------------------- xu hướng
def _floor_hour(ts: datetime) -> datetime:
    return ts.astimezone(trending.VN).replace(minute=0, second=0, microsecond=0)


def _baseline(conn: psycopg.Connection, tc: dict, now: datetime) -> list[float]:
    """Mức nền đã lưu (từ lần nạp run); DB mới chưa có → tính từ 30 ngày gần nhất và lưu lại."""
    rows = dict(conn.execute("SELECT hour_of_day, value FROM trend_baselines WHERE trend_version = %s",
                             (tc["trend_version"],)).fetchall())
    if len(rows) == 24:
        return [float(rows[h]) for h in range(24)]
    start = now - timedelta(days=30)
    ts = [r[0].timestamp() for r in conn.execute(
        "SELECT published_at FROM articles WHERE published_at >= %s AND published_at < %s", (start, now))]
    b = trending.hourly_baseline(ts, start, now)
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO trend_baselines (trend_version, hour_of_day, value, computed_from, computed_to) "
                        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        [(tc["trend_version"], h, b[h], start.date(), now.date()) for h in range(24)])
    return b


def update_trend(conn: psycopg.Connection, cfg: WorkerConfig, now: datetime, changed: bool,
                 logf: Callable[[str], None] = print) -> int:
    """Tính lại `rescore_hours` mốc gần nhất; có khoảng hở nhỏ thì bù, tối đa `backfill_hours`. Trả số mốc đã tính."""
    tc, wc, version = cfg.trending, cfg.worker, cfg.trending["trend_version"]
    end = _floor_hour(now)
    last = conn.execute("SELECT max(t) FROM trend_scores WHERE trend_version = %s", (version,)).fetchone()[0]
    if not changed and last is not None and last >= end:
        return 0
    first = end - (wc["rescore_hours"] - 1) * HOUR
    if last is not None:
        first = min(first, last + HOUR)
    first = max(first, end - (wc["backfill_hours"] - 1) * HOUR)
    marks = []
    t = first
    while t <= end:
        marks.append(t)
        t += HOUR
    window = timedelta(hours=tc["window_hours"])
    arts = [{"event_id": r[0], "ts": r[1].timestamp(), "source": r[2], "title": r[3]} for r in conn.execute(
        "SELECT ea.event_id, a.published_at, a.source, a.title FROM event_articles ea "
        "JOIN articles a ON a.article_id = ea.article_id JOIN events e ON e.event_id = ea.event_id "
        "WHERE e.status IN ('open', 'closed') AND e.last_seen >= %s", (first - window,))]
    if not arts:
        return 0
    with _step(conn, "trend", cfg, now) as (_, stats), conn.transaction():
        b = _baseline(conn, tc, now)
        idx = trending.EventIndex(arts)
        scored = {m: trending.score_at(idx, m, tc, b) for m in marks}
        affected = {r[0] for r in conn.execute(
            "DELETE FROM trend_scores WHERE trend_version = %s AND t BETWEEN %s AND %s RETURNING event_id",
            (version, first, end))}
        n = _copy(conn, "trend_scores",
                  ["trend_version", "t", "event_id", "score", "rank", "n_articles", "n_articles_3h", "n_sources",
                   "n_sources_eff", "velocity"],
                  ["text", "timestamptz", "text", "float4", "int4", "int4", "int4", "int2", "float4", "float4"],
                  ((version, m, r["event_id"], r["score"], k, r["so_bai_den_t"], r["so_bai_3h"], r["so_bao"],
                    r["n_nguon_hd"], r["van_toc"]) for m, rows in scored.items() for k, r in enumerate(rows, 1)))
        affected |= {r["event_id"] for rows in scored.values() for r in rows}
        _summarize_scores(conn, version, affected, float(tc["step_hours"]), int(tc["top_n_hours"]))
        stats.update(n_marks=len(marks), n_rows=n, n_events=len(affected))
    logf(f"xu hướng: {len(marks)} mốc tới {end.isoformat()[:16]}, {n} dòng điểm")
    return len(marks)


def _summarize_scores(conn: psycopg.Connection, version: str, event_ids: set[str], step: float, top_n: int) -> None:
    ids = list(event_ids)
    conn.execute("UPDATE events SET peak_score = NULL, peak_at = NULL, total_score = NULL, top10_hours = NULL "
                 "WHERE event_id = ANY(%s)", (ids,))
    conn.execute(
        "WITH s AS (SELECT event_id, max(score) AS peak, sum(score) AS total, count(*) FILTER (WHERE rank <= %s) AS top "
        "FROM trend_scores WHERE trend_version = %s AND event_id = ANY(%s) GROUP BY event_id), "
        "p AS (SELECT DISTINCT ON (event_id) event_id, t FROM trend_scores WHERE trend_version = %s "
        "AND event_id = ANY(%s) ORDER BY event_id, score DESC, t) "
        "UPDATE events e SET peak_score = s.peak, total_score = s.total * %s, top10_hours = s.top * %s, peak_at = p.t, "
        "trend_version = %s FROM s JOIN p USING (event_id) WHERE e.event_id = s.event_id",
        (top_n, version, ids, version, ids, step, step, version))


# ---------------------------------------------------------------------- vòng lặp
def close_stale(conn: psycopg.Connection, cfg: WorkerConfig, now: datetime) -> int:
    return conn.execute("UPDATE events SET status = 'closed', updated_at = now() WHERE status = 'open' AND last_seen < %s",
                        (now - timedelta(hours=cfg.worker["closed_after_hours"]),)).rowcount


def run_cycle(conn: psycopg.Connection, cfg: WorkerConfig, *, encoder=None, generator=None,
              logf: Callable[[str], None] = print) -> dict[str, int]:
    """Một vòng đầy đủ. Mọi bước tự kiểm tra có việc hay không, nên gọi lặp khi không có bài mới là rẻ."""
    now = clock.app_now(conn)
    embedded = embed_pending(conn, cfg, now, encoder, logf)
    assigned = recluster(conn, cfg, now, logf)
    named = name_events(conn, cfg, now, generator, logf)
    marks = update_trend(conn, cfg, now, changed=bool(assigned or named), logf=logf)
    closed = close_stale(conn, cfg, now)
    return {"embedded": embedded, "assigned": assigned, "named": named, "trend_marks": marks, "closed": closed}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eventrank.serving.worker", description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="chạy một vòng rồi thoát (mặc định)")
    mode.add_argument("--loop", action="store_true", help="chạy lặp")
    ap.add_argument("--interval", type=float, default=None, help="giây giữa hai vòng (mặc định trong cấu hình)")
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--db-env", default="DATABASE_URL", help="TÊN biến môi trường chứa URL Postgres")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logf = lambda m: print(m, flush=True)
    try:
        with db.connect(env=a.db_env) as conn:
            pending = [r["name"] for r in db.status(conn) if r["state"] != "applied"]
            if pending:
                raise WorkerError(f"migration chưa áp: {', '.join(pending)} — chạy `make db-migrate` trước")
            if not conn.execute("SELECT pg_try_advisory_lock(%s)", (_LOCK_KEY,)).fetchone()[0]:
                raise WorkerError("đã có một worker khác đang chạy trên DB này")
            cfg = load_config(a.config)
            interval = a.interval if a.interval is not None else cfg.worker["interval_seconds"]
            while True:
                try:
                    result = run_cycle(conn, cfg, logf=logf)
                    if any(result.values()) or not a.loop:
                        logf(json.dumps(result, ensure_ascii=False))
                except (psycopg.Error, ValueError, RuntimeError, OSError) as e:
                    if not a.loop:
                        raise
                    log.exception("vòng worker lỗi, thử lại sau %.0f s: %s", interval, e.__class__.__name__)
                if not a.loop:
                    return 0
                time.sleep(interval)
    except (db.DatabaseConfigError, WorkerError, ES.HideWindowError) as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
