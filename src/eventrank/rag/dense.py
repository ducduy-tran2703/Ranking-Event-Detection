"""Snapshot Qwen → Qdrant, resumable indexing and Postgres-hydrated dense search."""

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml
from qdrant_client import QdrantClient
from qdrant_client import models as qm

from eventrank.common import db
from eventrank.rag.bm25 import (
    _VN,
    _dates,
    _hash_record,
    _normalize_record,
    _records,
    _write_json,
)
from eventrank.rag.models import ModelClient, _check_vectors, embedding_version
from eventrank.rag.prepare import _preparation_lock

INPUT_VIEW = 'rag_chunks.text-v1'


def _embed_documents(model, records):
    """Retry transient inference failures only; token-limit errors remain explicit."""
    for attempt in range(3):
        try:
            return model.embed([r['text'] for r in records], input_type='document')
        except RuntimeError as exc:
            transient = (str(exc).startswith('Model service connection failed')
                         or str(exc) in {f'Model service returned HTTP {code}'
                                         for code in (408, 429, 500, 502, 503, 504)})
            if not transient or attempt == 2:
                raise
            time.sleep(2 ** attempt)


def _snapshot(conn, version):
    records = [_normalize_record(r) for r in _records(conn, version)]
    if not records:
        raise ValueError('No chunks to index')
    # Canonical text is the source of truth; refuse stale or corrupt chunks.
    invalid = conn.execute(
        'SELECT count(*) FROM rag_chunks c JOIN article_ner n USING(article_id) '
        'WHERE c.text <> substring(n.canonical_text FROM c.start_char+1 '
        'FOR c.end_char-c.start_char)').fetchone()[0]
    if invalid:
        raise ValueError('Chunk/canonical text mismatch')
    return records


def _binding(records, model, version):
    digest = hashlib.sha256()
    for record in records:
        _hash_record(digest, record)
    return {'schema_version': 1, 'index_version': version,
                'embedding_version': embedding_version(model.config['embedding']),
                'dimension': model.config['embedding']['dimension'], 'input_view': INPUT_VIEW,
                'chunking_versions': sorted({r['chunking_version'] for r in records}),
                'corpus_sha256': digest.hexdigest(), 'documents': len(records)}


def _payload(record, binding):
    digest = hashlib.sha256()
    _hash_record(digest, record)
    return {'article_id': record['article_id'], 'source': record['source'],
                'published_ts': int(datetime.fromisoformat(record['published_at']).timestamp()),
                'chunking_version': record['chunking_version'],
                'embedding_version': binding['embedding_version'],
                'index_version': binding['index_version'], 'input_view': INPUT_VIEW,
                'record_sha256': digest.hexdigest(),
                'text_sha256': hashlib.sha256(record['text'].encode('utf-8')).hexdigest()}


def _check_collection(q, collection, binding):
    info = q.get_collection(collection)
    vectors = info.config.params.vectors
    if (not isinstance(vectors, qm.VectorParams) or vectors.size != binding['dimension']
            or vectors.distance != qm.Distance.COSINE):
        raise ValueError('Collection dimension/distance mismatch')
    metadata = info.config.metadata or {}
    if metadata.get('binding') != binding:
        raise ValueError('Collection binding mismatch; use a new collection')
    return metadata


def _mark(conn, ids, version, status, error=None):
    with conn.transaction():
        return conn.execute(
            'UPDATE rag_index_status SET qdrant_status=%s,updated_at=now(), '
            "error=CASE WHEN error IS NULL OR error LIKE 'qdrant:%%' THEN %s ELSE error END "
            'WHERE chunk_id=ANY(%s::uuid[]) AND index_version=%s '
            "AND (qdrant_status<>%s OR (error LIKE 'qdrant:%%' AND %s='ready'))",
            (status, error, ids, version, status, status)).rowcount


def _existing(q, collection, records, binding):
    points = q.retrieve(collection, ids=[r['chunk_id'] for r in records],
                        with_payload=True, with_vectors=True)
    expected = {r['chunk_id']: _payload(r, binding) for r in records}
    found = set()
    for point in points:
        cid = str(point.id)
        if point.payload != expected[cid]:
            raise ValueError(f'Point hash/version mismatch: {cid}')
        _check_vectors([point.vector], 1, binding['dimension'])
        found.add(cid)
    return found


def _index_records(conn, q, model, collection, selected, binding, batch_size, concurrency, progress):
    """Only inference runs in threads; one coordinator owns Qdrant and Postgres writes.

    Bound outstanding work to concurrency batches. On failure drain successful requests
    in the current group, then stop without scheduling the next group.
    """
    embedded = updated = checked = 0
    started = time.perf_counter()
    version = binding['index_version']

    def ready(batch):
        nonlocal updated, checked
        updated += _mark(conn, [r['chunk_id'] for r in batch], version, 'ready')
        checked += len(batch)
        if progress and (checked == len(batch) or checked % 320 == 0 or checked == len(selected)):
            progress({'checked': checked, 'selected': len(selected), 'embedded': embedded,
                      'status_updated': updated, 'concurrency': concurrency,
                      'elapsed_seconds': round(time.perf_counter() - started, 2)})

    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix='qwen') as pool:
        for start in range(0, len(selected), batch_size * concurrency):
            pending = {}
            failure = None
            # All calls below run in the coordinator, including resume verification.
            for offset in range(start, min(start + batch_size * concurrency, len(selected)), batch_size):
                batch = selected[offset:offset + batch_size]
                found = _existing(q, collection, batch, binding)
                missing = [r for r in batch if r['chunk_id'] not in found]
                if missing:
                    pending[pool.submit(_embed_documents, model, missing)] = (batch, missing)
                else:
                    ready(batch)
            for future in as_completed(pending):
                batch, missing = pending[future]
                try:
                    vectors = future.result()
                    _check_vectors(vectors, len(missing), binding['dimension'])
                    response = q.upsert(collection_name=collection, wait=True, points=[
                        qm.PointStruct(id=r['chunk_id'], vector=v, payload=_payload(r, binding))
                        for r, v in zip(missing, vectors, strict=True)])
                    if response.status != qm.UpdateStatus.COMPLETED:
                        raise RuntimeError('Qdrant upsert not completed')
                    embedded += len(missing)
                    ready(batch)
                except Exception as exc:  # noqa: BLE001 -- drain other in-flight batches before raising
                    failure = failure or exc
                    detail = type(exc).__name__
                    if str(exc).startswith('Model service returned HTTP '):
                        detail += ' HTTP ' + str(exc).rsplit(' ', 1)[-1]
                    if progress:
                        progress({'failed_chunk_ids': [r['chunk_id'] for r in missing],
                                  'error': detail})
                    try:
                        _mark(conn, [r['chunk_id'] for r in missing], version, 'failed',
                              'qdrant: ' + detail)
                    except Exception as status_exc:  # noqa: BLE001 -- preserve initial failure
                        # Preserve the initial failure and still drain the other requests.
                        failure.add_note('Status update also failed: ' + type(status_exc).__name__)
            if failure:
                raise failure
    return embedded, updated


def build_from_db(conn, q, model, *, collection, index_version='rag_v1',
                  batch_size=32, concurrency=1, pilot=None, progress=None):
    if type(batch_size) is not int or not 1 <= batch_size <= 32:
        raise ValueError('batch_size must be 1..32')
    if pilot is not None and (type(pilot) is not int or pilot < 1):
        raise ValueError('pilot must be positive')
    if type(concurrency) is not int or not 1 <= concurrency <= 4:
        raise ValueError('concurrency must be 1..4')
    started = time.perf_counter()
    with _preparation_lock(conn):
        records = _snapshot(conn, index_version)
        binding = _binding(records, model, index_version)
        if not q.collection_exists(collection):
            q.create_collection(collection, vectors_config=qm.VectorParams(
                size=binding['dimension'], distance=qm.Distance.COSINE),
                metadata={'binding': binding, 'published': False})
            for key, kind in [('source', qm.PayloadSchemaType.KEYWORD),
                              ('published_ts', qm.PayloadSchemaType.INTEGER)]:
                q.create_payload_index(collection, key, field_schema=kind, wait=True)
        metadata = _check_collection(q, collection, binding)
        selected = records[:pilot] if pilot else records
        embedded, updated = _index_records(conn, q, model, collection, selected, binding,
                                            batch_size, concurrency, progress)
        # Re-read source and every point before publication. Pilot never publishes.
        if _binding(_snapshot(conn, index_version), model, index_version) != binding:
            raise ValueError('corpus changed during indexing; cannot publish')
        if pilot is None:
            if q.count(collection, exact=True).count != len(records):
                raise ValueError('Collection point count mismatch')
            for start in range(0, len(records), 256):
                batch = records[start:start + 256]
                if len(_existing(q, collection, batch, binding)) != len(batch):
                    raise ValueError('Missing points before publication')
            q.update_collection(collection, metadata={'binding': binding, 'published': True})
        return {**binding, 'collection': collection, 'selected': len(selected),
                'published': pilot is None or metadata.get('published', False),
                'concurrency': concurrency,
                'embedded': embedded, 'status_updated': updated,
                'seconds': round(time.perf_counter() - started, 3)}


def sync_delta(conn, q, model, *, collection, index_version='rag_v1',
               batch_size=32, concurrency=4, delete_chunk_ids=(), progress=None):
    """Delete replaced points, embed pending/failed chunks, and update collection binding."""
    if type(batch_size) is not int or not 1 <= batch_size <= 32:
        raise ValueError('batch_size must be 1..32')
    if type(concurrency) is not int or not 1 <= concurrency <= 4:
        raise ValueError('concurrency must be 1..4')
    started = time.perf_counter()
    with _preparation_lock(conn):
        records = _snapshot(conn, index_version)
        binding = _binding(records, model, index_version)
        if not q.collection_exists(collection):
            return build_from_db(conn, q, model, collection=collection,
                                 index_version=index_version, batch_size=batch_size,
                                 concurrency=concurrency, progress=progress)
        info = q.get_collection(collection)
        vectors = info.config.params.vectors
        if (not isinstance(vectors, qm.VectorParams) or vectors.size != binding['dimension']
                or vectors.distance != qm.Distance.COSINE):
            raise ValueError('Collection dimension/distance mismatch')
        prev_binding = (info.config.metadata or {}).get('binding', {})
        for key in ('schema_version', 'index_version', 'embedding_version', 'dimension', 'input_view'):
            if prev_binding.get(key) != binding[key]:
                raise ValueError(f'Collection {key} mismatch; use a new collection')

        deleted = 0
        delete_list = [str(cid) for cid in delete_chunk_ids]
        for start in range(0, len(delete_list), 256):
            q.delete(collection_name=collection,
                     points_selector=qm.PointIdsList(points=delete_list[start:start + 256]),
                     wait=True)
            deleted += len(delete_list[start:start + 256])

        pending_ids = {
            str(r[0]) for r in conn.execute(
                "SELECT chunk_id FROM rag_index_status "
                "WHERE index_version=%s AND qdrant_status IN ('pending', 'failed')",
                (index_version,),
            )
        }
        selected = [r for r in records if r['chunk_id'] in pending_ids]
        embedded = updated = 0
        if selected:
            embedded, updated = _index_records(conn, q, model, collection, selected, binding,
                                                batch_size, concurrency, progress)
        if _binding(_snapshot(conn, index_version), model, index_version) != binding:
            raise ValueError('corpus changed during delta indexing; cannot publish')
        if q.count(collection, exact=True).count != len(records):
            raise ValueError('Collection point count mismatch after delta sync')
        q.update_collection(collection, metadata={'binding': binding, 'published': True})
        return {
            **binding,
            'collection': collection,
            'selected': len(selected),
            'deleted': deleted,
            'published': True,
            'concurrency': concurrency,
            'embedded': embedded,
            'status_updated': updated,
            'seconds': round(time.perf_counter() - started, 3),
        }


def _hydrate(conn, ids, version):
    rows = conn.execute(
        'SELECT c.chunk_id,c.article_id,c.text,c.start_char,c.end_char,c.chunking_version, '
        'a.title,a.url,a.source,a.published_at FROM rag_chunks c '
        'JOIN articles a USING(article_id) JOIN rag_index_status s USING(chunk_id) '
        "WHERE c.chunk_id=ANY(%s::uuid[]) AND s.index_version=%s AND s.qdrant_status='ready'",
        (ids, version)).fetchall()
    keys = ('chunk_id', 'article_id', 'text', 'start_char', 'end_char', 'chunking_version',
            'title', 'url', 'source', 'published_at')
    return {str(row[0]): _normalize_record(dict(zip(keys, row, strict=True))) for row in rows}


def search(conn, q, model, collection, query, *, limit=10, source=None,
           date_from=None, date_to=None, index_version='rag_v1'):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('limit must be 1..100')
    if not query.strip() or len(query) > 2048:
        raise ValueError('query must contain 1..2048 characters')
    lower, upper = _dates(date_from, date_to)
    metadata = q.get_collection(collection).config.metadata or {}
    binding = metadata.get('binding', {})
    if not metadata.get('published'):
        raise ValueError('Collection is not published (pilot/incomplete)')
    if (binding.get('embedding_version') != embedding_version(model.config['embedding'])
            or binding.get('index_version') != index_version
            or binding.get('input_view') != INPUT_VIEW):
        raise ValueError('Search model/index version mismatch')
    _check_collection(q, collection, binding)
    conditions = []
    if source:
        conditions.append(qm.FieldCondition(key='source', match=qm.MatchValue(value=source.lower())))
    if lower is not None or upper is not None:
        conditions.append(qm.FieldCondition(key='published_ts', range=qm.Range(gte=lower, lte=upper)))
    vector = model.embed([query], input_type='query')
    _check_vectors(vector, 1, binding['dimension'])
    points = q.query_points(collection, query=vector[0], limit=limit,
                            query_filter=qm.Filter(must=conditions), with_payload=True).points
    records = _hydrate(conn, [str(p.id) for p in points], index_version)
    hits = []
    for rank, point in enumerate(points, 1):
        record = records.get(str(point.id))
        if record is None or point.payload != _payload(record, binding):
            raise ValueError('Stale dense evidence; rebuild/synchronize index')
        record = dict(record)
        record['published_at'] = datetime.fromisoformat(record['published_at']).astimezone(_VN).isoformat()
        hits.append(dict(rank=rank, score=point.score, **record))
    return hits


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/rag.yaml')
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('build')
    build.add_argument('--pilot', type=int)
    build.add_argument('--report')
    build.add_argument('--concurrency', type=int, choices=range(1, 5))
    find = sub.add_parser('search')
    find.add_argument('query')
    find.add_argument('--limit', type=int, default=10)
    find.add_argument('--source')
    find.add_argument('--date-from')
    find.add_argument('--date-to')
    find.add_argument('--full-text', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'build' and args.report and Path(args.report).exists():
        parser.error('Report exists; choose a new path')
    model = q = None
    try:
        config = yaml.safe_load(Path(args.config).read_text(encoding='utf-8'))
        with db.connect() as conn:
            # db.connect loads runtime environment without exposing credentials.
            model = ModelClient.from_env()
            spec = config['dense']
            q = QdrantClient(url=spec['url'], timeout=120)
            if args.command == 'build':
                result = build_from_db(conn, q, model, collection=spec['collection'],
                                       index_version=config['index_version'], pilot=args.pilot,
                                       batch_size=spec['batch_size'],
                                       concurrency=args.concurrency or spec.get('concurrency', 1),
                                       progress=lambda r: print(json.dumps(r), flush=True))
                if args.report:
                    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
                    _write_json(args.report, result)
            else:
                hits = search(conn, q, model, spec['collection'], args.query, limit=args.limit,
                              source=args.source, date_from=args.date_from, date_to=args.date_to,
                              index_version=config['index_version'])
                if not args.full_text:
                    for hit in hits:
                        hit['snippet'] = hit.pop('text')[:320]
                result = {'query': args.query, 'collection': spec['collection'], 'hits': hits}
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 -- sanitize failures at CLI boundary
        # Service/DB errors can include credentials; do not echo raw exceptions.
        print(f'Dense operation failed ({type(exc).__name__})', file=sys.stderr)
        return 1
    finally:
        if model:
            model.close()
        if q:
            q.close()


if __name__ == '__main__':
    raise SystemExit(main())
