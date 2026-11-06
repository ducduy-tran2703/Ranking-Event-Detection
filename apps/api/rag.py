"""RAG router shared by the main app and a standalone local API without Silver/R2 startup.

python -m uvicorn apps.api.rag:app --host 127.0.0.1 --port 8001
"""

import threading
from pathlib import Path
from typing import Annotated

import psycopg
import yaml
from fastapi import APIRouter, Depends, FastAPI, HTTPException

from apps.api import schemas
from eventrank.common import db
from eventrank.rag.pipeline import RAGPipeline, RAGUnavailableError

router = APIRouter(prefix='/api/rag', tags=['RAG'])
_REQUEST_SLOT = threading.BoundedSemaphore(1)
_CONFIG = Path(__file__).resolve().parents[2] / 'configs/rag.yaml'


def get_pipeline():
    try:
        config = yaml.safe_load(_CONFIG.read_text('utf-8'))
        conn = db.connect()
    except (OSError, yaml.YAMLError, psycopg.Error, db.DatabaseConfigError):
        raise HTTPException(503, 'Không thể mở cấu hình hoặc kết nối Postgres cho RAG.') from None
    with conn:
        pipeline = RAGPipeline(conn, config)
        try:
            yield pipeline
        finally:
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
    except RAGUnavailableError:
        raise HTTPException(503, 'Dịch vụ RAG chưa sẵn sàng. Kiểm tra Postgres, Qdrant, tokenizer '
                            'và dịch vụ model; thử lại sau khi model khởi động.') from None
    finally:
        _REQUEST_SLOT.release()


def create_rag_app():
    app = FastAPI(title='Eventrank — RAG snapshot')
    app.include_router(router)
    return app


app = create_rag_app()
