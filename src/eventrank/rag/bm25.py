"""Tantivy BM25 baseline: syllable + mã văn bản, index snapshot immutable trên disk.

Analyzer dùng chung cho corpus/query; không stem/bỏ dấu/stopword. Compound như TP.HCM,
57-NQ/TW giữ cả nguyên mã và thành phần. Không dùng query syntax từ người dùng.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path

import psycopg
import tantivy
import yaml

from eventrank.common import db
from eventrank.rag.prepare import _preparation_lock

ANALYZER_VERSION = "vi_syllable_codes_v1"
_WORDS = re.compile(r"[^\W_]+(?:[./-][^\W_]+)*", re.UNICODE)
_HEADER = re.compile(r"(?m)^(?:tiêu đề:|sapo:|nội dung:)[ \t]*")
_VN = timezone(timedelta(hours=7))
_ENGINE = version("tantivy")


def analyze(text: str) -> list[str]:
    text = _HEADER.sub("", unicodedata.normalize("NFC", text).casefold())
    out = []
    for token in _WORDS.findall(text):
        if len(token) <= 256:
            out.append(token)
        if any(char in token for char in ".-/"):
            out.extend(part for part in re.split(r"[./-]", token) if 0 < len(part) <= 256)
    return out


def _signature(index_version):
    return {"analyzer": ANALYZER_VERSION, "tantivy": _ENGINE, "index_version": index_version}


def _normalize_record(raw):
    published = raw["published_at"]
    if isinstance(published, str):
        published = datetime.fromisoformat(published)
    if published.tzinfo is None or published.utcoffset() is None:
        raise ValueError("published_at cần có múi giờ")
    record = {key: raw[key] for key in ("article_id", "text", "title", "url", "chunking_version")}
    record.update(chunk_id=str(uuid.UUID(str(raw["chunk_id"]))),
                  source=raw["source"].lower(), published_at=published.astimezone(UTC).isoformat(),
                  start_char=int(raw["start_char"]), end_char=int(raw["end_char"]))
    if record["end_char"] - record["start_char"] != len(record["text"]):
        raise ValueError("Độ dài chunk không khớp offset")
    return record


def _hash_record(hasher, record):
    hasher.update(json.dumps(record, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8") + b"\n")


def _schema():
    builder = tantivy.SchemaBuilder()
    for field in ("chunk_id", "source"):
        builder.add_text_field(field, stored=True, tokenizer_name="raw")
    # Metadata/text gốc chỉ lưu để trả evidence, không tạo term nguyên cả chunk.
    builder.add_bytes_field("payload", stored=True)
    builder.add_text_field("lexical", tokenizer_name=ANALYZER_VERSION, index_option="freq")
    builder.add_integer_field("published_ts", stored=True, indexed=True, fast=True)
    return builder.build()


def _register(index):
    index.register_tokenizer(ANALYZER_VERSION,
                             tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.whitespace()).build())


def _write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())


def create_index(records, path, *, index_version="rag_v1", progress=None):
    """Dựng thư mục mới, commit bền rồi mới tạo manifest. Không ghi đè index cũ."""
    path = Path(path)
    if path.exists():
        raise ValueError("Thư mục index đã tồn tại; chọn thư mục mới")
    if not index_version.strip():
        raise ValueError("index_version không được rỗng")
    path.mkdir(parents=True)
    schema = _schema()
    index = tantivy.Index(schema, path=str(path))
    _register(index)
    writer = index.writer(64_000_000, 2)
    seen, digest = set(), hashlib.sha256()
    started = time.perf_counter()
    for raw in records:
        record = _normalize_record(raw)
        cid = record["chunk_id"]
        if cid in seen:
            raise ValueError(f"chunk_id trùng: {cid}")
        seen.add(cid)
        _hash_record(digest, record)
        doc = {"chunk_id": cid, "source": record["source"],
               "payload": json.dumps(record, ensure_ascii=False).encode("utf-8")}
        doc["published_ts"] = int(datetime.fromisoformat(record["published_at"]).timestamp())
        doc["lexical"] = " ".join(analyze(record["text"]))
        writer.add_document(tantivy.Document.from_dict(doc, schema))
        if progress and len(seen) % 10_000 == 0:
            progress({"indexed_documents": len(seen)})
    if not seen:
        raise ValueError("Không có chunk để index")
    writer.commit()
    writer.wait_merging_threads()
    index.reload()
    if index.searcher().num_docs != len(seen):
        raise ValueError("Tantivy document count không khớp")
    manifest = {"schema_version": 1, **_signature(index_version), "documents": len(seen),
                "corpus_sha256": digest.hexdigest(), "built_at": datetime.now(UTC).isoformat(),
                "seconds": round(time.perf_counter() - started, 3)}
    _write_json(path / "manifest.json", manifest)
    return manifest


def _resolve_index(path):
    path = Path(path)
    if (path / "manifest.json").is_file():
        return path
    pointer = path / "CURRENT.json"
    if not pointer.exists():
        raise ValueError("Chưa có BM25 index; chạy lệnh build trước")
    current = json.loads(pointer.read_text(encoding="utf-8"))
    build_dir = current.get("build_dir", "")
    if not isinstance(build_dir, str) or not re.fullmatch(r"[0-9a-f]{32}", build_dir):
        raise ValueError("CURRENT.json không hợp lệ")
    return path / build_dir


def _dates(date_from, date_to):
    lo = date.fromisoformat(date_from) if date_from else None
    hi = date.fromisoformat(date_to) if date_to else None
    if lo and hi and lo > hi:
        raise ValueError("date_from phải <= date_to")
    lower = int(datetime.combine(lo, datetime.min.time(), _VN).timestamp()) if lo else None
    upper = int(datetime.combine(hi + timedelta(days=1), datetime.min.time(), _VN).timestamp()) - 1 \
        if hi else None
    return lower, upper


class BM25Index:
    def __init__(self, path):
        self.path = _resolve_index(path)
        self.manifest = json.loads((self.path / "manifest.json").read_text(encoding="utf-8"))
        if self.manifest["analyzer"] != ANALYZER_VERSION or self.manifest["schema_version"] != 1:
            raise ValueError("Analyzer/schema version không được hỗ trợ")
        self.index = tantivy.Index.open(str(self.path))
        _register(self.index)
        if self.index.searcher().num_docs != self.manifest["documents"]:
            raise ValueError("Index không đủ số document trong manifest")

    def search(self, query, *, limit=10, source=None, date_from=None, date_to=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit phải từ 1 đến 100")
        if len(query) > 2048:
            raise ValueError("Câu hỏi tối đa 2048 ký tự")
        lower, upper = _dates(date_from, date_to)
        tokens = list(dict.fromkeys(analyze(query)))
        if not tokens:
            return []
        if len(tokens) > 128:
            raise ValueError("Câu hỏi quá nhiều term (tối đa 128)")
        schema = self.index.schema
        lexical = tantivy.Query.boolean_query([
            (tantivy.Occur.Should, tantivy.Query.term_query(schema, "lexical", token, "freq"))
            for token in tokens])
        clauses = [(tantivy.Occur.Must, lexical)]
        if source:
            filt = tantivy.Query.term_query(schema, "source", source.lower(), "basic")
            clauses.append((tantivy.Occur.Must, tantivy.Query.const_score_query(filt, 0.0)))
        if lower is not None or upper is not None:
            filt = tantivy.Query.range_query(schema, "published_ts", tantivy.FieldType.Integer,
                                             lower_bound=lower, upper_bound=upper)
            clauses.append((tantivy.Occur.Must, tantivy.Query.const_score_query(filt, 0.0)))
        searcher = self.index.searcher()
        found = searcher.search(tantivy.Query.boolean_query(clauses), limit=limit).hits
        results = []
        for rank, (score, address) in enumerate(found, 1):
            stored = searcher.doc(address).to_dict()
            doc = json.loads(bytes(stored["payload"][0]))
            doc["published_at"] = datetime.fromisoformat(doc["published_at"]).astimezone(_VN).isoformat()
            results.append({"rank": rank, "score": score, **doc})
        return results


def _records(conn, index_version):
    """Snapshot read-only, stream để không giữ toàn bộ text trong RAM."""
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        with conn.cursor(name="bm25_snapshot_" + uuid.uuid4().hex) as cursor:
            cursor.itersize = 1000
            cursor.execute(
                "SELECT c.chunk_id,c.article_id,c.text,c.start_char,c.end_char,c.chunking_version, "
                "a.title,a.url,a.source,a.published_at,s.index_version "
                "FROM rag_chunks c JOIN articles a USING(article_id) "
                "LEFT JOIN rag_index_status s USING(chunk_id) ORDER BY c.chunk_id")
            for row in cursor:
                if row[-1] != index_version:
                    raise ValueError("Thiếu trạng thái hoặc index_version của chunk không khớp cấu hình")
                yield dict(zip(("chunk_id", "article_id", "text", "start_char", "end_char",
                                "chunking_version", "title", "url", "source", "published_at"),
                               row[:-1], strict=True))


def _fingerprint(conn, index_version):
    digest, count = hashlib.sha256(), 0
    for raw in _records(conn, index_version):
        _hash_record(digest, _normalize_record(raw))
        count += 1
    if count == 0:
        raise ValueError("Chưa có chunk để dựng BM25")
    return digest.hexdigest(), count


def _mark_ready(conn, index_version):
    with conn.transaction():
        return conn.execute(
            "UPDATE rag_index_status s SET bm25_status='ready',updated_at=now(), "
            "error=CASE WHEN s.error LIKE 'bm25:%%' THEN NULL ELSE s.error END "
            "FROM rag_chunks c WHERE s.chunk_id=c.chunk_id AND s.index_version=%s "
            "AND (s.bm25_status<>'ready' OR s.error LIKE 'bm25:%%')",
            (index_version,)).rowcount


def build_from_db(conn, root, *, index_version="rag_v1", progress=None):
    """Build snapshot mới, publish pointer nguyên tử, rồi mới mark BM25 ready.

Giữ nguyên các thư mục index cũ. Build lỗi/corpus đổi thì không publish, không mark ready.
Pointer publish thành công nhưng UPDATE DB lỗi: chạy lại để phục hồi status từ artifact bền.
"""
    root = Path(root)
    if (root / "manifest.json").exists():
        raise ValueError("root phải là thư mục quản lý snapshot, không phải index trực tiếp")
    started = time.perf_counter()
    with _preparation_lock(conn):
        digest, count = _fingerprint(conn, index_version)
        active = BM25Index(root) if (root / "CURRENT.json").exists() else None
        signature = _signature(index_version)
        reused = bool(active and active.manifest["corpus_sha256"] == digest
                      and active.manifest["documents"] == count
                      and all(active.manifest.get(k) == v for k, v in signature.items()))
        if reused:
            path, manifest = active.path, active.manifest
        else:
            root.mkdir(parents=True, exist_ok=True)
            build_dir = uuid.uuid4().hex
            path = root / build_dir
            manifest = create_index(_records(conn, index_version), path,
                                    index_version=index_version, progress=progress)
            after, after_count = _fingerprint(conn, index_version)
            if (manifest["corpus_sha256"] != digest or after != digest
                    or manifest["documents"] != count or after_count != count):
                raise ValueError("corpus thay đổi trong lúc build; không publish, chạy lại")
            pointer = root / ("CURRENT-" + uuid.uuid4().hex + ".tmp")
            _write_json(pointer, {"build_dir": build_dir, **signature,
                                  "corpus_sha256": digest})
            os.replace(pointer, root / "CURRENT.json")
        updated = _mark_ready(conn, index_version)
        return {**manifest, "index_dir": str(path), "reused": reused,
                "status_updated": updated, "total_seconds": round(time.perf_counter() - started, 3)}


def prune_snapshots(root, *, keep=2):
    """Xoá snapshot BM25 cũ, giữ snapshot CURRENT và `keep-1` snapshot mới nhất còn lại.

    Chỉ đụng tới thư mục con có manifest.json; chưa publish (không có CURRENT.json) thì không xoá gì.
    Snapshot đang bị reader khác mở (Windows khoá file) thì bỏ qua, lần sau dọn tiếp.
    """
    if type(keep) is not int or keep < 1:
        raise ValueError("keep phải >= 1")
    root = Path(root)
    pointer = root / "CURRENT.json"
    if not pointer.exists():
        return []
    current = json.loads(pointer.read_text(encoding="utf-8"))["build_dir"]
    others = sorted((d for d in root.iterdir()
                     if d.is_dir() and d.name != current and (d / "manifest.json").exists()),
                    key=lambda d: d.stat().st_mtime, reverse=True)
    removed = []
    for old in others[keep - 1:]:
        try:
            shutil.rmtree(old)
        except OSError:
            continue
        removed.append(old.name)
    return removed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Dựng full snapshot BM25 từ Postgres")
    build.add_argument("--config", default="configs/rag.yaml")
    build.add_argument("--report", help="Báo cáo JSON mới, không ghi đè")
    search = sub.add_parser("search", help="Truy vấn index đã dựng, không cần nối DB")
    search.add_argument("query")
    search.add_argument("--config", default="configs/rag.yaml")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--source")
    search.add_argument("--date-from")
    search.add_argument("--date-to")
    search.add_argument("--full-text", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "build" and args.report and Path(args.report).exists():
        parser.error("File report đã tồn tại; chọn tên mới")
    try:
        config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
        root = config["bm25"]["root"]
        if args.command == "build":
            with db.connect() as conn:
                result = build_from_db(conn, root, index_version=config["index_version"],
                                       progress=lambda r: print(json.dumps(r), flush=True))
            if args.report:
                path = Path(args.report)
                path.parent.mkdir(parents=True, exist_ok=True)
                _write_json(path, result)
        else:
            index = BM25Index(root)
            start = time.perf_counter()
            hits = index.search(args.query, limit=args.limit, source=args.source,
                                date_from=args.date_from, date_to=args.date_to)
            search_ms = round((time.perf_counter() - start) * 1000, 3)
            if not args.full_text:
                for hit in hits:
                    hit["snippet"] = hit.pop("text")[:320]
            result = {"query": args.query, "index_version": index.manifest["index_version"],
                      "analyzer": index.manifest["analyzer"], "search_ms": search_ms, "hits": hits}
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    except psycopg.Error as e:
        print(f"Postgres thất bại: {type(e).__name__}", file=sys.stderr)
        return 1
    except (ValueError, TypeError, OSError, KeyError, RuntimeError, db.DatabaseConfigError) as e:
        print(f"BM25 thất bại: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
