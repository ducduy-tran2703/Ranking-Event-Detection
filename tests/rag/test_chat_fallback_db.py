"""Tích hợp: Qwen/Modal lỗi SAU khi sync đã commit chunk mới (dense bị gỡ "published") → lượt chat qua hàng đợi
(`ChatWorker.run_once`, retriever hybrid thật trên Postgres tạm) vẫn có kết quả `bm25_only`, không `failed`.

Không gọi GPU/Modal/mạng: Qdrant `:memory:`, embedding giả, LLM giả, tokenizer giả.
"""
import json
from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient
from test_context_generation import Counter
from test_rag_dense import Encoder
from test_sync_db import _cfg, _Predictor, _run, corpus  # noqa: F401 -- corpus là fixture

from eventrank.accounts import cli
from eventrank.common import db
from eventrank.rag import bm25, chat, hybrid, sync
from eventrank.rag.models import load_model_config
from eventrank.rag.pipeline import RAGPipeline


class _FailingEncoder(Encoder):
    def embed(self, texts, *, input_type):
        raise RuntimeError("Model service returned HTTP 503")


def _llm():
    spec = load_model_config({})
    spec["llm"]["max_model_len"] = 20000

    def chat_fn(messages, *, max_tokens, response_schema=None, temperature=0.0):
        return {"content": json.dumps({"status": "answered", "claims": [
            {"text": "Hà Nội mở tuyến buýt mới.", "evidence": [{"id": 1, "quote": "Hà Nội"}]}]}),
            "finish_reason": "stop", "usage": {}}
    return SimpleNamespace(config=spec, chat=chat_fn, ping_embedding=lambda: True, embed=Encoder().embed)


def test_qwen_loi_sau_commit_chat_qua_hang_doi_van_tra_bm25_only(corpus, pg_url, tmp_path):  # noqa: F811
    c, q = corpus, QdrantClient(":memory:")
    cfg = {**_cfg(tmp_path), "retrieval": {"branch_limit": 30, "rrf_k": 60}, "generation": {}}
    _run(c, tmp_path, q)
    aid = c.execute("SELECT article_id FROM articles WHERE title LIKE 'Hà Nội%%' LIMIT 1").fetchone()[0]
    c.execute("UPDATE articles SET content_text = content_text || ' Bổ sung tin Hà Nội.', updated_at = now() "
              "WHERE article_id = %s", (aid,))
    with pytest.raises(RuntimeError):
        sync.sync_rag(c, cfg, ner_predictor=_Predictor(), qdrant=q, model_client=_FailingEncoder())
    assert not q.get_collection(cfg["dense"]["collection"]).config.metadata.get("published")

    uid = cli.create_user(c, "hoi@example.com", "Người hỏi", "mat-khau-dai-123")
    msg = chat.ask(c, uid, "Hà Nội mở tuyến buýt nào?")

    def factory(conn):
        model = _llm()
        retr = hybrid.HybridRetriever(conn, cfg, bm25_index=bm25.BM25Index(cfg["bm25"]["root"]), qdrant=q,
                                      model=model)
        return RAGPipeline(conn, cfg, retriever=retr, model=model, counter=Counter())
    worker = chat.ChatWorker(pg_url, factory)
    assert worker.run_once() is True
    with db.connect(pg_url) as conn:
        status, mode, degraded, error = conn.execute(
            "SELECT status, retrieval_mode, degraded, error FROM rag_messages WHERE message_id = %s",
            (msg["message_id"],)).fetchone()
    assert status != "failed", error
    assert mode == "bm25_only" and degraded is True
