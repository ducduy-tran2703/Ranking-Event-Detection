"""Nạp Silver JSONL có sẵn vào Postgres (`eventrank.ingest.jsonl`)."""
import json
from datetime import UTC, datetime

from eventrank.ingest import jsonl, sink

NOW = datetime(2026, 11, 1, tzinfo=UTC)


def line(i, **kw):
    import hashlib
    url = f"https://tuoitre.vn/bai-{i}.htm"
    r = {"article_id": hashlib.sha256(url.encode()).hexdigest(), "url": url, "source": "TUOITRE",
         "category": "Thời sự", "title": f"Bài {i}", "sapo": "Sapo", "author": "",
         "published_at": f"2026-09-1{i}T10:00:00+07:00", "content_text": "chữ " * 90}
    r.update(kw)
    return json.dumps(r, ensure_ascii=False)


def write(tmp_path, lines):
    d = tmp_path / "silver" / "tuoitre"
    d.mkdir(parents=True)
    p = d / "articles_silver.jsonl"
    p.write_text("\n".join(lines) + "\n\n", encoding="utf-8")
    return p


def test_doc_jsonl_bao_dong_hong_la_rejected(tmp_path):
    p = write(tmp_path, [line(1), "{khong phai json", "[1, 2]"])
    items = list(jsonl.read_jsonl([str(p)]))
    assert len(items) == 3            # dòng trống bỏ qua
    assert isinstance(items[0], dict)
    assert items[1].codes == ("json_invalid",) and "articles_silver.jsonl:2" in items[1].ref


def test_import_hai_lan_lan_hai_khong_them_gi(pg_conn, tmp_path):
    sink.sync_sources(pg_conn, [{"source": "tuoitre", "display_name": "Tuổi Trẻ"}])
    p = write(tmp_path, [line(1), line(2), line(3, published_at="2026-09-13 10:00"), "{hỏng"])
    first = jsonl.import_jsonl(pg_conn, [str(tmp_path / "silver/*/*.jsonl")], now=NOW)
    assert (first.inserted, first.rejected) == (2, 2)
    assert first.reject_reasons == {"published_at_naive": 1, "json_invalid": 1}
    again = jsonl.import_jsonl(pg_conn, [str(p)], now=NOW)
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, 2)
    runs = pg_conn.execute("SELECT source, crawler, status, n_new, n_unchanged FROM crawl_runs "
                           "ORDER BY run_id").fetchall()
    assert runs == [("tuoitre", "import_jsonl", "ok", 2, 0),
                    ("tuoitre", "import_jsonl", "ok", 0, 2)]
    via = pg_conn.execute("SELECT DISTINCT ingested_via FROM articles").fetchall()
    assert via == [("import_jsonl",)]


def test_glob_khong_khop_file_nao_bao_loi(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        list(jsonl.read_jsonl([str(tmp_path / "khong/*.jsonl")]))
