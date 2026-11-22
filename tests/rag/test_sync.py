import json
from types import SimpleNamespace

import psycopg
import pytest

from eventrank.rag import dense, sync
from eventrank.rag.text import build_full_text, text_hash


class _FakePredictor:
    def __init__(self):
        self.calls = []

    def predict_texts(self, texts):
        self.calls.append(texts)
        out = []
        for text in texts:
            needle = "Hà Nội"
            if needle in text:
                s = text.index(needle)
                out.append([{"text": needle, "label": "LOC", "start_char": s, "end_char": s + len(needle)}])
            else:
                out.append([])
        return out


def test_sync_rag_dry_run_reports_pending_without_calling_models(monkeypatch):
    aid = "a" * 64
    plan = {
        "requested": 1,
        "missing_article_ids": [],
        "already_ready_ids": [],
        "need_ner_articles": [
            {"article_id": aid, "canonical_text": "Tiêu đề: Tin Hà Nội", "text_hash": "0" * 64},
        ],
        "need_rechunk_articles": [],
        "pending_index_ids": [],
    }
    monkeypatch.setattr(sync, "inspect_articles", lambda *a, **kw: plan)
    monkeypatch.setattr(sync, "_pending_counts", lambda *a, **kw: (0, 0))
    monkeypatch.setattr(sync, "_preparation_lock", lambda conn, **kw: _noop_ctx())

    cfg = {
        "index_version": "rag_v1",
        "chunking": {"max_units": 320, "overlap_units": 48},
        "dense": {"url": "http://127.0.0.1:6333", "collection": "col", "batch_size": 32, "concurrency": 4},
        "bm25": {"root": "data/rag/bm25"},
    }
    res = sync.sync_rag(object(), cfg, article_ids=[aid], dry_run=True)
    assert res["dry_run"] is True
    assert res["ner_articles"] == 1
    assert res["qdrant_embedded"] == 0
    assert res["bm25_rebuilt"] is False


class _noop_ctx:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_dense_sync_delta_validates_invariants_and_updates_binding(monkeypatch):
    records = [
        {
            "chunk_id": "11111111-1111-5111-8111-111111111111",
            "article_id": "a" * 64,
            "text": "Tiêu đề: Tin mới",
            "start_char": 0,
            "end_char": 16,
            "chunking_version": "ws-320-48",
            "title": "Tin mới",
            "url": "https://example.com/1",
            "source": "vnexpress",
            "published_at": "2026-09-18T10:00:00+00:00",
        }
    ]
    model = SimpleNamespace(
        config={"embedding": {
            "model": "Qwen/Qwen3-Embedding-0.6B",
            "revision": "rev1",
            "dimension": 4,
            "max_length": 2048,
            "instruction": "q",
        }},
    )
    binding = dense._binding(records, model, "rag_v1")
    old_binding = {**binding, "corpus_sha256": "old", "documents": 0}
    info = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors=dense.qm.VectorParams(size=4, distance=dense.qm.Distance.COSINE)),
            metadata={"binding": old_binding, "published": True},
        )
    )
    deleted_calls = []
    updated_meta = []

    class _FakeQdrant:
        def collection_exists(self, name):
            return True

        def get_collection(self, name):
            return info

        def delete(self, collection_name, points_selector, wait):
            deleted_calls.append((collection_name, points_selector.points, wait))

        def count(self, collection_name, exact=True):
            return SimpleNamespace(count=1)

        def update_collection(self, collection_name, metadata):
            updated_meta.append((collection_name, metadata))

    class _FakeCursor:
        def fetchall(self):
            return [(records[0]["chunk_id"],)]

        def __iter__(self):
            return iter([(records[0]["chunk_id"],)])

    class _FakeConn:
        def execute(self, sql, params=None):
            return _FakeCursor()

    monkeypatch.setattr(dense, "_preparation_lock", lambda conn: _noop_ctx())
    monkeypatch.setattr(dense, "_snapshot", lambda conn, ver: records)
    monkeypatch.setattr(dense, "_index_records", lambda *a, **kw: (1, 1))

    res = dense.sync_delta(
        _FakeConn(),
        _FakeQdrant(),
        model,
        collection="col",
        index_version="rag_v1",
        concurrency=4,
        delete_chunk_ids=["22222222-2222-5222-8222-222222222222"],
    )
    assert res["deleted"] == 1
    assert res["embedded"] == 1
    assert res["concurrency"] == 4
    assert deleted_calls[0][1] == ["22222222-2222-5222-8222-222222222222"]
    assert updated_meta[0][1]["binding"]["corpus_sha256"] == binding["corpus_sha256"]
    assert json.loads(json.dumps(res))["published"] is True


def test_build_full_text_hash_stable():
    t1 = build_full_text({"title": "A", "sapo": "B", "content_text": "C"})
    t2 = build_full_text({"title": "A", "sapo": "B", "content_text": "C"})
    assert text_hash(t1) == text_hash(t2)


# ---------------------------------------------------------------- thứ tự ghi an toàn khi DB lỗi giữa chừng
def _cfg():
    return {
        "index_version": "rag_v1",
        "chunking": {"max_units": 320, "overlap_units": 48},
        "dense": {"url": "http://127.0.0.1:6333", "collection": "col", "batch_size": 32, "concurrency": 4},
        "bm25": {"root": "data/rag/bm25"},
    }


def test_danh_dau_pending_truoc_khi_xoa_point_qdrant(monkeypatch):
    aid, old = "a" * 64, "33333333-3333-5333-8333-333333333333"
    text = "Tiêu đề: Tin Hà Nội\n\nSapo: Ngắn\n\nNội dung:\nThân bài."
    plan = {"requested": 1, "missing_article_ids": [], "already_ready_ids": [], "need_ner_articles": [],
            "need_rechunk_articles": [{"article_id": aid, "canonical_text": text,
                                       "text_hash": text_hash(text), "entities": []}],
            "pending_index_ids": []}
    events = []
    monkeypatch.setattr(sync, "inspect_articles", lambda *a, **kw: plan)
    monkeypatch.setattr(sync, "_pending_counts", lambda *a, **kw: (0, 0))
    monkeypatch.setattr(sync, "_preparation_lock", lambda conn, **kw: _noop_ctx())

    class _Conn:
        def execute(self, sql, params=None):
            if sql.startswith("SELECT a.article_id, a.title"):     # pha ghi kiểm lại hash: bài không đổi
                return SimpleNamespace(fetchall=lambda: [(aid, "Tin Hà Nội", "Ngắn", "Thân bài.", text_hash(text))])
            if sql.startswith("SELECT chunk_id FROM rag_chunks"):
                return iter([(old,)])
            if "UPDATE rag_index_status" in sql:
                events.append(("mark_pending", list(params[0])))
                return SimpleNamespace(rowcount=1)
            raise AssertionError(sql)

        def transaction(self):
            events.append("transaction")
            raise RuntimeError("Postgres mất kết nối")

    class _Qdrant:
        def collection_exists(self, name):
            return True

        def get_collection(self, name):
            return SimpleNamespace(config=SimpleNamespace(metadata={"published": True, "binding": {}}))

        def update_collection(self, collection_name, metadata):
            events.append(("unpublish", metadata["published"]))

        def delete(self, collection_name, points_selector, wait):
            events.append(("qdrant_delete", list(points_selector.points)))

    with pytest.raises(RuntimeError):
        sync.sync_rag(_Conn(), _cfg(), article_ids=[aid], qdrant=_Qdrant(), model_client=object())
    # Gỡ publish dense trước khi corpus đổi (Qwen lỗi sau đó thì hybrid không thấy binding lệch).
    assert events == [("unpublish", False), ("mark_pending", [old]), ("qdrant_delete", [old]), "transaction"]


def test_preparation_lock_cho_toi_khi_khoa_ranh(monkeypatch):
    from eventrank.rag import prepare
    answers = iter([False, False, True])
    executed, slept = [], []

    class _Conn:
        def execute(self, sql, params=None):
            executed.append(sql)
            value = next(answers) if "try_advisory_lock" in sql else True
            return SimpleNamespace(fetchone=lambda: (value,))

    monkeypatch.setattr(prepare.time, "sleep", slept.append)
    with prepare._preparation_lock(_Conn(), wait_seconds=10, poll_seconds=0.5):
        pass
    assert slept == [0.5, 0.5]
    assert executed[-1].startswith("SELECT pg_advisory_unlock(")


def test_preparation_lock_mac_dinh_khong_cho(monkeypatch):
    from eventrank.rag import prepare

    class _Conn:
        def execute(self, sql, params=None):
            return SimpleNamespace(fetchone=lambda: (False,))

    with pytest.raises(ValueError, match="khác đang chạy"), prepare._preparation_lock(_Conn()):
        pass


def test_safe_error_giu_thong_diep_noi_bo_an_thong_diep_ha_tang():
    assert sync.safe_error(ValueError("corpus thay đổi")) == "ValueError: corpus thay đổi"
    leaked = sync.safe_error(psycopg.OperationalError('password authentication failed for user "eventrank"'))
    assert leaked == "OperationalError"


# ---------------------------------------------------------------- hai pha: NER không giữ khoá ghi
class _LockSpy:
    """Giả `_preparation_lock`: ghi lại lúc nào khoá đang giữ."""

    def __init__(self):
        self.held = False
        self.entered = 0

    def __call__(self, conn, **kw):
        spy = self

        class _Ctx:
            def __enter__(self):
                spy.held = True
                spy.entered += 1

            def __exit__(self, *a):
                spy.held = False
                return False
        return _Ctx()


def _two_phase_setup(monkeypatch, *, changed=False):
    aid = "b" * 64
    text = build_full_text({"title": "Tin Hà Nội", "sapo": "Ngắn", "content_text": "Thân bài."})
    plan = {"requested": 1, "missing_article_ids": [], "already_ready_ids": [], "pending_index_ids": [],
            "need_ner_articles": [{"article_id": aid, "canonical_text": text, "text_hash": text_hash(text)}],
            "need_rechunk_articles": [], "stale_ids": [], "deferred": 0, "limited": False}
    lock = _LockSpy()
    events = []
    monkeypatch.setattr(sync, "inspect_articles", lambda *a, **kw: plan)
    monkeypatch.setattr(sync, "_pending_counts", lambda *a, **kw: (0, 0))
    monkeypatch.setattr(sync, "_preparation_lock", lock)

    class _Predictor:
        def predict_texts(self, texts):
            events.append(("ner", lock.held))
            return [[] for _ in texts]

    class _Model:
        def ping_embedding(self):
            events.append(("ping", lock.held))
            return True

    current_content = "Thân bài ĐÃ SỬA." if changed else "Thân bài."

    class _Conn:
        def execute(self, sql, params=None):
            if sql.startswith("SELECT a.article_id, a.title"):
                events.append(("recheck", lock.held))
                return SimpleNamespace(fetchall=lambda: [(aid, "Tin Hà Nội", "Ngắn", current_content, None)])
            if sql.startswith("SELECT chunk_id FROM rag_chunks"):
                return iter([])
            raise AssertionError(sql)

        def transaction(self):
            events.append(("write", lock.held))
            raise RuntimeError("dừng ở đây: đủ để kiểm thứ tự")

    class _Qdrant:
        def collection_exists(self, name):
            return True

        def get_collection(self, name):
            return SimpleNamespace(config=SimpleNamespace(metadata={"published": False}))

    return _Conn(), _Predictor(), _Model(), _Qdrant(), events, lock


def test_ner_va_ping_qwen_chay_ngoai_khoa_ghi_roi_moi_ghi_trong_khoa(monkeypatch):
    conn, pred, model, q, events, lock = _two_phase_setup(monkeypatch)
    with pytest.raises(RuntimeError, match="dừng ở đây"):
        sync.sync_rag(conn, _cfg(), ner_predictor=pred, qdrant=q, model_client=model)
    assert events == [("ner", False), ("ping", False), ("recheck", True), ("write", True)]
    assert lock.entered == 1 and lock.held is False


def test_bai_bi_sua_giua_hai_pha_bi_bo_de_lan_sau(monkeypatch):
    conn, pred, model, q, events, _ = _two_phase_setup(monkeypatch, changed=True)
    res = sync.sync_rag(conn, _cfg(), ner_predictor=pred, qdrant=q, model_client=model)
    assert res["skipped_changed"] == 1 and res["chunks_inserted"] == 0 and res["limited"] is True
    assert ("write", True) not in events


def test_max_articles_phai_duong():
    with pytest.raises(ValueError, match="max_articles"):
        sync.inspect_articles(object(), None, max_articles=0)


def test_cli_max_articles_truyen_xuong_sync(monkeypatch):
    seen = {}
    monkeypatch.setattr(sync.db, "connect", lambda: _noop_ctx())
    monkeypatch.setattr(sync, "sync_rag", lambda conn, cfg, **kw: seen.update(kw) or {"ok": 1})
    assert sync.main(["--max-articles", "25"]) == 0
    assert seen["max_articles"] == 25 and seen["article_ids"] is None
