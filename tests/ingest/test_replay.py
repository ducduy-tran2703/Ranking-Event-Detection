"""Phát lại Silver theo published_at với đồng hồ giả lập (`eventrank.ingest.replay`)."""
from datetime import UTC, datetime, timedelta

import pytest

from eventrank.ingest import clock, contract, replay, sink

T0 = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
NOW = datetime(2026, 11, 1, tzinfo=UTC)


def art(i, offset):
    r = {"url": f"https://tuoitre.vn/r-{i}.htm", "source": "tuoitre", "category": "Thời sự",
         "title": f"Bài {i}", "sapo": "Sapo", "author": "A",
         "published_at": (T0 + offset).isoformat(), "content_text": "chữ " * 90}
    return contract.validate_article(r, known_sources={"tuoitre"}, now=NOW)


ARTS = [art(1, timedelta(hours=-1)), art(2, timedelta(minutes=10)),
        art(3, timedelta(minutes=30)), art(4, timedelta(hours=2))]


class FakeTime:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture
def conn(pg_conn):
    sink.sync_sources(pg_conn, [{"source": "tuoitre", "display_name": "Tuổi Trẻ"}])
    return pg_conn


def n_articles(conn):
    return conn.execute("SELECT count(*) FROM articles").fetchone()[0]


def run(conn, **kw):
    ft = FakeTime()
    args = {"start": T0, "speed": 60, "tick": 5, "clock": ft, "sleep": ft.sleep,
            "log": lambda m: None}
    args.update(kw)
    return replay.run_replay(conn, sorted(ARTS, key=lambda a: a.published_at), **args)


def test_phat_lai_theo_dong_ho_gia_lap_dung_roi_chay_tiep(conn):
    # nhịp 5 s thật × 60 = 5 phút giả lập
    r = run(conn, max_ticks=2)
    assert r.sim_now == T0 + timedelta(minutes=10)
    assert n_articles(conn) == 2                     # bài trước T0 + bài 00:10
    c = clock.read_clock(conn)
    assert (c.mode, c.sim_now, c.speed) == ("replay", T0 + timedelta(minutes=10), 60)
    assert clock.app_now(conn) == T0 + timedelta(minutes=10)
    # chạy lại (không --reset): tiếp tục từ 00:10, không quay về T0
    r2 = run(conn, until=T0 + timedelta(hours=1))
    assert r2.resumed and r2.sim_now == T0 + timedelta(hours=1)
    assert n_articles(conn) == 3                     # bài 02:00 chưa tới giờ
    assert r2.counts.inserted == 1
    via = conn.execute("SELECT DISTINCT ingested_via FROM articles").fetchall()
    assert via == [("replay",)]


def test_reset_quay_ve_start(conn):
    run(conn, max_ticks=6)
    r = run(conn, max_ticks=1, reset=True)
    assert not r.resumed and r.sim_now == T0 + timedelta(minutes=5)


def test_mac_dinh_dung_sau_bai_cuoi(conn):
    r = run(conn)
    assert r.sim_now == T0 + timedelta(hours=2) and n_articles(conn) == 4


def test_tu_choi_phat_lai_vao_db_co_bai_that(conn):
    sink.upsert_articles(conn, [art(9, timedelta(0))], via="import_jsonl")
    with pytest.raises(replay.ReplayError, match="DB riêng"):
        run(conn, max_ticks=1)


def test_nap_silver_sap_xep_va_dem_bai_loai(tmp_path):
    import json
    p = tmp_path / "a.jsonl"
    rows = [a.to_silver() for a in reversed(ARTS)] + [{"url": "http://x"}]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    arts, rejected = replay.load_silver([str(p)], known_sources={"tuoitre"}, now=NOW)
    assert [a.title for a in arts] == ["Bài 1", "Bài 2", "Bài 3", "Bài 4"]
    assert rejected.rejected == 1
