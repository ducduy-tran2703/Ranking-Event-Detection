"""Trang "Cài đặt hệ thống" của khu quản trị: `/api/admin/system/*` (chỉ admin; POST/PUT/PATCH cần header CSRF).

Chỉnh NGAY KHI ĐANG CHẠY, không sửa YAML, không khởi động lại:
- **Cào báo**: lịch nằm ở dịch vụ crawler (:8002, `data/state/schedule.json`) → chuyển tiếp `GET/PATCH /crawl/schedule`,
  `POST /crawl/jobs`. Crawler tắt: GET vẫn 200 với `reachable=false`; PATCH/POST trả 503 kèm câu tiếng Việt.
  Không sửa code crawler; chỉ kiểm lại giá trị theo cùng luật với `api/schemas.py` của nó trước khi gửi.
- **Đồng bộ RAG**: khối `rag_sync` trong `system_settings` (migration 011); bộ lập lịch `eventrank.rag.auto_sync` đọc lại
  mỗi vòng. "Đồng bộ ngay" → `AutoSync.trigger_now()`.
- **Worker sự kiện**: khối `event_worker`; `make worker` (`--loop`) đọc lại mỗi vòng và trong lúc chờ.

Bộ lập lịch RAG được tạo ở `lifespan` của `apps/api/main.py` bằng `build_auto_sync` (tắt hẳn: `RAG_AUTO_SYNC=0`).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

import psycopg
import yaml
from fastapi import APIRouter, HTTPException, Request

from apps.api import schemas
from apps.api.accounts import Admin, Conn
from eventrank.common import db, settings_store
from eventrank.rag import auto_sync as RS
from eventrank.serving import live_stats
from eventrank.serving import worker_settings as WS

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/system", tags=["Cài đặt hệ thống"])

CRAWLER_DOWN = ("Không kết nối được dịch vụ cào báo (cổng 8002). Bật bằng `make crawler` rồi thử lại; "
                "lịch cào lưu trong dịch vụ đó nên không đổi được khi nó đang tắt.")
BAD_REPLY = "Dịch vụ cào báo trả dữ liệu không đúng dạng (phiên bản khác?). Kiểm tra dịch vụ cào báo."
NO_MIGRATION = "Postgres chưa áp migration 011 (bảng system_settings). Chạy `make db-migrate` rồi thử lại."
EVENT_STEPS = ("embed", "recluster", "name", "trend")
WORKER_LOCK = 0x6576656E74776B72        # = eventrank.serving.worker._LOCK_KEY (không import worker: nặng RAM)


# ---------------------------------------------------------------------- dịch vụ crawler
class CrawlerUnavailable(RuntimeError):
    pass


def _crawler_base(request: Request) -> str:
    st = request.app.state
    return (getattr(st, "crawler_url", None) or os.environ.get("CRAWLER_URL") or "http://127.0.0.1:8002").rstrip("/")


def crawler_call(base: str, method: str, path: str, body: Any = None, timeout: float = 3.0) -> tuple[int, Any]:
    """Gọi API crawler (URL nội bộ cấu hình sẵn, không phải URL người dùng). Không kết nối được → CrawlerUnavailable."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc)
        except ValueError:
            detail = None
        return exc.code, detail
    except (OSError, ValueError) as exc:            # URLError là OSError; ValueError: trả về không phải JSON
        raise CrawlerUnavailable(type(exc).__name__) from None


def _crawler_settings(base: str) -> dict[str, Any]:
    try:
        st, sched = crawler_call(base, "GET", "/crawl/schedule", timeout=1.5)
        st2, jobs = crawler_call(base, "GET", f"/crawl/jobs?limit={live_stats.CRAWLER_JOBS}", timeout=1.5)
    except CrawlerUnavailable:
        return {"reachable": False, "message": CRAWLER_DOWN}
    if st != 200 or st2 != 200:
        return {"reachable": False, "message": f"Dịch vụ cào báo trả lỗi (HTTP {st if st != 200 else st2})."}
    if not isinstance(sched, dict) or not isinstance(jobs, dict):
        return {"reachable": False, "message": BAD_REPLY}
    try:
        items = [live_stats.format_crawler_job(j) for j in live_stats.crawler_job_items(jobs)]
        interval = sched.get("interval_minutes")
        out = {"reachable": True, "enabled": bool(sched.get("enabled")),
               "interval_minutes": interval if isinstance(interval, int) else None,
               "sources": [x for x in sched.get("sources") or [] if isinstance(x, str)],
               "next_run_at": sched.get("next_run_at"), "active_job_id": _str_or_none(sched.get("active_job_id")),
               "jobs": items}
        schemas.CrawlerSettings.model_validate(out)    # trường sai kiểu (ngày, id số, số đếm null) → như trả sai dạng
        return out
    except (AttributeError, TypeError, ValueError):     # pydantic.ValidationError là ValueError
        return {"reachable": False, "message": BAD_REPLY}


def _str_or_none(v: Any) -> str | None:
    return v if isinstance(v, str) else None


_FIELDS = {"enabled": "bật/tắt", "interval_minutes": "chu kỳ", "sources": "danh sách báo"}


def _crawler_error(status: int, detail: Any) -> HTTPException:
    """Không chuyển nguyên văn lỗi của crawler cho trình duyệt (có thể chứa đường dẫn/URL nội bộ): câu cố định, kèm
    tên trường khi tách được từ lỗi 422 dạng FastAPI (`detail: [{loc: [..., "sources"], ...}]`)."""
    if status == 409:
        return HTTPException(409, "Đang có một lượt cào chạy; đợi lượt đó xong rồi bấm lại.")
    if status == 422:
        fields = []
        items = detail.get("detail") if isinstance(detail, dict) else None
        for err in items if isinstance(items, list) else []:
            loc = err.get("loc") if isinstance(err, dict) else None
            name = next((x for x in reversed(loc) if x in _FIELDS), None) if isinstance(loc, list) else None
            if name and _FIELDS[name] not in fields:
                fields.append(_FIELDS[name])
        return HTTPException(400, "Dịch vụ cào báo từ chối giá trị" + (f" ({', '.join(fields)})" if fields else "")
                             + ". Kiểm tra lại lựa chọn rồi lưu lại.")
    return HTTPException(502, f"Dịch vụ cào báo trả lỗi HTTP {status}.")


# ---------------------------------------------------------------------- RAG / worker
def _rag_config() -> dict:
    from apps.api import rag as R
    return R._load_config()


def build_auto_sync(app) -> RS.AutoSync:
    """Bộ lập lịch RAG dùng chung BamiBERT của API (`shared_ner`, chỉ nạp khi có lượt chạy thật cần NER)."""
    from apps.api import rag as R

    def ner_factory(config):
        return R.shared_ner(config) if R._ner_checkpoint_exists(config.get("ner", {})) else None

    def crawler_busy() -> bool:
        status = live_stats.crawler_status(getattr(app.state, "crawler_url", None))
        return bool(status and status.get("active_job_id"))

    return RS.AutoSync(connect=lambda: db.connect(getattr(app.state, "db_url", None)), load_config=R._load_config,
                       ner_factory=ner_factory, crawler_busy=crawler_busy)


def _scheduler(request: Request) -> RS.AutoSync:
    """Bộ lập lịch đang chạy; không có (RAG_AUTO_SYNC=0, test) → bản không chạy nền, chỉ để bấm "Đồng bộ ngay"."""
    st = request.app.state
    sched = getattr(st, "rag_auto_sync", None)
    if sched is None:
        sched = getattr(st, "rag_auto_sync_idle", None)
        if sched is None:
            factory = getattr(st, "rag_auto_sync_factory", None) or build_auto_sync
            sched = st.rag_auto_sync_idle = factory(request.app)
    return sched


def _user_name(conn, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    row = conn.execute("SELECT display_name FROM users WHERE user_id = %s", (user_id,)).fetchone()
    return row[0] if row else None


def _qdrant_get(config: dict, path: str) -> Any:
    import httpx
    r = httpx.get(config["dense"]["url"].rstrip("/") + path, timeout=1.0)    # URL nội bộ từ configs/rag.yaml
    return r.json() if r.status_code == 200 else None


def dense_published(request: Request, config: dict) -> bool | None:
    """Collection Qdrant có đang publish không (sync gỡ publish khi Qwen lỗi giữa chừng). Lỗi/không hỏi được → None.
    Test đặt `app.state.rag_qdrant_get(path)` để không gọi mạng."""
    getter = getattr(request.app.state, "rag_qdrant_get", None) or (lambda path: _qdrant_get(config, path))
    try:
        info = getter(f"/collections/{config['dense']['collection']}")
    except Exception:  # noqa: BLE001 -- Qdrant tắt/chậm/cấu hình thiếu: chỉ bỏ dòng cảnh báo
        return None
    if not isinstance(info, dict):
        return None
    meta = ((info.get("result") or {}).get("config") or {}).get("metadata") or {}
    return bool(meta.get("published"))


def _rag_block(request: Request, conn) -> dict[str, Any]:
    stored = RS.load_settings(conn)
    state = RS.state_snapshot()
    pending = without = published = None
    try:
        config = getattr(request.app.state, "rag_config", None) or _rag_config()
        published = dense_published(request, config)
        iv, cv = RS.versions_of(config)
        summary = RS.pending_summary(conn, index_version=iv, chunk_version=cv)
        pending, without = summary["pending_articles"], summary["without_ner"]
    except (OSError, yaml.YAMLError, KeyError, psycopg.errors.UndefinedTable):
        log.warning("không đếm được bài chờ đồng bộ RAG", exc_info=True)
    runs = RS.recent_runs(conn)
    failed = next((r for r in runs if r["status"] == "failed"), None)
    # Bộ lập lịch nền, hoặc bản không chạy nền (RAG_AUTO_SYNC=0) đã chạy "Đồng bộ ngay": kết quả lượt đó (bỏ vì RAM,
    # lỗi…) nằm ở `last_decision` của bản này.
    st = request.app.state
    sched = getattr(st, "rag_auto_sync", None) or getattr(st, "rag_auto_sync_idle", None)
    return {"settings": stored.value, "updated_at": stored.updated_at, "updated_by": _user_name(conn, stored.updated_by),
            "env_enabled": RS.enabled_from_env(), "running": bool(state["running"]), "trigger": state.get("trigger"),
            "pending_articles": pending, "without_ner": without, "recent_runs": runs,
            "last_error": state.get("last_error") or (failed["error"] if failed else None), "dense_published": published,
            "scheduler": sched.status() if sched is not None else {"scheduler_running": False, "leader": False}}


def _worker_block(conn) -> dict[str, Any]:
    yaml_seconds = WS.yaml_interval()
    stored = WS.load(conn, WS.default_settings(yaml_seconds))
    row = conn.execute(
        "SELECT run_id, step, status, started_at, finished_at, stats, left(error, 300), "
        "extract(epoch FROM finished_at - started_at)::float8 FROM worker_runs WHERE step = ANY(%s) "
        "ORDER BY started_at DESC, run_id DESC LIMIT 1", (list(EVENT_STEPS),)).fetchone()
    last = None if row is None else {
        "run_id": row[0], "step": row[1], "status": row[2], "started_at": row[3], "finished_at": row[4],
        "stats": row[5] or {}, "error": row[6], "seconds": row[7]}
    alive = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_locks l JOIN pg_database d ON d.oid = l.database "
        "WHERE l.locktype = 'advisory' AND d.datname = current_database() AND l.granted "
        "AND l.classid = %s AND l.objid = %s AND l.objsubid = 1)",
        (WORKER_LOCK >> 32, WORKER_LOCK & 0xFFFFFFFF)).fetchone()[0]
    return {"settings": stored.value, "updated_at": stored.updated_at, "updated_by": _user_name(conn, stored.updated_by),
            "yaml_interval_seconds": yaml_seconds, "worker_alive": bool(alive), "last_run": last}


def _require_settings_table(conn) -> None:
    if not settings_store.available(conn):
        raise HTTPException(503, NO_MIGRATION)


# ---------------------------------------------------------------------- endpoint
@router.get("/settings", response_model=schemas.SystemSettings)
def get_settings(request: Request, conn: Conn, _: Admin) -> dict[str, Any]:
    return {"settings_available": settings_store.available(conn),
            "crawler": _crawler_settings(_crawler_base(request)),
            "rag_sync": _rag_block(request, conn), "event_worker": _worker_block(conn)}


@router.put("/settings/rag-sync", response_model=schemas.RagSyncBlock)
def put_rag_sync(body: RS.RagSyncSettings, request: Request, conn: Conn, actor: Admin) -> dict[str, Any]:
    _require_settings_table(conn)
    RS.save_settings(conn, body, actor.user_id)
    sched = getattr(request.app.state, "rag_auto_sync", None)
    if sched is not None:
        sched.wake()                 # kiểm lại ngay theo cài đặt mới (không chạy nếu chưa đủ điều kiện)
    return _rag_block(request, conn)


@router.put("/settings/event-worker", response_model=schemas.EventWorkerBlock)
def put_event_worker(body: WS.EventWorkerSettings, conn: Conn, actor: Admin) -> dict[str, Any]:
    _require_settings_table(conn)
    WS.save(conn, body, actor.user_id)
    return _worker_block(conn)


@router.patch("/crawler/schedule", response_model=schemas.CrawlerSettings)
def patch_crawler_schedule(body: schemas.CrawlerScheduleBody, request: Request, _: Admin) -> dict[str, Any]:
    changes = body.model_dump(exclude_none=True)
    if "sources" in changes:
        changes["sources"] = list(dict.fromkeys(changes["sources"]))
    base = _crawler_base(request)
    try:
        status, detail = crawler_call(base, "PATCH", "/crawl/schedule", changes)
    except CrawlerUnavailable:
        raise HTTPException(503, CRAWLER_DOWN) from None
    if status != 200:
        raise _crawler_error(status, detail)
    return _crawler_settings(base)


@router.post("/crawler/run", response_model=schemas.CrawlerRunAccepted, status_code=202)
def run_crawler(body: schemas.CrawlerRunBody, request: Request, _: Admin) -> dict[str, Any]:
    base = _crawler_base(request)
    try:
        sources = body.sources
        if sources is None:                    # theo các báo đang chọn trong lịch cào
            st, sched = crawler_call(base, "GET", "/crawl/schedule", timeout=1.5)
            raw = sched.get("sources") if st == 200 and isinstance(sched, dict) else None
            # Chỉ chuyển tiếp mã báo hợp lệ (dữ liệu lạ từ crawler → để crawler dùng mặc định của nó).
            sources = [x for x in raw if x in schemas.CRAWLER_SOURCES] if isinstance(raw, list) else None
        payload = {"sources": list(dict.fromkeys(sources))} if sources else {}
        status, job = crawler_call(base, "POST", "/crawl/jobs", payload)
    except CrawlerUnavailable:
        raise HTTPException(503, CRAWLER_DOWN) from None
    if status not in (200, 202) or not isinstance(job, dict):
        raise _crawler_error(status, job)
    srcs = [x for x in job.get("sources") or [] if isinstance(x, str)] if isinstance(job.get("sources"), list) else []
    return {"id": _str_or_none(job.get("id")), "status": _str_or_none(job.get("status")), "sources": srcs,
            "message": f"Đã bắt đầu cào {len(srcs)} báo. Bài mới vào Postgres khi từng báo cào xong."}


@router.post("/rag-sync/run", response_model=schemas.RagSyncRunAccepted, status_code=202)
def run_rag_sync(request: Request, _: Admin) -> dict[str, Any]:
    if RS.state_snapshot()["running"]:
        return {"status": "already_running", "message": "Đang có một lượt đồng bộ RAG chạy; đợi lượt đó xong."}
    _scheduler(request).trigger_now()
    return {"status": "accepted",
            "message": "Đã yêu cầu đồng bộ ngay. Bỏ qua chế độ hiện tại, nhưng vẫn kiểm RAM trống trước khi chạy."}
