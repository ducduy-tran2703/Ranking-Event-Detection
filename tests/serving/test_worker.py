"""Worker chạy liên tục: đối chiếu event_id (thuần) và một vòng đầy đủ trên Postgres tạm. Không tải mô hình."""
import hashlib
import re
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from eventrank.ingest import clock, sink
from eventrank.ingest.contract import validate_article
from eventrank.ingest.sources import load_sources
from eventrank.serving import worker as W
from eventrank.serving.db_store import DbEventStore


def day_of(_aid):
    return "20261109"


def aid(n):
    return f"{n:02x}" * 32


A, B, C, D, E_, F = (aid(k) for k in range(1, 7))


# ---------------------------------------------------------------------- reconcile
def test_all_new_cluster_gets_id_from_first_article():
    plan = W.reconcile([A, B], [0, 0], {}, {}, day_of)
    eid = f"E20261109-{A[:8]}"
    assert plan.new_events == {eid: A}
    assert plan.assign == {A: (eid, "recluster"), B: (eid, "recluster")}


def test_new_article_joins_existing_event_and_keeps_id():
    plan = W.reconcile([A, B, C], [0, 0, 0], {A: "E1", B: "E1"}, {"E1": 2}, day_of)
    assert plan.new_events == {}
    assert plan.assign == {C: ("E1", "recluster")}


def test_locked_event_is_never_split():
    prev = {A: "E1", B: "E1", C: "E1"}
    plan = W.reconcile([A, B, C], [0, 0, 1], prev, {"E1": 3}, day_of)
    assert plan.assign == {} or set(plan.assign) <= {C}
    assert C not in plan.assign, "bài của sự kiện khoá không được chuyển đi"
    assert plan.merges == {}


def test_new_fragment_of_locked_event_grows_it():
    prev = {A: "E1", B: "E1", C: "E1"}
    plan = W.reconcile([A, B, C, D], [0, 0, 1, 1], prev, {"E1": 3}, day_of)
    assert plan.assign == {D: ("E1", "recluster")}
    assert plan.new_events == {}


def test_small_event_can_split_one_to_one():
    prev = {A: "E1", B: "E1"}
    plan = W.reconcile([A, B, C], [0, 1, 1], prev, {"E1": 2}, day_of)
    # Jaccard: {A}∩E1 = 1/2, {B,C}∩E1 = 1/3 → cụm {A} giữ E1, cụm {B,C} là sự kiện mới
    new = next(iter(plan.new_events))
    assert A not in plan.assign
    assert plan.assign[B] == (new, "recluster") and plan.assign[C] == (new, "recluster")


def test_locked_event_fully_inside_cluster_is_merged():
    prev = {A: "E1", B: "E1", C: "E1", D: "E2", E_: "E2", F: "E2"}
    plan = W.reconcile([A, B, C, D, E_, F], [0] * 6, prev, {"E1": 3, "E2": 3}, day_of)
    assert plan.merges == {"E2": "E1"}
    assert plan.assign[D] == ("E1", "merge")


def test_locked_event_partly_outside_window_is_not_merged():
    prev = {A: "E1", B: "E1", C: "E1", D: "E2"}
    plan = W.reconcile([A, B, C, D], [0] * 4, prev, {"E1": 3, "E2": 5}, day_of)
    assert plan.merges == {}
    assert D not in plan.assign


def test_emptied_small_event_is_marked_merged():
    prev = {A: "E1", B: "E1", C: "E1", D: "E2"}
    plan = W.reconcile([A, B, C, D], [0] * 4, prev, {"E1": 3, "E2": 1}, day_of)
    assert plan.assign[D] == ("E1", "recluster")
    assert plan.merges == {"E2": "E1"}


def test_cluster_barely_touching_locked_event_does_not_join_it():
    prev = {A: "E1", B: "E1", C: "E1"}
    plan = W.reconcile([A, B, C, D, E_], [0, 0, 1, 1, 1], prev, {"E1": 3}, day_of, min_lock_jaccard=0.5)
    assert C not in plan.assign, "bài đã khoá vẫn ở lại sự kiện của nó"
    new = next(iter(plan.new_events))
    assert plan.assign[D] == (new, "recluster") and plan.assign[E_] == (new, "recluster")


def test_cluster_overlapping_locked_event_enough_still_joins():
    prev = {A: "E1", B: "E1", C: "E1"}
    plan = W.reconcile([A, B, C, D], [0, 0, 0, 0], prev, {"E1": 3}, day_of, min_lock_jaccard=0.5)
    assert plan.assign == {D: ("E1", "recluster")}


def test_cluster_of_only_locked_articles_needs_no_new_event():
    prev = {A: "E1", B: "E1", C: "E1"}
    plan = W.reconcile([A, B, C], [0, 0, 1], prev, {"E1": 3}, day_of, min_lock_jaccard=0.9)
    assert plan.new_events == {} and plan.assign == {}


def test_new_event_id_comes_from_a_movable_article():
    prev = {A: "E1", B: "E1", C: "E1"}
    plan = W.reconcile([A, B, C, D], [0, 0, 1, 1], prev, {"E1": 3}, day_of, min_lock_jaccard=0.9)
    assert list(plan.new_events.values()) == [D]


def test_new_id_never_fails_when_every_candidate_is_taken():
    taken = {f"E20261109-{A[:8]}"}
    plan = W.reconcile([A], [0], {}, {}, day_of, taken_ids=taken)
    eid = next(iter(plan.new_events))
    assert eid not in taken and re.fullmatch(r"E\d{8}-[0-9a-f]{8}", eid)
    assert plan.new_events[eid] == A


def test_new_id_avoids_collision():
    taken = {f"E20261109-{A[:8]}"}
    plan = W.reconcile([A, B], [0, 0], {}, {}, day_of, taken_ids=taken)
    assert list(plan.new_events) == [f"E20261109-{B[:8]}"]


# ---------------------------------------------------------------------- một vòng trên Postgres
NOW = datetime(2026, 11, 9, 10, 20, tzinfo=UTC)
TOPICS = {"Bão": 0, "Lạm": 1, "Bóng": 2}


def encoder(texts):
    out = np.zeros((len(texts), 4), dtype=np.float32)
    for i, text in enumerate(texts):
        out[i, TOPICS.get(text.split()[0], 3)] = 1.0
    return out


class Gen:
    def __init__(self):
        self.calls = 0

    def __call__(self, inputs):
        self.calls += len(inputs)
        return ["Bão số 13 đổ bộ" for _ in inputs]


@pytest.fixture
def conn(pg_conn):
    sink.sync_sources(pg_conn, load_sources())
    clock.set_replay(pg_conn, NOW, 60)
    return pg_conn


@pytest.fixture
def cfg(tmp_path):
    return W.WorkerConfig(
        cluster={"algo_version": "v1", "model_version": "m1", "model": "khong-co", "prep": "raw", "algo": "agglo",
                 "threshold": 0.83, "window_hours": 48},
        naming={**W.naming.DEFAULTS, "naming_version": "n1", "model": "khong-co", "cache_dir": str(tmp_path)},
        trending={**W.trending.DEFAULTS, "trend_version": "t2"},
        hide_window=W.ES.parse_hide_window(None))


def add(conn, n, title, source="tuoitre", minutes=60, now=NOW):
    url = f"https://{source}.vn/bai-{n}.htm"
    raw = {"article_id": hashlib.sha256(url.encode()).hexdigest(), "url": url, "source": source, "category": "Thời sự",
           "title": title, "sapo": "Sapo đủ dài cho bài kiểm thử.", "author": "A",
           "published_at": (now - timedelta(minutes=minutes)).isoformat(),
           "content_text": "Nội dung bài báo phục vụ kiểm thử worker đủ dài. " * 15}
    res = validate_article(raw, known_sources=sink.known_sources(conn), now=datetime(2030, 1, 1, tzinfo=UTC))
    assert sink.upsert_articles(conn, [res], "test").inserted == 1
    return raw["article_id"]


def cycle(conn, cfg, gen=None):
    return W.run_cycle(conn, cfg, encoder=encoder, generator=gen or Gen(), logf=lambda _m: None)


def event_of(conn, article):
    return conn.execute("SELECT event_id FROM event_articles WHERE article_id = %s", (article,)).fetchone()[0]


def test_cycle_builds_events_names_and_trend(conn, cfg):
    a1 = add(conn, 1, "Bão số 13 đổ bộ miền Trung", "tuoitre")
    a2 = add(conn, 2, "Bão số 13 gây mưa lớn ở Huế", "thanhnien", 50)
    add(conn, 3, "Lạm phát tháng 10 tăng nhẹ", "vnexpress", 40)
    res = cycle(conn, cfg)
    assert (res["embedded"], res["assigned"]) == (3, 3)
    assert event_of(conn, a1) == event_of(conn, a2)
    name, source, size, status = conn.execute(
        "SELECT display_name, name_source, size, status FROM events WHERE event_id = %s", (event_of(conn, a1),)).fetchone()
    assert (name, source, size, status) == ("Bão số 13 đổ bộ", "model", 2, "open")
    single = conn.execute("SELECT name_source FROM events WHERE size = 1").fetchone()[0]
    assert single == "title"
    assert conn.execute("SELECT count(*) FROM event_articles WHERE is_medoid").fetchone()[0] == 2
    rows = conn.execute("SELECT event_id, rank FROM trend_scores").fetchall()
    assert {r[0] for r in rows} == {event_of(conn, a1)}                    # sự kiện 1 bài không vào xu hướng
    peak, total = conn.execute("SELECT peak_score, total_score FROM events WHERE event_id = %s",
                               (event_of(conn, a1),)).fetchone()
    assert peak > 0 and total >= peak
    assert conn.execute("SELECT count(*) FROM worker_runs WHERE status = 'ok'").fetchone()[0] == 4


def test_second_cycle_without_new_articles_does_nothing(conn, cfg):
    add(conn, 1, "Bão số 13 đổ bộ miền Trung")
    add(conn, 2, "Bão số 13 gây mưa lớn", "thanhnien", 50)
    cycle(conn, cfg)
    version = DbEventStore.current_version(conn)
    gen = Gen()
    assert not any(cycle(conn, cfg, gen).values())
    assert gen.calls == 0
    assert DbEventStore.current_version(conn) == version


def test_event_id_survives_new_article_and_user_bookmark_stays(conn, cfg):
    a1 = add(conn, 1, "Bão số 13 đổ bộ", "tuoitre", 90)
    add(conn, 2, "Bão số 13 gây mưa", "thanhnien", 80)
    add(conn, 3, "Bão số 13 làm mất điện", "vnexpress", 70)
    cycle(conn, cfg)
    eid = event_of(conn, a1)
    user = conn.execute("INSERT INTO users (email, password_hash, display_name, terms_accepted_at) VALUES ('a@b.vn', 'x', 'A', now()) "
                        "RETURNING user_id").fetchone()[0]
    conn.execute("INSERT INTO event_bookmarks (user_id, event_id) VALUES (%s, %s)", (user, eid))
    a4 = add(conn, 4, "Bão số 13 suy yếu", "vietnamnet", 10)
    clock.set_replay(conn, NOW + timedelta(minutes=5), 60)
    cycle(conn, cfg)
    assert event_of(conn, a4) == eid
    assert conn.execute("SELECT size, n_sources FROM events WHERE event_id = %s", (eid,)).fetchone() == (4, 4)
    assert conn.execute("SELECT event_id FROM event_bookmarks").fetchone()[0] == eid


def test_rename_only_when_event_grows_enough(conn, cfg):
    a1 = add(conn, 1, "Bão số 13 đổ bộ", "tuoitre", 90)
    for n, src, minutes in ((2, "thanhnien", 80), (3, "vnexpress", 70), (4, "vietnamnet", 60)):
        add(conn, n, f"Bão số 13 tin {n}", src, minutes)
    cycle(conn, cfg)
    eid = event_of(conn, a1)
    add(conn, 5, "Bão số 13 tin 5", "nhandan", 30)
    clock.set_replay(conn, NOW + timedelta(minutes=5), 60)
    cycle(conn, cfg)
    assert conn.execute("SELECT count(*) FROM event_names WHERE event_id = %s", (eid,)).fetchone()[0] == 1
    add(conn, 6, "Bão số 13 tin 6", "baochinhphu", 20)
    clock.set_replay(conn, NOW + timedelta(minutes=10), 60)
    cycle(conn, cfg)
    assert conn.execute("SELECT count(*) FROM event_names WHERE event_id = %s", (eid,)).fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM event_names WHERE event_id = %s AND is_current", (eid,)).fetchone()[0] == 1


def test_editor_name_is_never_overwritten(conn, cfg):
    a1 = add(conn, 1, "Bão số 13 đổ bộ", "tuoitre", 90)
    add(conn, 2, "Bão số 13 gây mưa", "thanhnien", 80)
    cycle(conn, cfg)
    eid = event_of(conn, a1)
    conn.execute("UPDATE event_names SET source = 'editor', name = 'Tên editor' WHERE event_id = %s", (eid,))
    conn.execute("UPDATE events SET display_name = 'Tên editor', name_source = 'editor' WHERE event_id = %s", (eid,))
    for n in range(3, 9):
        add(conn, n, f"Bão số 13 tin {n}", "vnexpress", 90 - n)
    clock.set_replay(conn, NOW + timedelta(minutes=5), 60)
    cycle(conn, cfg)
    assert conn.execute("SELECT display_name FROM events WHERE event_id = %s", (eid,)).fetchone()[0] == "Tên editor"


def test_test_window_event_never_gets_model_name(conn, cfg):
    at = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
    clock.set_replay(conn, at, 60)
    a1 = add(conn, 1, "Bão số 13 đổ bộ", "tuoitre", 60, at)
    add(conn, 2, "Bão số 13 gây mưa", "thanhnien", 50, at)
    gen = Gen()
    cycle(conn, cfg, gen)
    assert gen.calls == 0
    name, hidden, source = conn.execute("SELECT display_name, name_hidden, name_source FROM events WHERE event_id = %s",
                                        (event_of(conn, a1),)).fetchone()
    assert hidden is True and source == "medoid" and name.startswith("Bão số 13")
    assert conn.execute("SELECT count(*) FROM event_names WHERE source = 'model'").fetchone()[0] == 0


def test_fallback_id_from_an_earlier_cycle_is_not_reused(conn, cfg):
    a1 = add(conn, 1, "Bão số 13 đổ bộ")
    day = W._vn_day(NOW - timedelta(minutes=60))
    used = [f"E{day}-{a1[:8]}", f"E{day}-{hashlib.sha256(f'{a1}:1'.encode()).hexdigest()[:8]}"]
    for eid in used:
        conn.execute("INSERT INTO events (event_id, first_seen, last_seen, size, n_sources, display_name, name_source, "
                     "algo_version, model_version) VALUES (%s, now(), now(), 1, 1, 'x', 'title', 'v1', 'm1')", (eid,))
    assert cycle(conn, cfg)["assigned"] == 1
    assert event_of(conn, a1) not in used


def test_old_articles_outside_pending_window_are_ignored(conn, cfg):
    add(conn, 1, "Bão số 13 từ lâu", "tuoitre", 60 * 24 * 30)
    res = cycle(conn, cfg)
    assert (res["embedded"], res["assigned"]) == (0, 0)
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_stale_event_is_closed(conn, cfg):
    a1 = add(conn, 1, "Bão số 13 đổ bộ", "tuoitre", 60)
    cycle(conn, cfg)
    clock.set_replay(conn, NOW + timedelta(hours=60), 60)
    assert cycle(conn, cfg)["closed"] == 1
    assert conn.execute("SELECT status FROM events WHERE event_id = %s", (event_of(conn, a1),)).fetchone()[0] == "closed"


def test_failed_step_is_recorded_and_retried(conn, cfg):
    add(conn, 1, "Bão số 13 đổ bộ", "tuoitre", 60)

    def broken(_texts):
        raise RuntimeError("mô hình lỗi")

    with pytest.raises(RuntimeError):
        W.run_cycle(conn, cfg, encoder=broken, generator=Gen(), logf=lambda _m: None)
    status, error = conn.execute("SELECT status, error FROM worker_runs WHERE step = 'embed'").fetchone()
    assert status == "failed" and "mô hình lỗi" in error
    assert cycle(conn, cfg)["assigned"] == 1


