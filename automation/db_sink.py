"""Load each job's clean_silver export into Postgres through the shared ingest contract.

A per-job marker records success, so an export that missed the database (outage, crash) is picked
up by the next job of that source. Upserts are idempotent, so importing one twice is harmless.
"""
from eventrank.common import db
from eventrank.ingest import clock, jsonl, sink, sources

MARKER_SUFFIX = ".db-imported"


def pending_exports(root, source):
    exports = sorted((root / "jobs").glob(f"*/clean_silver/{source}.jsonl"),
                     key=lambda path: path.stat().st_mtime)
    return [path for path in exports
            if path.stat().st_size and not path.with_suffix(MARKER_SUFFIX).exists()]


def import_pending(root, source):
    """Import every unimported export of `source`. Returns counters; None when there was nothing."""
    exports = pending_exports(root, source)
    if not exports:
        return None
    with db.connect() as conn:
        if clock.read_clock(conn).mode == "replay":
            raise RuntimeError("database clock is in replay mode; refusing to mix in live crawl data")
        sink.sync_sources(conn, sources.load_sources())
        result = jsonl.import_jsonl(conn, [str(path) for path in exports])
    for path in exports:
        path.with_suffix(MARKER_SUFFIX).touch()
    return {"files": len(exports), **result.as_dict()}
