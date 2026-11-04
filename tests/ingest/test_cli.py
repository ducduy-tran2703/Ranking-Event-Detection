"""CLI `python -m eventrank.ingest`."""
import json

import pytest

from eventrank.common import db
from eventrank.ingest import cli, contract


def test_thieu_database_url_thi_bao_ro_va_thoat_1(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "load_dotenv", lambda *a, **k: False)
    assert cli.main(["status"]) == 1
    assert "DATABASE_URL" in capsys.readouterr().err


def test_help_khong_can_db():
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0


def test_sources_sync_import_status_qua_cli(pg_conn, pg_url, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("EVENTRANK_TEST_DB", pg_url)
    assert cli.main(["sources", "sync", "--db-env", "EVENTRANK_TEST_DB"]) == 0
    url = "https://tuoitre.vn/cli-1.htm"
    row = {"article_id": contract.article_id_for(url), "url": url, "source": "tuoitre",
           "category": "Thời sự", "title": "Bài CLI", "sapo": "S", "author": None,
           "published_at": "2026-09-16T07:00:00+07:00", "content_text": "chữ " * 90}
    p = tmp_path / "a.jsonl"
    p.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    assert cli.main(["import-jsonl", str(p), "--db-env", "EVENTRANK_TEST_DB"]) == 0
    assert cli.main(["import-jsonl", str(p), "--db-env", "EVENTRANK_TEST_DB"]) == 0
    out = capsys.readouterr().out
    assert "inserted=1" in out and "inserted=0" in out
    assert cli.main(["status", "--db-env", "EVENTRANK_TEST_DB"]) == 0
    assert "tuoitre" in capsys.readouterr().out


def test_run_tu_choi_nguon_chua_bat_hoac_chua_co_crawler(pg_conn, pg_url, monkeypatch, capsys):
    monkeypatch.setenv("EVENTRANK_TEST_DB", pg_url)
    assert cli.main(["run", "--source", "tuoitre", "--once", "--db-env", "EVENTRANK_TEST_DB"]) == 1
    assert "chưa có crawler" in capsys.readouterr().err


def test_run_tu_choi_khi_dong_ho_dang_replay(pg_conn, pg_url, monkeypatch, capsys):
    from datetime import UTC, datetime

    from eventrank.ingest import clock
    clock.set_replay(pg_conn, datetime(2026, 8, 1, tzinfo=UTC), 60)
    monkeypatch.setenv("EVENTRANK_TEST_DB", pg_url)
    assert cli.main(["run", "--source", "tuoitre", "--once", "--db-env", "EVENTRANK_TEST_DB"]) == 1
    assert "replay" in capsys.readouterr().err
