"""RAG router shared by the main app and a standalone local API without Silver/R2 startup.

python -m uvicorn apps.api.rag:app --host 127.0.0.1 --port 8001
"""

import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import psycopg
import yaml
from fastapi import APIRouter, Depends, FastAPI, HTTPException

from apps.api import schemas
from eventrank.common import db
from eventrank.rag.chunking import chunking_version
from eventrank.rag.ner import SharedNER, ner_from_config
from eventrank.rag.pipeline import RAGPipeline, RAGUnavailableError
from eventrank.rag.sync import inspect_articles, safe_error, sync_rag

log = logging.getLogger(__name__)

router = APIRouter(prefix='/api/rag', tags=['RAG'])
_REQUEST_SLOT = threading.BoundedSemaphore(1)
_SYNC_LOCK = threading.Lock()
_SYNC_STATE: dict = {
    'running': False,
    'last_started_at': None,
    'last_finished_at': None,
    'last_result': None,
    'last_error': None,
}
_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _ROOT / 'configs/rag.yaml'
# Tài nguyên nặng dùng chung cả tiến trình: BamiBERT trên VRAM và tokenizer Gemma.
_NER: SharedNER | None = None
_COUNTER = None
_SHARED_INIT = threading.Lock()


def _load_config():
    return yaml.safe_load(_CONFIG.read_text('utf-8'))


def _ner_dir(ner_cfg):
    path = Path(ner_cfg.get('model_dir') or '')
    return path if path.is_absolute() else _ROOT / path


def _ner_checkpoint_exists(ner_cfg):
    return bool(ner_cfg.get('model_dir')) and _ner_dir(ner_cfg).exists()


def shared_ner(config=None):
    """Bản BamiBERT duy nhất của tiến trình; nạp lười nếu chưa preload."""
    global _NER
    with _SHARED_INIT:
        if _NER is None:
            ner_cfg = dict((config if config is not None else _load_config()).get('ner', {}))
            ner_cfg['model_dir'] = str(_ner_dir(ner_cfg))
            _NER = SharedNER(lambda: ner_from_config(ner_cfg))
        return _NER


def shared_counter():
    """Tokenizer Gemma dùng chung (chỉ đọc cache local, không tải mạng); None nếu chưa chuẩn bị."""
    global _COUNTER
    with _SHARED_INIT:
        if _COUNTER is None:
            try:
                from eventrank.rag.models import load_model_config
                from eventrank.rag.token_budget import GemmaTokenCounter

                _COUNTER = GemmaTokenCounter(load_model_config()['llm'])
            except Exception:  # noqa: BLE001 -- pipeline tự báo lỗi tokenizer rõ ràng khi cần
                return None
        return _COUNTER


def preload_models():
    """Nạp BamiBERT vào VRAM lúc khởi động; lỗi chỉ ghi log, API vẫn chạy (không có NER boost)."""
    try:
        config = _load_config()
    except (OSError, yaml.YAMLError):
        log.warning('RAG: không đọc được %s; bỏ qua preload BamiBERT', _CONFIG.name)
        return
    if not _ner_checkpoint_exists(config.get('ner', {})):
        log.warning('RAG: chưa có checkpoint BamiBERT; câu hỏi chạy không có NER boost, '
                    'sync bài mới cần NER sẽ lỗi')
        return
    started = time.perf_counter()
    ner = shared_ner(config)
    if ner.load():
        log.info('RAG: đã nạp BamiBERT trong %.1f giây', time.perf_counter() - started)
    else:
        log.warning('RAG: không nạp được BamiBERT (%s); thử lại ở request sau', ner.error)


def get_pipeline():
    global _COUNTER
    try:
        config = _load_config()
        conn = db.connect()
    except (OSError, yaml.YAMLError, psycopg.Error, db.DatabaseConfigError):
        raise HTTPException(503, 'Không thể mở cấu hình hoặc kết nối Postgres cho RAG.') from None
    ner = shared_ner(config) if _ner_checkpoint_exists(config.get('ner', {})) else None
    with conn:
        pipeline = RAGPipeline(conn, config, query_ner=ner, counter=_COUNTER)
        try:
            yield pipeline
        finally:
            if _COUNTER is None and pipeline.counter is not None:
                _COUNTER = pipeline.counter  # tokenizer Gemma nạp một lần rồi giữ lại
            pipeline.close()


@router.post('/ask', response_model=schemas.RAGAnswer)
def ask(body: schemas.RAGQuestion, pipeline: Annotated[RAGPipeline, Depends(get_pipeline)]):
    if not _REQUEST_SLOT.acquire(blocking=False):
        raise HTTPException(429, 'Một câu hỏi đang được xử lý. Vui lòng thử lại sau.')
    try:
        return pipeline.ask(body.question, source=body.source,
                            date_from=body.date_from.isoformat() if body.date_from else None,
                            date_to=body.date_to.isoformat() if body.date_to else None,
                            max_tokens=body.max_tokens, allow_fallback=body.allow_fallback)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except RAGUnavailableError as exc:
        if exc.phase == 'index_sync':
            raise HTTPException(503, 'Chỉ mục RAG đang được đồng bộ bài mới; thử lại sau ít phút.') from None
        raise HTTPException(503, 'Dịch vụ RAG chưa sẵn sàng. Kiểm tra Postgres, Qdrant, tokenizer '
                            'và dịch vụ model; thử lại sau khi model khởi động.') from None
    finally:
        _REQUEST_SLOT.release()


def _run_sync_worker(config: dict, article_ids: list[str] | None) -> None:
    try:
        # Dùng chung bản BamiBERT đã nạp sẵn với /ask, không nạp thêm bản thứ hai lên VRAM.
        ner = shared_ner(config) if _ner_checkpoint_exists(config.get('ner', {})) else None
        with db.connect() as conn:
            result = sync_rag(conn, config, article_ids=article_ids, ner_predictor=ner)
        with _SYNC_LOCK:
            _SYNC_STATE['last_result'] = result
            _SYNC_STATE['last_error'] = None
    except Exception as exc:  # noqa: BLE001 -- keep sanitized error state for /sync/status
        with _SYNC_LOCK:
            _SYNC_STATE['last_error'] = safe_error(exc)
    finally:
        with _SYNC_LOCK:
            _SYNC_STATE['running'] = False
            _SYNC_STATE['last_finished_at'] = datetime.now(UTC).isoformat()


@router.post('/sync', response_model=schemas.RAGSyncAccepted)
def trigger_sync(body: schemas.RAGSyncRequest):
    try:
        config = _load_config()
        chunk_cfg = config['chunking']
        c_ver = chunking_version(int(chunk_cfg['max_units']), int(chunk_cfg['overlap_units']))
        with db.connect() as conn:
            # Cùng tiêu chí với worker: đổi tham số chunking thì bài cũ cũng phải được chia lại.
            plan = inspect_articles(conn, body.article_ids, index_version=config['index_version'],
                                    chunk_version=c_ver)
    except (OSError, yaml.YAMLError, psycopg.Error, db.DatabaseConfigError):
        raise HTTPException(503, 'Không thể mở cấu hình hoặc kết nối Postgres cho RAG sync.') from None

    queued = len(plan['need_ner_articles']) + len(plan['need_rechunk_articles']) + len(plan['pending_index_ids'])
    with _SYNC_LOCK:
        if _SYNC_STATE['running']:
            return schemas.RAGSyncAccepted(
                status='already_running',
                requested=plan['requested'],
                queued_articles=queued,
                already_ready=len(plan['already_ready_ids']),
                missing_article_ids=plan['missing_article_ids'],
                message='Một tiến trình RAG sync đang chạy nền; batch mới sẽ được xử lý ở lượt tiếp theo.',
            )
        if queued == 0:
            return schemas.RAGSyncAccepted(
                status='up_to_date',
                requested=plan['requested'],
                queued_articles=0,
                already_ready=len(plan['already_ready_ids']),
                missing_article_ids=plan['missing_article_ids'],
                message='Tất cả bài báo hợp lệ đã được index sẵn sàng.',
            )
        _SYNC_STATE['running'] = True
        _SYNC_STATE['last_started_at'] = datetime.now(UTC).isoformat()
        _SYNC_STATE['last_error'] = None

    worker = threading.Thread(
        target=_run_sync_worker,
        args=(config, body.article_ids),
        name='rag-sync-worker',
        daemon=True,
    )
    worker.start()
    return schemas.RAGSyncAccepted(
        status='accepted',
        requested=plan['requested'],
        queued_articles=queued,
        already_ready=len(plan['already_ready_ids']),
        missing_article_ids=plan['missing_article_ids'],
        message=f'Đã nhận {queued} bài cần xử lý và đang chạy RAG sync ở nền.',
    )


@router.get('/sync/status', response_model=schemas.RAGSyncStatus)
def sync_status():
    with _SYNC_LOCK:
        return schemas.RAGSyncStatus(**_SYNC_STATE)


def create_rag_app(*, preload=False):
    """`preload=True` (app chạy thật ở cổng RAG) nạp BamiBERT vào VRAM trước request đầu tiên."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if preload:
            preload_models()
        yield

    app = FastAPI(title='Eventrank — RAG snapshot', lifespan=lifespan)
    app.include_router(router)
    return app


app = create_rag_app(preload=True)
