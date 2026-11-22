"""Tool đếm/sự kiện/phạm vi kho chạy thật trên Postgres tạm: chỉ tính bài đã vào kho RAG, loại báo bị ẩn."""
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eventrank.ingest import contract, sink
from eventrank.rag import tools as T
from eventrank.rag.pipeline import corpus_snapshot
from eventrank.rag.prepare import build_chunks, import_ner

FIX = Path("tests/fixtures/rag")
EVENT = "E20260910-aaaaaaaa"


@pytest.fixture
def kho(pg_conn):
    c = pg_conn
    sink.sync_sources(c, [{"source": "vnexpress", "display_name": "VnExpress"},
                          {"source": "tuoitre", "display_name": "Tuổi Trẻ"}])
    arts = [json.loads(line) for line in (FIX / "silver.jsonl").read_text(encoding="utf-8").splitlines()]
    sink.upsert_articles(c, [contract.validate_article(a, known_sources={"vnexpress"},
                                                       now=datetime(2026, 11, 4, tzinfo=UTC)) for a in arts[:2]],
                         via="import_jsonl")
    import_ner(c, str(FIX / "silver.jsonl"), FIX / "ner.jsonl", ner_version="sample")
    build_chunks(c, max_units=15, overlap_units=3)
    ready, waiting = [r[0] for r in c.execute("SELECT article_id FROM articles ORDER BY article_id")]
    c.execute("UPDATE rag_index_status s SET bm25_status = 'ready' FROM rag_chunks ch "
              "WHERE ch.chunk_id = s.chunk_id AND ch.article_id = %s", (ready,))
    # Bài crawler vừa nạp (báo khác), chưa NER/chunk: không được tính.
    raw = {**arts[0], "url": "https://tuoitre.vn/moi.htm", "source": "tuoitre"}
    raw["article_id"] = contract.article_id_for(raw["url"])
    sink.upsert_articles(c, [contract.validate_article(raw, known_sources={"tuoitre"},
                                                       now=datetime(2026, 11, 4, tzinfo=UTC))], via="import_jsonl")
    c.execute("INSERT INTO events (event_id, first_seen, last_seen, size, n_sources, sources, display_name, name_source, "
              "medoid_title, algo_version, model_version) VALUES "
              "(%s, '2026-09-10', '2026-09-10', 2, 2, '{}', 'x', 'model', 'Tin thật', 'v', 'm'), "
              "('E20260910-bbbbbbbb', '2026-09-10', '2026-09-10', 2, 1, '{}', 'y', 'model', 'Chưa vào kho', 'v', 'm')",
              (EVENT,))
    c.execute("INSERT INTO event_articles (event_id, article_id, method) VALUES "
              "(%s, %s, 'import'), (%s, %s, 'import'), (%s, %s, 'import')",
              (EVENT, ready, "E20260910-bbbbbbbb", waiting, "E20260910-bbbbbbbb", raw["article_id"]))
    return c


def _ctx(conn, **kw):
    snap = corpus_snapshot(conn, "rag_v1")
    return T.ToolContext(conn=conn, question="có bao nhiêu bài", filters={}, search=lambda *a, **k: [],
                         snapshot=lambda: snap, **kw)


def test_dem_bai_khop_snapshot_kho_rag(kho):
    c = _ctx(kho)
    out, err = T.run_tool(c, "count_articles", {}, allowed=set(T.HANDLERS))
    assert err is None and out["count"] == 1 == c.snapshot()["articles"]
    out, _ = T.run_tool(_ctx(kho, hidden_sources=["VnExpress"]), "count_articles", {}, allowed=set(T.HANDLERS))
    assert out["count"] == 0


def test_su_kien_noi_bat_chi_lay_su_kien_co_bai_trong_kho(kho):
    out, _ = T.run_tool(_ctx(kho), "top_events", {}, allowed=set(T.HANDLERS))
    assert [e["event_id"] for e in out["events"]] == [EVENT]
    out, _ = T.run_tool(_ctx(kho, hidden_sources=["vnexpress"]), "top_events", {}, allowed=set(T.HANDLERS))
    assert out["events"] == []


def test_pham_vi_kho_tung_bao_khong_tinh_bai_chua_index(kho):
    out, _ = T.run_tool(_ctx(kho), "corpus_info", {}, allowed=set(T.HANDLERS))
    assert "vnexpress: 1 bài" in out["text"] and "tuoitre" not in out["text"]



def test_su_kien_noi_bat_dem_bai_va_bao_chi_tren_bai_trong_kho(kho):
    # Sự kiện ghi size=2, n_sources=2 nhưng chỉ 1 bài đã vào kho RAG → câu dữ liệu nói đúng 1 bài của 1 báo.
    out, _ = T.run_tool(_ctx(kho), "top_events", {}, allowed=set(T.HANDLERS))
    assert out["events"][0]["text"].startswith("Tin thật: 1 bài của 1 báo")
