"""`GET /api/live/overview` (số liệu trực tiếp từ Postgres) và cách gom `worker_runs` thành vòng worker."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from eventrank.serving.live_stats import HOURS, group_rounds

T0 = datetime(2026, 11, 10, 7, 0, tzinfo=UTC)


def _run(run_id, step, minute, seconds=1.0, status="ok", **stats):
    start = T0 + timedelta(minutes=minute)
    return {"run_id": run_id, "step": step, "status": status, "started_at": start,
            "finished_at": start + timedelta(seconds=seconds), "seconds": seconds, "stats": stats, "error": None}


def test_group_rounds_splits_on_embed_repeat_and_gap():
    runs = [
        _run(1, "embed", 0, n_articles=5), _run(2, "recluster", 0.5), _run(3, "name", 0.6), _run(4, "trend", 1),
        _run(5, "trend", 6),                                   # vòng chỉ có trend (không bài mới)
        _run(6, "embed", 11), _run(7, "recluster", 11.2, status="failed"),
        _run(8, "name", 40),                                   # cách đầu vòng > 10 phút → vòng mới
    ]
    rounds = group_rounds(list(reversed(runs)))
    assert [list(r["steps"]) for r in rounds] == [["name"], ["embed", "recluster"], ["trend"],
                                                  ["embed", "recluster", "name", "trend"]]
    assert rounds[1]["status"] == "failed"
    assert rounds[3]["status"] == "ok"
    assert rounds[3]["finished_at"] == runs[3]["finished_at"]
    assert len(group_rounds(runs, limit=2)) == 2


def _article(conn, source, url, published, crawled, flags=()):
    aid = hashlib.sha256(url.encode()).hexdigest()
    conn.execute(
        "INSERT INTO articles (article_id, url, source, category, title, sapo, published_at, content_text, crawled_at, "
        "ingested_via, content_hash, quality_flags) VALUES (%s, %s, %s, 'Thời sự', 'Tiêu đề', 'Sapo', %s, 'Nội dung', "
        "%s, 'import_jsonl', %s, %s)", (aid, url, source, published, crawled, aid, list(flags)))
    return aid


@pytest.fixture
def client(pg_conn, pg_url, store):
    c = pg_conn
    now = c.execute("SELECT now()").fetchone()[0]
    c.execute("INSERT INTO sources (source, display_name) VALUES ('tuoitre', 'Tuổi Trẻ'), ('qdnd', 'QĐND')")
    a1 = _article(c, "tuoitre", "https://tuoitre.vn/a", now - timedelta(hours=2), now - timedelta(minutes=20),
                  ["missing_author"])
    _article(c, "tuoitre", "https://tuoitre.vn/b", now - timedelta(hours=3), now - timedelta(hours=5))
    _article(c, "qdnd", "https://qdnd.vn/c", now - timedelta(days=30), now - timedelta(days=30), ["no_body"])
    c.execute("INSERT INTO article_embeddings (article_id, model_version, content_hash, dim, vec) "
              "VALUES (%s, 'm', %s, 1, '\\x00000000')", (a1, a1))
    c.execute(
        "INSERT INTO events (event_id, first_seen, last_seen, size, n_sources, sources, display_name, name_source, "
        "category_std, algo_version, model_version) VALUES "
        "('E20261110-0000000a', %(t)s, %(t)s, 2, 2, '{\"tuoitre\": 1, \"qdnd\": 1}', 'Sự kiện A', 'model', 'Thời sự', 'v', 'm'),"
        "('E20261110-0000000b', %(t)s, %(t)s, 1, 1, '{\"tuoitre\": 1}', 'Sự kiện B', 'title', NULL, 'v', 'm')",
        {"t": now - timedelta(hours=1)})
    c.execute("UPDATE events SET status = 'closed' WHERE event_id = 'E20261110-0000000b'")
    c.execute("INSERT INTO crawl_runs (source, crawler, started_at, finished_at, status, n_seen, n_new, n_rejected, "
              "reject_reasons) VALUES ('tuoitre', 'import_jsonl', %s, %s, 'ok', 3, 2, 1, %s)",
              (now - timedelta(minutes=20), now - timedelta(minutes=19), json.dumps({"missing_title": 1})))
    c.execute("INSERT INTO crawl_runs (source, crawler, started_at, status, error) VALUES "
              "('qdnd', 'import_jsonl', %s, 'failed', 'HTTP 503')", (now - timedelta(minutes=10),))
    for step, minutes, stats in [("embed", 15, {"n_articles": 1}), ("recluster", 14, {"n_new_events": 2, "n_moved": 1}),
                                 ("name", 14, {"n_generated": 1}), ("trend", 13, {"n_rows": 4})]:
        c.execute("INSERT INTO worker_runs (step, started_at, finished_at, status, stats) VALUES (%s, %s, %s, 'ok', %s)",
                  (step, now - timedelta(minutes=minutes), now - timedelta(minutes=minutes - 0.5), json.dumps(stats)))
    app = create_app(store, None, db_url=pg_url)
    app.state.crawler_url = "http://127.0.0.1:9"           # không có crawler → phần crawler là null
    with TestClient(app) as tc:
        yield tc
    if app.state.db_pool is not None:
        app.state.db_pool.close()


def test_live_overview_counts(client):
    r = client.get("/api/live/overview")
    assert r.status_code == 200, r.text
    d = r.json()
    t = d["totals"]
    assert (t["articles"], t["new_1h"], t["new_24h"], t["embedded"], t["not_embedded"]) == (3, 1, 2, 1, 2)
    assert t["events_by_status"] == {"open": 1, "closed": 1}
    assert d["clock_mode"] == "real" and d["crawler"] is None

    src = {s["source"]: s for s in d["sources"]}
    assert src["tuoitre"]["display_name"] == "Tuổi Trẻ"
    assert (src["tuoitre"]["total"], src["tuoitre"]["new_24h"], src["tuoitre"]["flags"]["missing_author"]) == (2, 2, 1)
    assert (src["tuoitre"]["runs_24h"], src["tuoitre"]["rejected_24h"]) == (1, 1)
    assert src["qdnd"]["last_run_status"] == "failed" and src["qdnd"]["last_error"] == "HTTP 503"
    assert src["qdnd"]["failed_24h"] == 1 and src["qdnd"]["flags"]["no_body"] == 1

    h = d["hourly"]
    assert len(h["hours"]) == HOURS and all(len(s["ingested"]) == HOURS for s in h["series"])
    tuoitre = next(s for s in h["series"] if s["source"] == "tuoitre")
    assert sum(tuoitre["ingested"]) == 2 and sum(tuoitre["published"]) == 2
    assert sum(h["events_created"]) == 2
    assert len(d["daily"]["days"]) == 14

    w = d["worker"]
    assert len(w["rounds"]) == 1 and list(w["rounds"][0]["steps"]) == ["embed", "recluster", "name", "trend"]
    assert (w["rounds_24h"], w["new_events_24h"], w["moved_24h"], w["named_24h"]) == (1, 2, 1, 1)

    e = d["events"]
    assert e["total"] == 2 and e["multi_source"] == 1
    assert e["size_hist"][0] == {"label": "1", "events": 1, "articles": 1}
    assert e["naming"] == {"model": 1}
    assert [x["event_id"] for x in e["top"]] == ["E20261110-0000000a", "E20261110-0000000b"]

    tables = {x["table"]: x["rows"] for x in d["tables"]}
    assert tables["articles"] == 3 and tables["crawl_runs"] == 2


def test_live_overview_is_cached(client, pg_conn):
    assert client.get("/api/live/overview").json()["totals"]["articles"] == 3
    _article(pg_conn, "qdnd", "https://qdnd.vn/moi", datetime.now(UTC), datetime.now(UTC))
    assert client.get("/api/live/overview").json()["totals"]["articles"] == 3     # còn trong 15 s đệm
