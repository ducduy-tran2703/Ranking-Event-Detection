"""Incremental RAG sync worker: NER -> chunking -> Qdrant delta -> BM25 snapshot."""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

import yaml
from psycopg.types.json import Jsonb
from qdrant_client import QdrantClient
from qdrant_client import models as qm

from eventrank.common import db
from eventrank.rag import bm25, dense
from eventrank.rag.chunking import chunking_version, make_chunks
from eventrank.rag.models import ModelClient
from eventrank.rag.ner import ner_from_config
from eventrank.rag.prepare import _CHUNK_INSERT, _NER_UPSERT, _preparation_lock
from eventrank.rag.text import build_full_text, text_hash, validate_entities


def safe_error(exc: BaseException) -> str:
    """Chuỗi lỗi an toàn để trả qua API/log.

    Chỉ giữ thông điệp của ValueError/RuntimeError thuần (guard do chính code RAG ném, không chứa
    khoá). Lỗi của driver/thư viện (psycopg, httpx, qdrant...) có thể chứa host, user, URL → chỉ tên lớp.
    """
    if type(exc) in (ValueError, RuntimeError):
        return f"{type(exc).__name__}: {exc}"
    return type(exc).__name__


def _dedup_ids(article_ids: list[str] | None) -> list[str] | None:
    if article_ids is None:
        return None
    seen, out = set(), []
    for raw in article_ids:
        aid = str(raw).strip()
        if aid and aid not in seen:
            seen.add(aid)
            out.append(aid)
    return out


def inspect_articles(conn, article_ids: list[str] | None = None, *,
                     index_version: str = "rag_v1",
                     chunk_version: str | None = None) -> dict:
    """Classify requested (or all pending/modified) articles into missing, ready, or needing sync."""
    clean_ids = _dedup_ids(article_ids)
    if clean_ids is not None:
        if not clean_ids:
            return {
                "requested": 0, "missing_article_ids": [], "already_ready_ids": [],
                "need_ner_articles": [], "need_rechunk_articles": [], "pending_index_ids": [],
            }
        rows = conn.execute(
            "SELECT a.article_id, a.title, a.sapo, a.content_text, "
            "n.canonical_text, n.text_hash, n.entities "
            "FROM articles a LEFT JOIN article_ner n USING(article_id) "
            "WHERE a.article_id = ANY(%s) ORDER BY a.article_id",
            (clean_ids,),
        ).fetchall()
        found_ids = {r[0] for r in rows}
        missing_ids = [aid for aid in clean_ids if aid not in found_ids]
        chunk_rows = conn.execute(
            "SELECT c.article_id, count(*), "
            "bool_and(c.chunking_version = COALESCE(%s, c.chunking_version) "
            "AND s.index_version = %s AND s.bm25_status = 'ready' AND s.qdrant_status = 'ready'), "
            "bool_and(c.chunking_version = COALESCE(%s, c.chunking_version)) "
            "FROM rag_chunks c JOIN rag_index_status s USING(chunk_id) "
            "WHERE c.article_id = ANY(%s) GROUP BY c.article_id",
            (chunk_version, index_version, chunk_version, list(found_ids)),
        ).fetchall() if found_ids else []
    else:
        missing_ids = []
        rows = conn.execute(
            "SELECT a.article_id, a.title, a.sapo, a.content_text, "
            "n.canonical_text, n.text_hash, n.entities "
            "FROM articles a LEFT JOIN article_ner n USING(article_id) "
            "WHERE n.article_id IS NULL "
            "OR NOT EXISTS (SELECT 1 FROM rag_chunks c WHERE c.article_id = a.article_id) "
            "OR EXISTS ("
            "  SELECT 1 FROM rag_chunks c LEFT JOIN rag_index_status s USING(chunk_id) "
            "  WHERE c.article_id = a.article_id "
            "  AND (s.chunk_id IS NULL OR s.index_version <> %s "
            "       OR s.bm25_status <> 'ready' OR s.qdrant_status <> 'ready'"
            "       OR (%s::text IS NOT NULL AND c.chunking_version <> %s))"
            ") ORDER BY a.article_id",
            (index_version, chunk_version, chunk_version),
        ).fetchall()
        found_ids = {r[0] for r in rows}
        chunk_rows = conn.execute(
            "SELECT c.article_id, count(*), "
            "bool_and(c.chunking_version = COALESCE(%s, c.chunking_version) "
            "AND s.index_version = %s AND s.bm25_status = 'ready' AND s.qdrant_status = 'ready'), "
            "bool_and(c.chunking_version = COALESCE(%s, c.chunking_version)) "
            "FROM rag_chunks c JOIN rag_index_status s USING(chunk_id) "
            "WHERE c.article_id = ANY(%s) GROUP BY c.article_id",
            (chunk_version, index_version, chunk_version, list(found_ids)),
        ).fetchall() if found_ids else []

    chunk_info = {r[0]: (r[1], bool(r[2]), bool(r[3])) for r in chunk_rows}
    already_ready, need_ner, need_rechunk, pending_index = [], [], [], []
    for aid, title, sapo, content_text, _canon, ner_hash, entities in rows:
        full_text = build_full_text({"title": title, "sapo": sapo, "content_text": content_text})
        digest = text_hash(full_text)
        if ner_hash is None or ner_hash != digest:
            need_ner.append({"article_id": aid, "canonical_text": full_text, "text_hash": digest})
            continue
        cnt, all_ready, same_chunk_ver = chunk_info.get(aid, (0, False, False))
        if cnt == 0 or not same_chunk_ver:
            need_rechunk.append({
                "article_id": aid, "canonical_text": full_text,
                "text_hash": digest, "entities": entities,
            })
        elif not all_ready:
            pending_index.append(aid)
        else:
            already_ready.append(aid)

    return {
        "requested": len(clean_ids) if clean_ids is not None else len(rows),
        "missing_article_ids": missing_ids,
        "already_ready_ids": already_ready,
        "need_ner_articles": need_ner,
        "need_rechunk_articles": need_rechunk,
        "pending_index_ids": pending_index,
    }


def _pending_counts(conn, index_version: str) -> tuple[int, int]:
    row = conn.execute(
        "SELECT "
        "count(*) FILTER (WHERE qdrant_status IN ('pending', 'failed') OR index_version <> %s), "
        "count(*) FILTER (WHERE bm25_status IN ('pending', 'failed') OR index_version <> %s) "
        "FROM rag_index_status",
        (index_version, index_version),
    ).fetchone()
    return int(row[0] or 0), int(row[1] or 0)


def sync_rag(conn, config: dict, *, article_ids: list[str] | None = None,
             ner_predictor=None, qdrant=None, model_client=None,
             dry_run: bool = False, progress=None) -> dict:
    """Run incremental NER, chunking, Qdrant delta, and BM25 snapshot rebuild."""
    started = time.perf_counter()
    index_version = config["index_version"]
    chunk_cfg = config["chunking"]
    max_units = int(chunk_cfg["max_units"])
    overlap_units = int(chunk_cfg["overlap_units"])
    c_ver = chunking_version(max_units, overlap_units)
    ner_cfg = config.get("ner", {})
    ner_version = ner_cfg.get("ner_version", "bamibert-s43-clean-20260929")
    dense_cfg = config["dense"]
    bm25_root = config["bm25"]["root"]
    keep_snapshots = int(config["bm25"].get("keep_snapshots", 2))
    # Chờ các lượt hỏi đáp đang giữ khoá đọc nhả ra thay vì báo lỗi ngay.
    lock_wait = float(config.get("sync", {}).get("lock_wait_seconds", 600))

    with _preparation_lock(conn, wait_seconds=lock_wait):
        plan = inspect_articles(conn, article_ids, index_version=index_version, chunk_version=c_ver)
        q_pending, b_pending = _pending_counts(conn, index_version)
        need_ner = plan["need_ner_articles"]
        need_rechunk = plan["need_rechunk_articles"]
        stats = Counter(
            requested=plan["requested"],
            already_ready=len(plan["already_ready_ids"]),
            missing_articles=len(plan["missing_article_ids"]),
            ner_articles=len(need_ner),
            rechunk_articles=len(need_rechunk),
            chunks_deleted=0,
            chunks_inserted=0,
            qdrant_embedded=0,
            qdrant_updated=0,
            bm25_rebuilt=False,
        )

        if not need_ner and not need_rechunk and q_pending == 0 and b_pending == 0:
            return {**stats, "dry_run": dry_run, "seconds": round(time.perf_counter() - started, 3)}

        if dry_run:
            return {
                **stats,
                "pending_qdrant_chunks": q_pending,
                "pending_bm25_chunks": b_pending,
                "dry_run": True,
                "seconds": round(time.perf_counter() - started, 3),
            }

        with ExitStack() as stack:
            if need_ner and ner_predictor is None:
                ner_predictor = ner_from_config(ner_cfg)
            if qdrant is None:
                qdrant = QdrantClient(url=dense_cfg["url"], timeout=120)
                stack.callback(qdrant.close)
            if model_client is None:
                model_client = ModelClient.from_env()
                stack.callback(model_client.close)

            ner_results = []
            if need_ner:
                predicted = ner_predictor.predict_texts([a["canonical_text"] for a in need_ner])
                for art, ents in zip(need_ner, predicted, strict=True):
                    valid_ents = validate_entities(art["canonical_text"], ents)
                    ner_results.append({**art, "entities": valid_ents})

            to_chunk = ner_results + need_rechunk
            if to_chunk:
                replace_aids = [a["article_id"] for a in to_chunk]
                old_chunk_ids = [
                    str(r[0]) for r in conn.execute(
                        "SELECT chunk_id FROM rag_chunks WHERE article_id = ANY(%s)",
                        (replace_aids,),
                    )
                ]
                # Hạ status trước (autocommit) rồi mới xoá point: nếu transaction bên dưới lỗi,
                # DB không còn khẳng định "ready" cho vector đã mất; lượt sync sau embed lại.
                if old_chunk_ids:
                    conn.execute(
                        "UPDATE rag_index_status SET qdrant_status='pending', updated_at=now() "
                        "WHERE chunk_id = ANY(%s::uuid[])",
                        (old_chunk_ids,),
                    )
                # Xoá point cũ trước khi commit DB để Qdrant không giữ ID mồ côi sau commit.
                if old_chunk_ids and qdrant.collection_exists(dense_cfg["collection"]):
                    for offset in range(0, len(old_chunk_ids), 256):
                        qdrant.delete(
                            collection_name=dense_cfg["collection"],
                            points_selector=qm.PointIdsList(points=old_chunk_ids[offset:offset + 256]),
                            wait=True,
                        )
                    stats["chunks_deleted"] = len(old_chunk_ids)

                with conn.transaction():
                    if old_chunk_ids:
                        conn.execute(
                            "DELETE FROM rag_index_status WHERE chunk_id = ANY(%s::uuid[])",
                            (old_chunk_ids,),
                        )
                        conn.execute(
                            "DELETE FROM rag_chunks WHERE article_id = ANY(%s)",
                            (replace_aids,),
                        )
                    if ner_results:
                        with conn.cursor() as cur:
                            cur.executemany(
                                _NER_UPSERT,
                                [
                                    (r["article_id"], r["canonical_text"], r["text_hash"],
                                     ner_version, Jsonb(r["entities"]))
                                    for r in ner_results
                                ],
                            )
                    all_chunks = []
                    for art in to_chunk:
                        all_chunks.extend(
                            make_chunks(
                                art["article_id"], art["canonical_text"], art["entities"],
                                max_units=max_units, overlap_units=overlap_units,
                            )
                        )
                    if all_chunks:
                        with conn.cursor() as cur:
                            cur.executemany(_CHUNK_INSERT, all_chunks)
                            cur.executemany(
                                "INSERT INTO rag_index_status (chunk_id, index_version) VALUES (%s, %s)",
                                [(c["chunk_id"], index_version) for c in all_chunks],
                            )
                    stats["chunks_inserted"] = len(all_chunks)

            q_pending, b_pending = _pending_counts(conn, index_version)
            if q_pending > 0:
                q_res = dense.sync_delta(
                    conn, qdrant, model_client,
                    collection=dense_cfg["collection"],
                    index_version=index_version,
                    batch_size=int(dense_cfg.get("batch_size", 32)),
                    concurrency=int(dense_cfg.get("concurrency", 4)),
                    progress=progress,
                )
                stats["qdrant_embedded"] = q_res["embedded"]
                stats["qdrant_updated"] = q_res["status_updated"]

            if b_pending > 0 or stats["chunks_deleted"] > 0 or stats["chunks_inserted"] > 0:
                bm25_res = bm25.build_from_db(
                    conn, bm25_root, index_version=index_version, progress=progress,
                )
                stats["bm25_rebuilt"] = not bm25_res["reused"]
                stats["bm25_status_updated"] = bm25_res["status_updated"]
                if stats["bm25_rebuilt"]:
                    stats["bm25_pruned"] = len(bm25.prune_snapshots(bm25_root, keep=keep_snapshots))

        return {**stats, "dry_run": False, "seconds": round(time.perf_counter() - started, 3)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/rag.yaml")
    parser.add_argument("--article-ids", nargs="*", help="Danh sách article_id cần đồng bộ (bỏ trống = quét toàn DB)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
        with db.connect() as conn:
            result = sync_rag(
                conn, config,
                article_ids=args.article_ids if args.article_ids else None,
                dry_run=args.dry_run,
                progress=lambda row: print(json.dumps(row, ensure_ascii=False), flush=True),
            )
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 -- sanitize failures at CLI boundary
        print(f"RAG sync thất bại: {safe_error(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
