"""Khung chat hỏi đáp trên web: cuộc trò chuyện, hàng đợi lượt hỏi và worker chạy pipeline RAG (migration 008).

Vì sao có hàng đợi: lần gọi đầu Modal phải khởi động GPU (đo 07/11/2026: 409 s cho một câu), lâu hơn nhiều so với
thời gian chờ của Cloudflare Tunnel/trình duyệt. API chỉ ghi lượt hỏi (`queued`) rồi trả ngay; một worker nền trong
tiến trình API lấy từng lượt, chạy `RAGPipeline.ask` và ghi kết quả; web hỏi lại trạng thái định kỳ.

- Mặc định (`tool_calling.enabled`) chatbot gọi tool và nhớ `history_turns` lượt trước của cuộc trò chuyện;
  tắt công tắc thì quay về pipeline single-turn (lịch sử chỉ để người dùng xem lại).
- Mỗi người tối đa một lượt đang chờ; tối đa `RAG_DAILY_LIMIT` lượt/24 giờ (mặc định 30; admin không giới hạn).
- Lỗi lưu cho người dùng là câu cố định theo pha, không chứa URL dịch vụ, khoá hay đường dẫn máy.
- Worker chỉ chạy MỘT lượt mỗi lúc (dịch vụ Gemma trên Modal phục vụ 1 chuỗi một lúc: --max-num-seqs 1).
"""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from eventrank.common import db

log = logging.getLogger(__name__)

DEFAULT_DAILY_LIMIT = 30
TITLE_MAX = 80
RESULT_STATUSES = ("answered", "insufficient_evidence", "unsupported_query", "invalid_generation", "smalltalk")
PENDING = ("queued", "running")
CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs/rag.yaml"

# Câu báo lỗi cho người dùng theo pha của RAGUnavailableError (pipeline.py).
PHASE_MESSAGES = {
    "snapshot": "Không đọc được kho dữ liệu RAG trong Postgres.",
    "index_sync": "Kho tin đang được đồng bộ bài mới. Hãy hỏi lại sau ít phút.",
    # Lấy/nhả khoá đọc chỉ mục lỗi = không nói chuyện được với Postgres.
    "index_lock": "Không đọc được kho dữ liệu RAG trong Postgres.",
    "retrieval": "Chưa tìm kiếm được trong kho: Qdrant, chỉ mục BM25 hoặc dịch vụ embedding chưa sẵn sàng.",
    "generation": "Mô hình ngôn ngữ chưa phản hồi (có thể đang khởi động quá lâu). Hãy thử lại sau ít phút.",
    "tokenizer": "Máy chủ chưa có tokenizer của mô hình (quản trị viên cần chạy `make rag-tokenizer`).",
}
GENERIC_ERROR = "Không trả lời được câu hỏi do lỗi máy chủ. Hãy thử lại sau."
RESTART_ERROR = "Máy chủ khởi động lại khi đang trả lời câu này. Hãy hỏi lại."


class ChatError(Exception):
    """Lỗi nghiệp vụ có mã HTTP (API đổi thành HTTPException)."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def daily_limit(env: dict[str, str] | None = None) -> int:
    raw = (os.environ if env is None else env).get("RAG_DAILY_LIMIT", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_DAILY_LIMIT
    except ValueError:
        value = DEFAULT_DAILY_LIMIT
    return max(value, 0)


def make_title(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1].rstrip() + "…"


# ---------------------------------------------------------------------- đọc
_MSG_COLS = ("message_id, conversation_id, question, filters, status, answer, sources, retrieval_mode, degraded, "
             "error, created_at, started_at, finished_at")


def _message(row: tuple) -> dict[str, Any]:
    keys = [c.strip() for c in _MSG_COLS.split(",")]
    m = dict(zip(keys, row, strict=True))
    m["seconds"] = (round((m["finished_at"] - m["started_at"]).total_seconds(), 1)
                    if m["finished_at"] and m["started_at"] else None)
    m["queue_position"] = None
    return m


def _with_queue_position(conn: psycopg.Connection, msg: dict[str, Any]) -> dict[str, Any]:
    if msg["status"] == "queued":
        msg["queue_position"] = conn.execute(
            "SELECT count(*) FROM rag_messages WHERE status IN ('queued','running') AND message_id < %s",
            (msg["message_id"],)).fetchone()[0] + 1
    return msg


def used_today(conn: psycopg.Connection, user_id: int) -> int:
    return conn.execute("SELECT count(*) FROM rag_messages WHERE user_id = %s AND created_at > now() - interval '24 hours'",
                        (user_id,)).fetchone()[0]


def list_conversations(conn: psycopg.Connection, user_id: int, limit: int = 100, *,
                       conversation_id: int | None = None) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT c.conversation_id, c.title, c.created_at, c.updated_at, count(m.message_id), "
        "(array_agg(m.status ORDER BY m.message_id DESC))[1] "
        "FROM rag_conversations c LEFT JOIN rag_messages m USING (conversation_id) "
        "WHERE c.user_id = %s AND (%s::bigint IS NULL OR c.conversation_id = %s) "
        "GROUP BY c.conversation_id ORDER BY c.updated_at DESC, c.conversation_id DESC LIMIT %s",
        (user_id, conversation_id, conversation_id, limit)).fetchall()
    keys = ("conversation_id", "title", "created_at", "updated_at", "n_messages", "last_status")
    return [dict(zip(keys, r, strict=True)) for r in rows]


def get_conversation(conn: psycopg.Connection, user_id: int, conversation_id: int) -> dict[str, Any]:
    conv = list_conversations(conn, user_id, 1, conversation_id=conversation_id)
    if not conv:
        raise ChatError(404, "Không tìm thấy cuộc trò chuyện.")
    rows = conn.execute(f"SELECT {_MSG_COLS} FROM rag_messages WHERE conversation_id = %s ORDER BY message_id",
                        (conversation_id,)).fetchall()
    return {"conversation": conv[0], "messages": [_with_queue_position(conn, _message(r)) for r in rows]}


def get_message(conn: psycopg.Connection, user_id: int, message_id: int) -> dict[str, Any]:
    row = conn.execute(f"SELECT {_MSG_COLS} FROM rag_messages WHERE message_id = %s AND user_id = %s",
                       (message_id, user_id)).fetchone()
    if row is None:
        raise ChatError(404, "Không tìm thấy câu hỏi.")
    return _with_queue_position(conn, _message(row))


# ---------------------------------------------------------------------- ghi
def ask(conn: psycopg.Connection, user_id: int, question: str, *, conversation_id: int | None = None,
        source: str | None = None, date_from: date | None = None, date_to: date | None = None,
        limit: int | None = None) -> dict[str, Any]:
    """Ghi một lượt hỏi vào hàng đợi (tạo cuộc trò chuyện mới khi `conversation_id` rỗng). `limit=None`: không giới hạn."""
    question = " ".join(question.split()) if question.strip() else ""
    if not question:
        raise ChatError(400, "Câu hỏi đang trống.")
    filters = {"source": source.strip().lower() if source and source.strip() else None,
               "date_from": date_from.isoformat() if date_from else None,
               "date_to": date_to.isoformat() if date_to else None}
    with conn.transaction():
        # Khoá dòng người dùng: hai yêu cầu song song của cùng một người không cùng lọt qua kiểm tra bên dưới.
        conn.execute("SELECT 1 FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
        if conn.execute("SELECT EXISTS (SELECT 1 FROM rag_messages WHERE user_id = %s AND status IN ('queued','running'))",
                        (user_id,)).fetchone()[0]:
            raise ChatError(409, "Câu hỏi trước của bạn vẫn đang được trả lời. Hãy chờ xong rồi hỏi tiếp.")
        if limit is not None and used_today(conn, user_id) >= limit:
            raise ChatError(429, f"Bạn đã hỏi đủ {limit} câu trong 24 giờ qua. Hãy quay lại sau.")
        if conversation_id is None:
            conversation_id = conn.execute(
                "INSERT INTO rag_conversations (user_id, title) VALUES (%s, %s) RETURNING conversation_id",
                (user_id, make_title(question))).fetchone()[0]
        elif conn.execute("UPDATE rag_conversations SET updated_at = now() WHERE conversation_id = %s AND user_id = %s",
                          (conversation_id, user_id)).rowcount == 0:
            raise ChatError(404, "Không tìm thấy cuộc trò chuyện.")
        row = conn.execute(
            f"INSERT INTO rag_messages (conversation_id, user_id, question, filters) VALUES (%s, %s, %s, %s) "
            f"RETURNING {_MSG_COLS}", (conversation_id, user_id, question, Jsonb(filters))).fetchone()
    return _with_queue_position(conn, _message(row))


def delete_conversation(conn: psycopg.Connection, user_id: int, conversation_id: int) -> None:
    if conn.execute("DELETE FROM rag_conversations WHERE conversation_id = %s AND user_id = %s",
                    (conversation_id, user_id)).rowcount == 0:
        raise ChatError(404, "Không tìm thấy cuộc trò chuyện.")


def cancel(conn: psycopg.Connection, user_id: int, message_id: int) -> dict[str, Any]:
    """Dừng một lượt đang chờ/đang chạy. Hàng đợi được giải phóng ngay; lời gọi mô hình đang dở (nếu có) vẫn chạy
    nốt ở Modal nhưng kết quả bị bỏ — worker chỉ ghi kết quả cho lượt còn `running`."""
    row = conn.execute(
        f"UPDATE rag_messages SET status = 'cancelled', finished_at = now(), error = NULL "
        f"WHERE message_id = %s AND user_id = %s AND status IN ('queued', 'running') RETURNING {_MSG_COLS}",
        (message_id, user_id)).fetchone()
    if row is None:
        current = get_message(conn, user_id, message_id)          # 404 nếu không phải của người này
        raise ChatError(409, "Câu hỏi này đã có kết quả nên không dừng được."
                        if current["status"] != "cancelled" else "Câu hỏi này đã được dừng.")
    return _message(row)


def still_running(conn: psycopg.Connection, message_id: int) -> bool:
    row = conn.execute("SELECT status FROM rag_messages WHERE message_id = %s", (message_id,)).fetchone()
    return bool(row) and row[0] == "running"


# ---------------------------------------------------------------------- hàng đợi (worker)
@dataclass
class Job:
    message_id: int
    question: str
    filters: dict[str, Any]
    user_id: int | None = None
    conversation_id: int | None = None


def recover_stale(conn: psycopg.Connection) -> int:
    """Lượt đang `running` khi tiến trình trước dừng giữa chừng → `failed` (người dùng hỏi lại)."""
    return conn.execute("UPDATE rag_messages SET status = 'failed', error = %s, finished_at = now() "
                        "WHERE status = 'running'", (RESTART_ERROR,)).rowcount


def claim_next(conn: psycopg.Connection) -> Job | None:
    with conn.transaction():
        row = conn.execute(
            "UPDATE rag_messages SET status = 'running', started_at = now() WHERE message_id = ("
            "  SELECT message_id FROM rag_messages WHERE status = 'queued' ORDER BY message_id "
            "  FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING message_id, question, filters, user_id, conversation_id").fetchone()
    return Job(*row) if row else None


def _events_for(conn: psycopg.Connection, article_ids: list[str]) -> dict[str, tuple[str, str]]:
    """article_id → (event_id, tên hiển thị) theo lớp sự kiện hiện tại; bài chưa thuộc sự kiện thì không có."""
    if not article_ids:
        return {}
    rows = conn.execute("SELECT ea.article_id, e.event_id, e.display_name FROM event_articles ea "
                        "JOIN events e USING (event_id) WHERE ea.article_id = ANY(%s)", (article_ids,)).fetchall()
    return {r[0].strip(): (r[1], r[2]) for r in rows}


def finish(conn: psycopg.Connection, message_id: int, result: dict[str, Any]) -> None:
    status = result.get("status")
    if status not in RESULT_STATUSES:
        raise ValueError(f"trạng thái pipeline lạ: {status!r}")
    sources = [dict(s) for s in result.get("sources") or []]
    # Nguồn dạng dữ liệu (số đếm, phạm vi kho từ tool SQL) không có bài/URL nên không có sự kiện.
    events = _events_for(conn, [str(s["article_id"]) for s in sources if s.get("article_id")])
    for s in sources:
        if not s.get("article_id"):
            s["event_id"], s["event_name"] = None, None
            continue
        ev = events.get(str(s["article_id"]).strip())
        s["event_id"], s["event_name"] = ev if ev else (None, None)
        if not isinstance(s.get("published_at"), str):
            s["published_at"] = s["published_at"].isoformat()
    conn.execute(
        "UPDATE rag_messages SET status = %s, answer = %s, sources = %s, retrieval_mode = %s, degraded = %s, "
        "trace = %s, error = NULL, finished_at = now() WHERE message_id = %s AND status = 'running'",
        (status, result.get("answer"), Jsonb(sources), result.get("retrieval_mode"), result.get("degraded"),
         Jsonb(result.get("trace") or {}, dumps=_dumps), message_id))


def fail(conn: psycopg.Connection, message_id: int, error: str, trace: dict | None = None) -> None:
    conn.execute("UPDATE rag_messages SET status = 'failed', error = %s, trace = %s, finished_at = now() "
                 "WHERE message_id = %s AND status = 'running'", (error, Jsonb(trace or {}, dumps=_dumps), message_id))


def _dumps(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, default=str)


def error_for(exc: BaseException) -> str:
    """Câu báo lỗi an toàn cho người dùng; chi tiết chỉ ở log máy chủ."""
    from eventrank.rag.pipeline import RAGUnavailableError

    if isinstance(exc, RAGUnavailableError):
        phase = str(exc.phase).split(";")[0].strip()
        return PHASE_MESSAGES.get(phase, GENERIC_ERROR)
    if isinstance(exc, ValueError):
        text = str(exc)
        # Lỗi kiểm tra đầu vào của pipeline (độ dài câu hỏi, số từ tìm kiếm…) — câu ngắn, không chứa bí mật.
        return f"Câu hỏi chưa hợp lệ: {text}" if text and len(text) < 200 else GENERIC_ERROR
    return GENERIC_ERROR


# ---------------------------------------------------------------------- sẵn sàng?
MODEL_ENV = ("RAG_EMBEDDING_URL", "RAG_LLM_URL", "MODAL_PROXY_TOKEN_ID", "MODAL_PROXY_TOKEN_SECRET")


def readiness(conn: psycopg.Connection, config: dict[str, Any], *, qdrant_get: Callable[[str], Any] | None = None,
              env: dict[str, str] | None = None, root: Path | None = None) -> dict[str, Any]:
    """Kiểm nhanh, KHÔNG gọi GPU: kho Postgres, BM25, Qdrant, biến dịch vụ model, tokenizer.

    Trả {available, problems, warnings, snapshot}. Chat qua hàng đợi chạy được khi còn MỘT nhánh tìm kiếm: có BM25 mà
    Qdrant chưa publish/không nối được → `warnings` (chỉ dùng BM25), không phải problem. Thiếu cả hai mới là problem."""
    from eventrank.rag.pipeline import corpus_snapshot

    env = os.environ if env is None else env
    root = root or CONFIG_PATH.parents[1]
    problems: list[str] = []
    snapshot = None
    try:
        snapshot = corpus_snapshot(conn, config["index_version"])
        if not snapshot["articles"]:
            problems.append("Kho RAG trong Postgres chưa có dữ liệu.")
    except psycopg.Error:
        problems.append("Chưa có bảng RAG trong Postgres (migration 007).")
    has_bm25 = (root / config["bm25"]["root"] / "CURRENT.json").is_file()
    if not has_bm25:
        problems.append("Chưa có chỉ mục BM25.")
    dense_problem = None
    try:
        if qdrant_get is None:
            import httpx

            def qdrant_get(path: str) -> Any:
                r = httpx.get(config["dense"]["url"].rstrip("/") + path, timeout=2)
                return r.json() if r.status_code == 200 else None
        info = qdrant_get(f"/collections/{config['dense']['collection']}")
        meta = ((info or {}).get("result") or {}).get("config", {}).get("metadata") or {}
        if not meta.get("published"):
            dense_problem = "Qdrant chưa có bộ vector đã công bố."
    except Exception:  # noqa: BLE001 - Qdrant tắt/không nối được
        dense_problem = "Không kết nối được Qdrant."
    warnings: list[str] = []
    if dense_problem and has_bm25:
        warnings.append(f"{dense_problem} Tìm kiếm ngữ nghĩa đang tạm tắt; chatbot chỉ dùng BM25 (từ khoá).")
    elif dense_problem:
        problems.append(dense_problem)
    if not all(env.get(k, "").strip() for k in MODEL_ENV):
        problems.append("Máy chủ chưa cấu hình dịch vụ mô hình (RAG_EMBEDDING_URL, RAG_LLM_URL, MODAL_PROXY_TOKEN_*).")
    tok = root / "data/rag/tokenizers"
    if not tok.is_dir() or not any(tok.iterdir()):
        problems.append("Máy chủ chưa có tokenizer của mô hình.")
    return {"available": not problems, "problems": problems, "warnings": warnings, "snapshot": snapshot}


# ---------------------------------------------------------------------- worker nền
PipelineFactory = Callable[[psycopg.Connection], Any]


def build_pipeline(conn: psycopg.Connection, config: dict[str, Any], *, query_ner=None, counter=None):
    """Pipeline tool calling khi `tool_calling.enabled`, ngược lại pipeline snapshot cũ.

    `query_ner`/`counter` cho phép API truyền bản BamiBERT/tokenizer dùng chung, không nạp lại mỗi lượt chat.
    """
    if config.get("tool_calling", {}).get("enabled"):
        from eventrank.rag.agent import ToolCallingPipeline

        return ToolCallingPipeline(conn, config, query_ner=query_ner, counter=counter)
    from eventrank.rag.pipeline import RAGPipeline

    return RAGPipeline(conn, config, query_ner=query_ner, counter=counter)


def default_pipeline_factory(conn: psycopg.Connection):
    import yaml

    return build_pipeline(conn, yaml.safe_load(CONFIG_PATH.read_text("utf-8")))


class ChatWorker:
    """Một luồng nền, chạy từng lượt trong hàng đợi. `run_once()` dùng được trực tiếp trong test (không cần luồng).

    Mỗi lượt chạy trong một luồng con; luồng worker kiểm tra mỗi `cancel_poll` giây xem lượt còn `running` không.
    Người dùng dừng (hoặc xoá cuộc trò chuyện) → worker bỏ luồng con và nhận lượt kế tiếp ngay. Lời gọi mô hình đang
    dở không huỷ được ở Modal: luồng con chạy nốt (tối đa theo hạn của ModelClient) rồi kết quả bị bỏ. Tối đa
    `max_abandoned` luồng bị bỏ còn sống cùng lúc; vượt thì chờ bớt rồi mới nhận lượt mới.
    """

    def __init__(self, url: str, pipeline_factory: PipelineFactory = default_pipeline_factory, *,
                 idle_seconds: float = 30.0, cancel_poll: float = 1.0, max_abandoned: int = 2):
        self.url, self.factory, self.idle_seconds = url, pipeline_factory, idle_seconds
        self.cancel_poll, self.max_abandoned = cancel_poll, max_abandoned
        self._wake, self._stop = threading.Event(), threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._abandoned: list[threading.Thread] = []
        self.recovered = 0

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            with db.connect(self.url) as conn:
                self.recovered = recover_stale(conn)
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="rag-chat-worker", daemon=True)
            self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                busy = self.run_once()
            except Exception:  # Postgres tạm lỗi: chờ rồi thử lại, không chết luồng
                log.exception("rag chat worker: lỗi vòng lặp")
                busy = False
            if not busy:
                self._wake.wait(self.idle_seconds)
                self._wake.clear()

    def _execute(self, job: Job, box: dict[str, Any]) -> None:
        """Chạy pipeline cho một lượt (luồng con, kết nối Postgres riêng); kết quả/ngoại lệ để vào `box`."""
        pipeline = None
        try:
            with db.connect(self.url) as conn:
                pipeline = self.factory(conn)
                f = job.filters or {}
                extra = ({"user_id": job.user_id, "conversation_id": job.conversation_id,
                          "message_id": job.message_id} if getattr(pipeline, "accepts_context", False) else {})
                # allow_fallback=True: nhánh dense tạm tắt (sync gỡ "published" khi Qwen/Modal lỗi giữa chừng, Qdrant
                # tắt) thì vẫn trả lời bằng BM25 (`retrieval_mode='bm25_only'`, `degraded`; web có nhãn cảnh báo) thay
                # vì báo lỗi. `/api/rag/ask` đồng bộ của admin vẫn theo tham số của request.
                box["result"] = pipeline.ask(job.question, source=f.get("source"), date_from=f.get("date_from"),
                                             date_to=f.get("date_to"), allow_fallback=True, **extra)
        except Exception as exc:  # noqa: BLE001 - mọi lỗi → failed với câu an toàn; chi tiết ở log
            box["error"] = exc
        finally:
            if pipeline is not None and hasattr(pipeline, "close"):
                try:
                    pipeline.close()
                except Exception:  # noqa: BLE001
                    log.warning("rag chat: đóng pipeline lỗi")

    def run_once(self) -> bool:
        """Lấy và trả lời một lượt. Trả False khi hàng đợi rỗng (hoặc còn quá nhiều lượt bị dừng đang chạy nốt)."""
        self._abandoned = [t for t in self._abandoned if t.is_alive()]
        if len(self._abandoned) >= self.max_abandoned:
            self._abandoned[0].join(self.cancel_poll)
            return False
        with db.connect(self.url) as conn:
            job = claim_next(conn)
            if job is None:
                return False
            box: dict[str, Any] = {}
            t = threading.Thread(target=self._execute, args=(job, box), daemon=True,
                                 name=f"rag-chat-job-{job.message_id}")
            t.start()
            while True:
                t.join(self.cancel_poll)
                if not t.is_alive():
                    break
                if not still_running(conn, job.message_id):       # người dùng dừng / xoá cuộc trò chuyện
                    log.info("rag chat: lượt %s bị dừng; bỏ kết quả", job.message_id)
                    self._abandoned.append(t)
                    return True
            if "result" in box:
                try:
                    finish(conn, job.message_id, box["result"])
                except Exception as exc:  # noqa: BLE001 - kết quả pipeline lạ
                    log.warning("rag chat: lượt %s ghi kết quả lỗi: %s", job.message_id, type(exc).__name__)
                    fail(conn, job.message_id, GENERIC_ERROR)
            else:
                exc = box.get("error") or RuntimeError("không có kết quả")
                log.warning("rag chat: lượt %s lỗi: %s", job.message_id, type(exc).__name__)
                fail(conn, job.message_id, error_for(exc), getattr(exc, "trace", None))
            return True
