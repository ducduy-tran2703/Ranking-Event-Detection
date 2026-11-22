"""Silver gốc + NER → canonical text → chunk/pending trong Postgres; không gọi model/mạng.

Kiểm toàn bộ input trước khi ghi NER; commit theo lô, chạy lại idempotent. Chỉ thay chunk
cũ nếu tất cả trạng thái còn pending. Đã index/thử index thì phải chờ worker đồng bộ.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import yaml
from psycopg.types.json import Jsonb

from eventrank.common import db
from eventrank.ingest.contract import Article, article_id_for, clean_line, validate_article
from eventrank.rag.chunking import chunking_version, make_chunks
from eventrank.rag.text import build_full_text, text_hash, validate_entities

_LOCK = 0x72616770726570
_NER_UPSERT = """
INSERT INTO article_ner (article_id,canonical_text,text_hash,ner_version,entities)
VALUES (%s,%s,%s,%s,%s)
ON CONFLICT (article_id) DO UPDATE SET canonical_text=EXCLUDED.canonical_text,
text_hash=EXCLUDED.text_hash,ner_version=EXCLUDED.ner_version,entities=EXCLUDED.entities,
updated_at=now()
"""
_CHUNK_INSERT = """
INSERT INTO rag_chunks (chunk_id,article_id,chunk_index,text,start_char,end_char,chunking_version)
VALUES (%(chunk_id)s,%(article_id)s,%(chunk_index)s,%(text)s,%(start_char)s,%(end_char)s,
        %(chunking_version)s)
"""


@contextmanager
def _preparation_lock(conn, *, wait_seconds=0, poll_seconds=1.0):
    """Khoá ghi độc quyền cho preparation/BM25/dense/sync (session-level, re-entrant cùng kết nối).

    `wait_seconds>0`: chờ các lượt đọc ngắn (`index_read_lock`) hoặc tiến trình khác nhả khoá.
    """
    deadline = time.monotonic() + wait_seconds
    while not conn.execute("SELECT pg_try_advisory_lock(%s)", (_LOCK,)).fetchone()[0]:
        if time.monotonic() >= deadline:
            raise ValueError("Một tiến trình preparation RAG khác đang chạy")
        time.sleep(poll_seconds)
    try:
        yield
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK,))


class IndexBusyError(RuntimeError):
    """Index đang được ghi (sync/preparation); đọc lúc này có thể thấy BM25/Qdrant/DB lệch nhau."""


@contextmanager
def index_read_lock(conn):
    """Khoá đọc chia sẻ cùng key với `_preparation_lock`: nhiều lượt đọc song song được,
    nhưng không chồng lên lượt ghi. Không chờ: đang ghi thì báo bận ngay."""
    if not conn.execute("SELECT pg_try_advisory_lock_shared(%s)", (_LOCK,)).fetchone()[0]:
        raise IndexBusyError("RAG index is being synchronized")
    try:
        yield
    finally:
        conn.execute("SELECT pg_advisory_unlock_shared(%s)", (_LOCK,))


def _jsonl(path):
    with Path(path).open(encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise TypeError("record phải là object")
            except (ValueError, TypeError) as e:
                raise ValueError(f"{Path(path).name}:{line_no}: JSONL không hợp lệ") from e
            yield value


def _load_silver(pattern):
    paths = sorted(glob.glob(str(pattern)))
    if not paths:
        raise ValueError("Không tìm thấy file Silver theo --silver-glob")
    articles = {}
    for path in paths:
        for raw in _jsonl(path):
            aid = raw.get("article_id")
            if not isinstance(raw.get("url"), str) or aid != article_id_for(raw["url"]):
                raise ValueError(f"Silver {Path(path).name}: article_id không khớp URL")
            if aid in articles:
                raise ValueError(f"Silver trùng article_id: {aid}")
            articles[aid] = raw
    return articles, paths


def _ner_records(path, silver, db_hashes, version, stats):
    seen = set()
    now = datetime.now(UTC)
    for ner in _jsonl(path):
        aid = ner.get("article_id")
        if not isinstance(aid, str) or aid in seen:
            raise ValueError("NER thiếu hoặc trùng article_id")
        seen.add(aid)
        stats["ner_rows"] += 1
        if aid not in db_hashes:
            stats["outside_db"] += 1
            continue
        raw = silver.get(aid)
        if raw is None:
            raise ValueError(f"Thiếu Silver cho article_id {aid}")
        source = str(raw.get("source") or "").lower()
        article = validate_article(raw, known_sources={source}, now=now)
        if not isinstance(article, Article) or article.content_hash != db_hashes[aid]:
            raise ValueError(f"content_hash Silver không khớp DB: {aid}")
        if (ner.get("url") != raw["url"]
                or str(ner.get("source") or "").lower() != source
                or clean_line(ner.get("title")) != clean_line(raw.get("title"))):
            raise ValueError(f"Metadata NER/Silver không khớp: {aid}")
        text = build_full_text(raw)
        try:
            entities = validate_entities(text, ner.get("entities"))
        except (ValueError, TypeError) as e:
            raise ValueError(f"NER {aid}: {e}") from e
        if ner.get("entity_count", len(entities)) != len(entities):
            raise ValueError(f"entity_count không khớp: {aid}")
        stats["matched_articles"] += 1
        stats["entities"] += len(entities)
        yield (aid, text, text_hash(text), version, entities)
    missing = set(db_hashes) - seen
    if missing:
        raise ValueError(f"Thiếu NER cho {len(missing)} bài trong DB")


def _guard_unindexed(conn, article_ids):
    if not article_ids:
        return
    used = conn.execute(
        "SELECT count(*) FROM rag_chunks c JOIN rag_index_status s USING(chunk_id) "
        "WHERE c.article_id=ANY(%s) AND (s.bm25_status<>'pending' OR s.qdrant_status<>'pending')",
        (article_ids,)).fetchone()[0]
    if used:
        raise ValueError("Đã có chunk được index/thử index; cần đồng bộ point cũ trước khi dựng lại")


def _remove_pending_chunks(conn, article_ids):
    """Chỉ xoá dữ liệu dẫn xuất chưa index; không xoá articles/nguồn NER."""
    if not article_ids:
        return
    _guard_unindexed(conn, article_ids)
    conn.execute("DELETE FROM rag_index_status s USING rag_chunks c "
                 "WHERE s.chunk_id=c.chunk_id AND c.article_id=ANY(%s)", (article_ids,))
    conn.execute("DELETE FROM rag_chunks WHERE article_id=ANY(%s)", (article_ids,))


def _write_ner_batch(conn, batch, db_hashes, stats, dry_run):
    aids = [r[0] for r in batch]
    with conn.transaction():
        current = dict(conn.execute("SELECT article_id,content_hash FROM articles "
                                    "WHERE article_id=ANY(%s) ORDER BY article_id FOR UPDATE", (aids,)))
        if any(current.get(aid) != db_hashes[aid] for aid in aids):
            raise ValueError("content_hash DB thay đổi trong lúc nhập; chạy lại preparation")
        existing = {r[0]: r[1:] for r in conn.execute(
            "SELECT article_id,canonical_text,text_hash,ner_version,entities FROM article_ner "
            "WHERE article_id=ANY(%s) FOR UPDATE", (aids,))}
        changed = [r for r in batch if r[0] in existing and existing[r[0]] != r[1:]]
        fresh = [r for r in batch if r[0] not in existing]
        _guard_unindexed(conn, [r[0] for r in changed])
        stats["inserted"] += len(fresh)
        stats["updated"] += len(changed)
        stats["unchanged"] += len(batch) - len(fresh) - len(changed)
        if not dry_run:
            _remove_pending_chunks(conn, [r[0] for r in changed])
            with conn.cursor() as cur:
                cur.executemany(_NER_UPSERT, [(*r[:4], Jsonb(r[4])) for r in fresh + changed])


def import_ner(conn, silver_glob, ner_path, *, ner_version, dry_run=False, batch_size=200):
    """Full-corpus import; thiếu NER/bản Silver cũ → dừng trước khi ghi. Ngoài DB → bỏ qua."""
    if not ner_version.strip() or batch_size < 1:
        raise ValueError("Cần ner_version và batch_size > 0")
    stats = Counter(inserted=0, updated=0, unchanged=0, outside_db=0, entities=0)
    with _preparation_lock(conn):
        silver, paths = _load_silver(silver_glob)
        db_hashes = dict(conn.execute("SELECT article_id,content_hash FROM articles"))
        snapshot = [(Path(p), Path(p).stat().st_size, Path(p).stat().st_mtime_ns)
                    for p in [*paths, str(ner_path)]]
        # Pass 1 kiểm toàn kho; pass 2 ghi theo lô, tránh giữ gần 1 triệu entity trong RAM.
        for _ in _ner_records(ner_path, silver, db_hashes, ner_version, stats):
            pass
        batch = []
        for row in _ner_records(ner_path, silver, db_hashes, ner_version, Counter()):
            batch.append(row)
            if len(batch) >= batch_size:
                _write_ner_batch(conn, batch, db_hashes, stats, dry_run)
                batch = []
        if batch:
            _write_ner_batch(conn, batch, db_hashes, stats, dry_run)
        if any(p.stat().st_size != size or p.stat().st_mtime_ns != mtime
               for p, size, mtime in snapshot):
            raise ValueError("File nguồn đổi trong lúc nhập; các lô đã commit có thể chạy lại")
    return dict(stats)


def _chunk_article(conn, article, max_units, overlap_units, index_version, dry_run, stats):
    aid, text, digest, entities = article
    if text_hash(text) != digest:
        raise ValueError(f"text_hash canonical bị sai: {aid}")
    chunks = make_chunks(aid, text, entities, max_units=max_units, overlap_units=overlap_units)
    expected = [(c["chunk_id"], c["chunk_index"], c["text"], c["start_char"],
                 c["end_char"], c["chunking_version"]) for c in chunks]
    existing = conn.execute("SELECT chunk_id,chunk_index,text,start_char,end_char,chunking_version "
                            "FROM rag_chunks WHERE article_id=%s ORDER BY chunk_index", (aid,)).fetchall()
    same = existing == expected
    stats["articles"] += 1
    stats["oversized_chunks"] += sum(len(c["text"].split()) > max_units for c in chunks)
    stats["entities"] += len(entities)
    if same:
        stats["unchanged_chunks"] += len(chunks)
    else:
        _guard_unindexed(conn, [aid])
        stats["inserted_chunks"] += len(chunks)
        stats["replaced_chunks"] += len(existing)
    ids = [c["chunk_id"] for c in chunks]
    old_status = {r[0]: r[1:] for r in conn.execute(
        "SELECT chunk_id,index_version,bm25_status,qdrant_status FROM rag_index_status "
        "WHERE chunk_id=ANY(%s)", (ids,))}
    reset = [cid for cid, (v, _, _) in old_status.items() if v != index_version]
    if any(old_status[cid][1:] != ("pending", "pending") for cid in reset):
        raise ValueError("Đổi index_version khi đã index cần worker đồng bộ chỉ mục cũ")
    stats["new_status_rows"] += len(ids) - len(old_status)
    stats["reset_status_rows"] += len(reset)
    if dry_run:
        return
    if not same:
        _remove_pending_chunks(conn, [aid])
        with conn.cursor() as cur:
            cur.executemany(_CHUNK_INSERT, chunks)
    new_ids = ids if not same else [cid for cid in ids if cid not in old_status]
    if new_ids:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO rag_index_status (chunk_id,index_version) VALUES (%s,%s) "
                "ON CONFLICT (chunk_id) DO NOTHING", [(cid, index_version) for cid in new_ids])
    if reset:
        conn.execute("UPDATE rag_index_status SET index_version=%s,bm25_status='pending', "
                     "qdrant_status='pending',error=NULL,updated_at=now() WHERE chunk_id=ANY(%s)",
                     (index_version, reset))


def build_chunks(conn, *, max_units=320, overlap_units=48, index_version="rag_v1",
                 dry_run=False, batch_size=200):
    version = chunking_version(max_units, overlap_units)
    if not index_version.strip() or batch_size < 1:
        raise ValueError("Cần index_version và batch_size > 0")
    stats = Counter(inserted_chunks=0, unchanged_chunks=0, replaced_chunks=0,
                    new_status_rows=0, reset_status_rows=0, oversized_chunks=0)
    with _preparation_lock(conn):
        last = ""
        while True:
            with conn.transaction():
                rows = conn.execute(
                    "SELECT article_id,canonical_text,text_hash,entities FROM article_ner "
                    "WHERE article_id>%s ORDER BY article_id LIMIT %s FOR UPDATE", (last, batch_size)
                ).fetchall()
                if not rows:
                    break
                for row in rows:
                    _chunk_article(conn, row, max_units, overlap_units, index_version, dry_run, stats)
                last = rows[-1][0]
    return {**stats, "chunking_version": version, "index_version": index_version}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", choices=("ner", "chunks", "all"), default="all")
    parser.add_argument("--silver-glob", default="data/lake/silver/*/*.jsonl")
    parser.add_argument("--ner", default="data/lake/gold/gold_data.jsonl")
    parser.add_argument("--ner-version")
    parser.add_argument("--config", default="configs/rag.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--report", help="File JSON mới, không ghi đè báo cáo cũ")
    args = parser.parse_args(argv)
    if args.steps != "chunks" and not args.ner_version:
        parser.error("--ner-version là bắt buộc khi nhập NER")
    if args.dry_run and args.steps == "all":
        parser.error("Dry-run dùng --steps ner hoặc chunks riêng")
    if args.report and Path(args.report).exists():
        parser.error("File --report đã tồn tại; chọn tên mới")
    try:
        cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
        started = time.perf_counter()
        report = {"dry_run": args.dry_run, "steps": {}, "config": cfg}
        with db.connect() as conn:
            if args.steps in ("ner", "all"):
                report["steps"]["ner"] = import_ner(
                    conn, args.silver_glob, args.ner, ner_version=args.ner_version,
                    dry_run=args.dry_run, batch_size=args.batch_size)
                files = sorted(glob.glob(args.silver_glob)) + [args.ner]
                fingerprints = []
                for name in files:
                    path = Path(name)
                    with path.open("rb") as f:
                        digest = hashlib.file_digest(f, "sha256").hexdigest()
                    fingerprints.append({"path": str(path), "sha256": digest,
                                         "bytes": path.stat().st_size})
                report["sources"] = {"silver_glob": args.silver_glob, "ner": args.ner,
                                     "ner_version": args.ner_version, "files": fingerprints}
                print(json.dumps({"ner": report["steps"]["ner"]}, ensure_ascii=False), flush=True)
            if args.steps in ("chunks", "all"):
                report["steps"]["chunks"] = build_chunks(
                    conn, **cfg["chunking"], index_version=cfg["index_version"],
                    dry_run=args.dry_run, batch_size=args.batch_size)
                print(json.dumps({"chunks": report["steps"]["chunks"]}, ensure_ascii=False), flush=True)
        report["seconds"] = round(time.perf_counter() - started, 2)
        if args.report:
            path = Path(args.report)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        print(json.dumps({"seconds": report["seconds"]}), flush=True)
    except (ValueError, TypeError, OSError, db.DatabaseConfigError) as e:
        print(f"Preparation thất bại: {e}", file=sys.stderr)
        return 1
    except psycopg.Error as e:
        print(f"Postgres thất bại: {type(e).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
