"""Crawler → Postgres bridge, age filter and the rules every source must follow. No network."""
import json
import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import psycopg
import pytest

from automation import db_sink
from automation.config import Settings
from automation.http import SourceBlocked, SourceClient
from automation.pipeline import Pipeline

LEGACY = ["baochinhphu", "nhandan", "dantri", "qdnd"]
HONEST_UA = "EventRank-Test/1.0 (test)"


def record(source="tuoitre", url="https://tuoitre.vn/bai-kiem-thu-100261109105028588.htm"):
    from crawler.common_utils import compute_article_id

    body = "Nội dung bài báo phục vụ kiểm thử được viết đủ dài để qua hợp đồng dữ liệu. " * 12
    return {"article_id": compute_article_id(url), "url": url, "source": source, "category": "Thể Thao",
            "title": "Tiêu đề bài báo dùng để kiểm thử cầu nối", "sapo": "Sapo kiểm thử đủ dài.", "author": "A",
            "published_at": datetime.now(UTC).isoformat(), "content_text": body}


def write_export(root, job, source, rows):
    path = root / "jobs" / job / "clean_silver" / f"{source}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


@pytest.mark.parametrize("source", LEGACY)
def test_legacy_sources_require_honest_user_agent(source, monkeypatch, tmp_path):
    monkeypatch.delenv("CRAWLER_USER_AGENT", raising=False)
    with pytest.raises(ValueError, match="CRAWLER_USER_AGENT"):
        SourceClient(source, Settings(data_dir=tmp_path), threading.Event())
    monkeypatch.setenv("CRAWLER_USER_AGENT", "Mozilla/5.0 Chrome")
    with pytest.raises(ValueError, match="CRAWLER_USER_AGENT"):
        SourceClient(source, Settings(data_dir=tmp_path), threading.Event())


def test_legacy_source_stops_when_robots_disallows(monkeypatch, tmp_path):
    monkeypatch.setenv("CRAWLER_USER_AGENT", HONEST_UA)
    client = SourceClient("qdnd", Settings(data_dir=tmp_path, delays=dict.fromkeys(
        Settings(data_dir=tmp_path).delays, 0)), threading.Event())
    session = Mock()
    session.get.return_value = Mock(status_code=200, is_redirect=False, text="User-agent: *\nDisallow: /kinh-te/\n")
    with patch.object(client, "_session", return_value=session), pytest.raises(SourceBlocked, match="robots"):
        client.get("https://www.qdnd.vn/kinh-te/bai-viet-123")
    assert session.get.call_count == 1           # only robots.txt was requested


@pytest.mark.parametrize(("age_days", "limit", "expected"), [
    (30, 7, True), (6, 7, False), (30, 0, False),
])
def test_too_old_uses_configured_limit(age_days, limit, expected, tmp_path):
    pipeline = Pipeline(Settings(data_dir=tmp_path, max_article_age_days=limit), threading.Event())
    assert pipeline.too_old((datetime.now(UTC) - timedelta(days=age_days)).isoformat()) is expected


def test_naive_published_at_is_treated_as_vietnam_time(tmp_path):
    pipeline = Pipeline(Settings(data_dir=tmp_path, max_article_age_days=1), threading.Event())
    assert pipeline.too_old("2020-01-01T08:00:00") is True


def test_db_sink_is_off_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("CRAWLER_DB_SINK", raising=False)
    assert Settings(data_dir=tmp_path).db_sink is False


def test_pending_skips_empty_and_already_imported(tmp_path):
    fresh = write_export(tmp_path, "b", "tuoitre", [record()])
    write_export(tmp_path, "c", "tuoitre", [])
    done = write_export(tmp_path, "a", "tuoitre", [record()])
    done.with_suffix(db_sink.MARKER_SUFFIX).touch()
    assert db_sink.pending_exports(tmp_path, "tuoitre") == [fresh]


def test_import_pending_loads_marks_and_is_idempotent(pg_conn, pg_url, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    export = write_export(tmp_path, "job1", "tuoitre", [record()])
    result = db_sink.import_pending(tmp_path, "tuoitre")
    assert (result["files"], result["inserted"], result["rejected"]) == (1, 1, 0)
    assert export.with_suffix(db_sink.MARKER_SUFFIX).exists()
    assert pg_conn.execute("SELECT count(*) FROM articles").fetchone()[0] == 1
    assert db_sink.import_pending(tmp_path, "tuoitre") is None


@pytest.mark.parametrize(("source", "url"), [
    ("DANTRI", "https://dantri.com.vn/thoi-su/bai-20261109080000000.htm"),
    ("QDND", "https://www.qdnd.vn/kinh-te/bai-viet-123"),
])
def test_uppercase_legacy_source_is_accepted(pg_conn, pg_url, tmp_path, monkeypatch, source, url):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    write_export(tmp_path, "job1", source.lower(), [record(source, url)])
    result = db_sink.import_pending(tmp_path, source.lower())
    assert (result["inserted"], result["rejected"]) == (1, 0), result
    stored = pg_conn.execute("SELECT source FROM articles").fetchone()[0]
    assert stored == source.lower()


def test_failed_import_leaves_export_pending(tmp_path, monkeypatch):
    export = write_export(tmp_path, "job1", "tuoitre", [record()])
    monkeypatch.setattr(db_sink.db, "connect", Mock(side_effect=psycopg.OperationalError("down")))
    with pytest.raises(psycopg.OperationalError):
        db_sink.import_pending(tmp_path, "tuoitre")
    assert not export.with_suffix(db_sink.MARKER_SUFFIX).exists()


def test_replay_clock_refuses_live_data(pg_conn, pg_url, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    pg_conn.execute("UPDATE app_clock SET mode = 'replay', sim_now = now(), speed = 60")
    write_export(tmp_path, "job1", "tuoitre", [record()])
    with pytest.raises(RuntimeError, match="replay"):
        db_sink.import_pending(tmp_path, "tuoitre")
