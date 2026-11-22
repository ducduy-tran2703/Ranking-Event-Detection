"""API khung chat hỏi đáp RAG cho web: /api/rag/status, /api/rag/conversations, /api/rag/messages (+ /cancel).

Nghiệp vụ ở `eventrank.rag.chat`; ở đây chỉ HTTP. Đăng nhập + CSRF dùng chung với `apps/api/accounts.py`.
Gửi câu hỏi trả 202 ngay (lượt `queued`); worker nền trong tiến trình API trả lời rồi ghi kết quả; web hỏi lại
GET /api/rag/messages/{id} cho đến khi hết `queued`/`running`.

Worker khởi động lười ở yêu cầu đầu tiên tới các endpoint này (lúc đó dọn lượt `running` bị bỏ dở khi máy chủ tắt).
Test đặt `app.state.rag_autostart = False` và `app.state.rag_pipeline_factory` rồi gọi `worker.run_once()`.
"""
from __future__ import annotations

import threading
import time
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Path, Request

from apps.api import schemas
from apps.api.accounts import Conn, User, optional_user
from eventrank.accounts.auth import CurrentUser
from eventrank.common import db
from eventrank.rag import chat as C
from eventrank.rag import profile as P

router = APIRouter(prefix="/api/rag", tags=["RAG chat"])
_worker_lock = threading.Lock()
STATUS_TTL = 30.0          # giây: kết quả kiểm "sẵn sàng" được đệm lại, tránh truy vấn kho ở mỗi lần web hỏi lại
Id = Annotated[int, Path(ge=1)]


def worker(request: Request) -> C.ChatWorker:
    st = request.app.state
    if getattr(st, "rag_worker", None) is None:
        with _worker_lock:
            if getattr(st, "rag_worker", None) is None:
                try:
                    url = getattr(st, "db_url", None) or db.database_url()
                except db.DatabaseConfigError as exc:
                    raise HTTPException(503, "Hỏi đáp cần Postgres (DATABASE_URL).") from exc
                factory = getattr(st, "rag_pipeline_factory", None) or _shared_factory
                st.rag_worker = C.ChatWorker(url, factory, cancel_poll=getattr(st, "rag_cancel_poll", 1.0))
    w = st.rag_worker
    if getattr(st, "rag_autostart", True):
        w.start()
    return w


Worker = Annotated[C.ChatWorker, Depends(worker)]


def _shared_factory(conn):
    """Pipeline cho mỗi lượt chat, dùng chung BamiBERT (VRAM) và tokenizer Gemma của tiến trình API."""
    from apps.api import rag as R

    config = yaml.safe_load(C.CONFIG_PATH.read_text("utf-8"))
    ner = R.shared_ner(config) if R._ner_checkpoint_exists(config.get("ner", {})) else None
    return C.build_pipeline(conn, config, query_ner=ner, counter=R.shared_counter())


def _run(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except C.ChatError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


def _limit(user: CurrentUser) -> int | None:
    return None if user.role == "admin" else C.daily_limit()


def _readiness(request: Request, conn) -> dict[str, Any]:
    st = request.app.state
    cached = getattr(st, "rag_status_cache", None)
    if cached and time.monotonic() - cached[0] < STATUS_TTL:
        return cached[1]
    config = yaml.safe_load(C.CONFIG_PATH.read_text("utf-8"))
    value = (getattr(st, "rag_readiness", None) or C.readiness)(conn, config)    # test thay bằng bản không gọi mạng
    st.rag_status_cache = (time.monotonic(), value)
    return value


@router.get("/status", response_model=schemas.RAGChatStatus)
def status(request: Request, conn: Conn,
           user: Annotated[CurrentUser | None, Depends(optional_user)]) -> dict[str, Any]:
    """Công khai: web dùng để hiện/ẩn khung chat. Đăng nhập thì kèm hạn mức của người đó."""
    ready = _readiness(request, conn)
    return {**ready, "daily_limit": _limit(user) if user else C.daily_limit(),
            "used_today": C.used_today(conn, user.user_id) if user else None}


@router.get("/conversations", response_model=list[schemas.RAGConversation])
def conversations(conn: Conn, user: User, _: Worker) -> list[dict[str, Any]]:
    return C.list_conversations(conn, user.user_id)


@router.get("/conversations/{conversation_id}", response_model=schemas.RAGConversationDetail)
def conversation(conversation_id: Id, conn: Conn, user: User, _: Worker) -> dict[str, Any]:
    return _run(C.get_conversation, conn, user.user_id, conversation_id)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: Id, conn: Conn, user: User) -> None:
    _run(C.delete_conversation, conn, user.user_id, conversation_id)


@router.post("/messages", response_model=schemas.RAGChatMessage, status_code=202)
def ask(body: schemas.RAGChatAsk, conn: Conn, user: User, w: Worker) -> dict[str, Any]:
    """Xếp câu hỏi vào hàng đợi: 409 khi câu trước còn đang chờ, 429 khi hết lượt trong 24 giờ."""
    msg = _run(C.ask, conn, user.user_id, body.question, conversation_id=body.conversation_id,
               source=body.source, date_from=body.date_from, date_to=body.date_to, limit=_limit(user))
    w.wake()
    return msg


@router.post("/messages/{message_id}/cancel", response_model=schemas.RAGChatMessage)
def cancel(message_id: Id, conn: Conn, user: User) -> dict[str, Any]:
    """Dừng lượt đang chờ/đang chạy: 409 khi đã có kết quả. Người dùng hỏi tiếp được ngay."""
    return _run(C.cancel, conn, user.user_id, message_id)


@router.get("/messages/{message_id}", response_model=schemas.RAGChatMessage)
def message(message_id: Id, conn: Conn, user: User, _: Worker) -> dict[str, Any]:
    return _run(C.get_message, conn, user.user_id, message_id)


# ---------------------------------------------------------------------- hồ sơ cá nhân hoá (migration 010)
def _categories() -> list[str]:
    return list(yaml.safe_load(C.CONFIG_PATH.read_text("utf-8")).get("profile", {}).get("categories", []))


@router.get("/profile", response_model=schemas.RAGProfile)
def get_profile(conn: Conn, user: User) -> dict[str, Any]:
    return P.get_profile(conn, user.user_id)


@router.put("/profile", response_model=schemas.RAGProfile)
def put_profile(body: schemas.RAGProfileUpdate, conn: Conn, user: User) -> dict[str, Any]:
    """Người dùng tự sửa hồ sơ (không cần xác nhận). Chuyên mục phải nằm trong danh sách cấu hình."""
    fields = body.model_dump(exclude_unset=True)
    if fields.get("interests") is not None:
        known = {" ".join(c.casefold().split()): c for c in _categories()}
        wrong = [c for c in fields["interests"] if " ".join(c.casefold().split()) not in known]
        if wrong:
            raise HTTPException(422, f"Chuyên mục không có trong danh sách: {', '.join(wrong)}")
        fields["interests"] = list(dict.fromkeys(known[" ".join(c.casefold().split())] for c in fields["interests"]))
    elif "interests" in fields:
        fields["interests"] = []
    P.save_fields(conn, user.user_id, fields)
    return P.get_profile(conn, user.user_id)


@router.post("/profile/confirm", response_model=schemas.RAGProfile)
def confirm_profile(body: schemas.RAGProfileConfirm, conn: Conn, user: User) -> dict[str, Any]:
    """Áp (accept=true) hoặc bỏ (false) thay đổi nghề/nhóm người dùng mà chatbot đã suy ra."""
    return P.confirm_pending(conn, user.user_id, body.accept)


@router.delete("/profile", status_code=204)
def delete_profile(conn: Conn, user: User) -> None:
    P.delete_profile(conn, user.user_id)

