"""Đồng bộ RAG tăng dần: NER BamiBERT → chia chunk → delta Qdrant (Qwen) → snapshot BM25.

    uv run --no-sync python -m eventrank.rag.sync --max-articles 200      (make rag-sync)

Chạy theo HAI PHA để chatbot không bị chặn suốt cả lượt (máy không có CUDA: BamiBERT chạy CPU, rất lâu):

1. **Pha tính — KHÔNG giữ khoá ghi** (`_preparation_lock`): tìm bài cần làm, chạy NER, chia chunk trong RAM, ping
   dịch vụ embedding để Modal bật Qwen trước. Chat vẫn đọc chỉ mục cũ bình thường.
2. **Pha ghi — giữ khoá ghi**: kiểm lại hash văn bản của từng bài (crawler sửa bài giữa chừng → bỏ bài đó, lượt sau
   làm lại), ghi NER/chunk, `dense.sync_delta`, dựng lại BM25. Khoá phải giữ ở pha này vì `hybrid.search` kiểm
   `status == 'ready'` cho từng nhánh; trong lúc đó chat nhận `IndexBusyError` ("đang đồng bộ").

Quét toàn kho bắt cả bài crawler sửa nội dung SAU khi đã có NER/chunk (`articles.updated_at > article_ner.updated_at`).
Bài sửa mà văn bản ghép không đổi (chỉ đổi tác giả, cờ chất lượng…) chỉ được "chạm" `article_ner.updated_at` để
không bị đếm là bài chờ mãi. `max_articles` giới hạn số bài mỗi lượt, ưu tiên bài **mới đăng trước**.
"""
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

NER_BATCH = 16          # số bài mỗi lần gọi NER ở pha tính (để báo tiến độ; BamiBERT tự chia lô nhỏ hơn)


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


# Bài bị sửa sau lần NER: `articles.updated_at` hiện tại KHÁC bản đã dùng (`article_ner.source_updated_at`, migration 011).
# So bằng chứ không so `>`: crawler ghi cả lô trong một transaction, `updated_at` = giờ BẮT ĐẦU lô, có thể sớm hơn lúc
# sync commit. Dòng cũ chưa có `source_updated_at` (NULL) → tiêu chí cũ.
_STALE = ("((n.source_updated_at IS NULL AND a.updated_at > n.updated_at) "
          "OR (n.source_updated_at IS NOT NULL AND a.updated_at IS DISTINCT FROM n.source_updated_at))")
# Bài cần đồng bộ khi quét toàn kho: chưa NER, bị sửa sau lần NER, chưa có chunk, hoặc có chunk chưa ready/khác phiên
# bản/thiếu dòng rag_index_status. PHẢI cùng tiêu chí với `_CHUNK_INFO` (không thì `limited` luôn True, chạy rỗng mãi).
_PENDING_WHERE = (
    "n.article_id IS NULL OR " + _STALE + " "
    "OR NOT EXISTS (SELECT 1 FROM rag_chunks c WHERE c.article_id = a.article_id) "
    "OR EXISTS ("
    "  SELECT 1 FROM rag_chunks c LEFT JOIN rag_index_status s USING(chunk_id) "
    "  WHERE c.article_id = a.article_id "
    "  AND (s.chunk_id IS NULL OR s.index_version <> %(iv)s "
    "       OR s.bm25_status <> 'ready' OR s.qdrant_status <> 'ready'"
    "       OR (%(cv)s::text IS NOT NULL AND c.chunking_version <> %(cv)s))"
    ")"
)
_SELECT = (
    "SELECT a.article_id, a.title, a.sapo, a.content_text, n.text_hash, n.entities, "
    "(n.article_id IS NOT NULL AND " + _STALE + ") AS stale "
    "FROM articles a LEFT JOIN article_ner n USING(article_id) "
)
_ORDER = " ORDER BY a.published_at DESC NULLS LAST, a.article_id"
# (số chunk, mọi chunk ready ở index hiện hành, mọi chunk cùng chunking_version, mọi chunk CÓ dòng rag_index_status).
# LEFT JOIN + COALESCE: bool_and bỏ qua NULL, nên chunk thiếu dòng status phải tính là "chưa ready" tường minh.
_CHUNK_INFO = (
    "SELECT c.article_id, count(*), "
    "bool_and(COALESCE(c.chunking_version = COALESCE(%s, c.chunking_version) "
    "AND s.index_version = %s AND s.bm25_status = 'ready' AND s.qdrant_status = 'ready', false)), "
    "bool_and(c.chunking_version = COALESCE(%s, c.chunking_version)), "
    "bool_and(s.chunk_id IS NOT NULL) "
    "FROM rag_chunks c LEFT JOIN rag_index_status s USING(chunk_id) "
    "WHERE c.article_id = ANY(%s) GROUP BY c.article_id"
)


def inspect_articles(conn, article_ids: list[str] | None = None, *,
                     index_version: str = "rag_v1",
                     chunk_version: str | None = None,
                     max_articles: int | None = None) -> dict:
    """Phân loại bài được hỏi (hoặc mọi bài chờ/bị sửa) thành: thiếu, đã ready, cần NER, cần chia lại, chờ index.

    `max_articles`: tối đa chừng này bài CẦN NER/CHIA LẠI mỗi lượt, mới đăng trước; phần dư đếm ở `deferred`
    và `limited = True` (bộ lập lịch dựa vào đó để chạy tiếp lô sau).
    """
    if max_articles is not None and (type(max_articles) is not int or max_articles < 1):
        raise ValueError("max_articles phải là số nguyên >= 1")
    clean_ids = _dedup_ids(article_ids)
    empty = {
        "requested": 0, "missing_article_ids": [], "already_ready_ids": [],
        "need_ner_articles": [], "need_rechunk_articles": [], "pending_index_ids": [],
        "stale_ids": [], "deferred": 0, "limited": False,
    }
    full_scan_limited = False
    if clean_ids is not None:
        if not clean_ids:
            return empty
        rows = conn.execute(_SELECT + "WHERE a.article_id = ANY(%s)" + _ORDER, (clean_ids,)).fetchall()
        found_ids = {r[0] for r in rows}
        missing_ids = [aid for aid in clean_ids if aid not in found_ids]
    else:
        missing_ids = []
        params = {"iv": index_version, "cv": chunk_version}
        sql = _SELECT + "WHERE " + _PENDING_WHERE + _ORDER
        if max_articles is not None:
            sql += " LIMIT %(lim)s"
            params["lim"] = max_articles + 1      # +1 để biết còn bài cho lô sau hay không
        rows = conn.execute(sql, params).fetchall()
        if max_articles is not None and len(rows) > max_articles:
            rows, full_scan_limited = rows[:max_articles], True
        found_ids = {r[0] for r in rows}
    chunk_rows = conn.execute(
        _CHUNK_INFO, (chunk_version, index_version, chunk_version, list(found_ids)),
    ).fetchall() if found_ids else []

    chunk_info = {r[0]: (r[1], bool(r[2]), bool(r[3]), bool(r[4])) for r in chunk_rows}
    already_ready, need_ner, need_rechunk, pending_index, stale = [], [], [], [], []
    deferred = 0

    def room() -> bool:
        return max_articles is None or len(need_ner) + len(need_rechunk) < max_articles

    for aid, title, sapo, content_text, ner_hash, entities, is_stale in rows:
        full_text = build_full_text({"title": title, "sapo": sapo, "content_text": content_text})
        digest = text_hash(full_text)
        if ner_hash is None or ner_hash != digest:
            if not room():
                deferred += 1
                continue
            need_ner.append({"article_id": aid, "canonical_text": full_text, "text_hash": digest})
            continue
        if is_stale:
            # NER vẫn khớp văn bản (bài sửa trường khác) → chỉ chạm updated_at ở pha ghi.
            stale.append({"article_id": aid, "text_hash": digest})
        cnt, all_ready, same_chunk_ver, has_status = chunk_info.get(aid, (0, False, False, False))
        if cnt == 0 or not same_chunk_ver or not has_status:     # thiếu dòng status: dựng lại chunk + status
            if not room():
                deferred += 1
                continue
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
        "stale_ids": stale,
        "deferred": deferred,
        "limited": bool(deferred) or full_scan_limited,
    }


def pending_summary(conn, *, index_version: str = "rag_v1", chunk_version: str | None = None) -> dict:
    """Đếm rẻ số bài chờ đồng bộ (cùng tiêu chí quét toàn kho của `inspect_articles`, không đọc văn bản)."""
    row = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE n.article_id IS NULL) "
        "FROM articles a LEFT JOIN article_ner n USING(article_id) WHERE " + _PENDING_WHERE,
        {"iv": index_version, "cv": chunk_version},
    ).fetchone()
    return {"pending_articles": int(row[0] or 0), "without_ner": int(row[1] or 0)}


def _pending_counts(conn, index_version: str) -> tuple[int, int]:
    row = conn.execute(
        "SELECT "
        "count(*) FILTER (WHERE qdrant_status IN ('pending', 'failed') OR index_version <> %s), "
        "count(*) FILTER (WHERE bm25_status IN ('pending', 'failed') OR index_version <> %s) "
        "FROM rag_index_status",
        (index_version, index_version),
    ).fetchone()
    return int(row[0] or 0), int(row[1] or 0)


def _current_hashes(conn, article_ids: list[str]) -> dict[str, tuple[str, str | None, object]]:
    """{article_id: (hash văn bản ghép HIỆN TẠI, text_hash NER hiện tại, articles.updated_at)} — đọc lại dưới khoá ở pha
    ghi. `updated_at` đọc CÙNG LÚC với văn bản được ghi vào `article_ner.source_updated_at`: crawler sửa bài sau lúc này
    thì giá trị khác đi và bài lại thành bài chờ (không bị che bởi `now()` của lần ghi)."""
    if not article_ids:
        return {}
    rows = conn.execute(
        "SELECT a.article_id, a.title, a.sapo, a.content_text, n.text_hash, a.updated_at "
        "FROM articles a LEFT JOIN article_ner n USING(article_id) WHERE a.article_id = ANY(%s)",
        (article_ids,),
    ).fetchall()
    return {
        r[0]: (text_hash(build_full_text({"title": r[1], "sapo": r[2], "content_text": r[3]})), r[4],
               r[5] if len(r) > 5 else None)
        for r in rows
    }


def _warm_embedding(model_client) -> bool:
    """Ping Qwen để Modal khởi động container trong lúc còn ở pha tính; lỗi không chặn lượt sync."""
    ping = getattr(model_client, "ping_embedding", None)
    if ping is None:
        return False
    try:
        return bool(ping())
    except Exception:  # noqa: BLE001 -- chỉ là làm nóng; sync_delta tự báo lỗi thật nếu dịch vụ hỏng
        return False


def sync_rag(conn, config: dict, *, article_ids: list[str] | None = None,
             ner_predictor=None, qdrant=None, model_client=None,
             dry_run: bool = False, progress=None, max_articles: int | None = None) -> dict:
    """NER + chia chunk (pha tính, không khoá) rồi ghi + delta Qdrant + BM25 (pha ghi, giữ khoá)."""
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

    def report(row):
        if progress is not None:
            progress(row)

    # ------------------------------------------------------------------ pha tính: không giữ khoá ghi
    plan = inspect_articles(conn, article_ids, index_version=index_version, chunk_version=c_ver,
                            max_articles=max_articles)
    q_pending, b_pending = _pending_counts(conn, index_version)
    need_ner = plan["need_ner_articles"]
    need_rechunk = plan["need_rechunk_articles"]
    stale = plan.get("stale_ids", [])
    stats = Counter(
        requested=plan["requested"],
        already_ready=len(plan["already_ready_ids"]),
        missing_articles=len(plan["missing_article_ids"]),
        ner_articles=len(need_ner),
        rechunk_articles=len(need_rechunk),
        deferred_articles=plan.get("deferred", 0),
        skipped_changed=0,
        touched_articles=0,
        chunks_deleted=0,
        chunks_inserted=0,
        qdrant_embedded=0,
        qdrant_updated=0,
        bm25_rebuilt=False,
    )
    limited = bool(plan.get("limited", False))

    def done(**extra):
        return {**stats, "limited": limited, **extra, "seconds": round(time.perf_counter() - started, 3)}

    if not need_ner and not need_rechunk and not stale and q_pending == 0 and b_pending == 0:
        return done(dry_run=dry_run)

    if dry_run:
        return done(pending_qdrant_chunks=q_pending, pending_bm25_chunks=b_pending, dry_run=True)

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
        for offset in range(0, len(need_ner), NER_BATCH):
            batch = need_ner[offset:offset + NER_BATCH]
            predicted = ner_predictor.predict_texts([a["canonical_text"] for a in batch])
            for art, ents in zip(batch, predicted, strict=True):
                valid_ents = validate_entities(art["canonical_text"], ents)
                ner_results.append({**art, "entities": valid_ents, "new_ner": True})
            report({"phase": "ner", "done": min(offset + NER_BATCH, len(need_ner)), "total": len(need_ner)})

        prepared = []
        for art in ner_results + [{**a, "new_ner": False} for a in need_rechunk]:
            chunks = make_chunks(art["article_id"], art["canonical_text"], art["entities"],
                                 max_units=max_units, overlap_units=overlap_units)
            prepared.append((art, chunks))
        if prepared or q_pending > 0:
            stats["embedding_warmed"] = _warm_embedding(model_client)

        # -------------------------------------------------------------- pha ghi: giữ khoá ghi
        with _preparation_lock(conn, wait_seconds=lock_wait):
            current = _current_hashes(conn, [a["article_id"] for a, _ in prepared] + [s["article_id"] for s in stale])
            to_write = []
            for art, chunks in prepared:
                now_digest, now_ner, source_at = current.get(art["article_id"], (None, None, None))
                art["source_updated_at"] = source_at
                # Bài đổi giữa hai pha (hoặc NER bị tiến trình khác thay) → bỏ, lượt sau làm lại từ đầu.
                if now_digest != art["text_hash"] or (not art["new_ner"] and now_ner != art["text_hash"]):
                    stats["skipped_changed"] += 1
                    continue
                to_write.append((art, chunks))
            if stats["skipped_changed"]:
                limited = True

            if to_write:
                # Corpus sắp đổi → binding dense cũ không còn khớp BM25 sẽ dựng lại. Gỡ "published" trước: Qwen lỗi giữa
                # chừng thì hybrid thấy nhánh dense "chưa publish" (fallback BM25 được) thay vì binding lệch
                # (HybridIntegrityError). `dense.sync_delta` thành công sẽ publish lại.
                if qdrant.collection_exists(dense_cfg["collection"]):
                    meta = qdrant.get_collection(dense_cfg["collection"]).config.metadata or {}
                    if meta.get("published"):
                        qdrant.update_collection(dense_cfg["collection"], metadata={**meta, "published": False})
                        stats["dense_unpublished"] = True
                replace_aids = [a["article_id"] for a, _ in to_write]
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
                    new_ner = [a for a, _ in to_write if a["new_ner"]]
                    if new_ner:
                        with conn.cursor() as cur:
                            cur.executemany(
                                _NER_UPSERT,
                                [
                                    (r["article_id"], r["canonical_text"], r["text_hash"],
                                     ner_version, Jsonb(r["entities"]), r["source_updated_at"])
                                    for r in new_ner
                                ],
                            )
                    all_chunks = [c for _, chunks in to_write for c in chunks]
                    if all_chunks:
                        with conn.cursor() as cur:
                            cur.executemany(_CHUNK_INSERT, all_chunks)
                            cur.executemany(
                                "INSERT INTO rag_index_status (chunk_id, index_version) VALUES (%s, %s)",
                                [(c["chunk_id"], index_version) for c in all_chunks],
                            )
                    stats["chunks_inserted"] = len(all_chunks)

            # Chạm: NER vẫn khớp văn bản đọc dưới khoá → ghi bản đã dùng (source_updated_at đọc cùng lúc, KHÔNG now()).
            touch = []
            for st in stale:
                now_digest, now_ner, source_at = current.get(st["article_id"], (None, None, None))
                if now_digest == st["text_hash"] and now_ner == st["text_hash"]:
                    touch.append((source_at, st["article_id"], st["text_hash"]))
            if touch:
                with conn.cursor() as cur:
                    cur.executemany("UPDATE article_ner SET source_updated_at = %s, updated_at = now() "
                                    "WHERE article_id = %s AND text_hash = %s", touch)
                stats["touched_articles"] = len(touch)

            # BM25 dựng lại NGAY sau khi DB đổi chunk, TRƯỚC Qwen: nếu Modal lỗi giữa chừng, snapshot BM25 trên đĩa vẫn
            # khớp Postgres (không trỏ chunk_id đã xoá → chat không ném HybridIntegrityError); nhánh dense chỉ thấy
            # chunk qdrant_status='ready' và lượt sau embed nốt.
            q_pending, b_pending = _pending_counts(conn, index_version)
            if b_pending > 0 or stats["chunks_deleted"] > 0 or stats["chunks_inserted"] > 0:
                report({"phase": "bm25", "pending": b_pending})
                bm25_res = bm25.build_from_db(
                    conn, bm25_root, index_version=index_version, progress=progress,
                )
                stats["bm25_rebuilt"] = not bm25_res["reused"]
                stats["bm25_status_updated"] = bm25_res["status_updated"]
                if stats["bm25_rebuilt"]:
                    stats["bm25_pruned"] = len(bm25.prune_snapshots(bm25_root, keep=keep_snapshots))

            q_pending, _ = _pending_counts(conn, index_version)
            if q_pending > 0:
                report({"phase": "dense", "pending": q_pending})
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

        return done(dry_run=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", default="configs/rag.yaml")
    parser.add_argument("--article-ids", nargs="*", help="Danh sách article_id cần đồng bộ (bỏ trống = quét toàn DB)")
    parser.add_argument("--max-articles", type=int, default=None,
                        help="Tối đa chừng này bài cần NER/chia lại trong lượt này, mới đăng trước (bỏ trống = tất cả)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.max_articles is not None and args.max_articles < 1:
        parser.error("--max-articles phải >= 1")
    try:
        config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
        with db.connect() as conn:
            result = sync_rag(
                conn, config,
                article_ids=args.article_ids if args.article_ids else None,
                dry_run=args.dry_run,
                max_articles=args.max_articles,
                progress=lambda row: print(json.dumps(row, ensure_ascii=False), flush=True),
            )
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 -- sanitize failures at CLI boundary
        print(f"RAG sync thất bại: {safe_error(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
