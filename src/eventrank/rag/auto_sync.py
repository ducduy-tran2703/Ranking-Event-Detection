"""Bộ lập lịch đồng bộ RAG tự động: cào báo xong thì kho RAG tự cập nhật (NER → chunk → Qdrant → BM25).

Chạy trong tiến trình API chính (luồng nền `rag-auto-sync`, khởi động ở `lifespan` của `apps/api/main.py`) để dùng chung
bản BamiBERT đã nạp (máy 7 GB RAM không chịu được tiến trình thứ hai nạp lại model). Mỗi `poll_seconds` (60 s):

1. Đọc lại cài đặt `rag_sync` từ `system_settings` → đổi trên trang "Cài đặt hệ thống" có hiệu lực ở vòng sau.
2. Quyết định có chạy không (`decide`, hàm thuần):
   - `off`: không chạy.
   - `after_crawl` (mặc định): có bài chờ VÀ có lượt nạp `crawl_runs` xong sau lần `rag_sync` gần nhất VÀ không có lượt
     cào đang chạy. Lần trước bị cắt bởi `max_articles_per_run` mà còn bài chờ → chạy tiếp lô sau luôn.
   - `interval`: có bài chờ và đã qua `interval_minutes` kể từ lần trước (lô bị cắt cũng chạy tiếp luôn).
   - Chưa từng có `rag_sync`: mốc so sánh là LÚC BỘ LẬP LỊCH KHỞI ĐỘNG, không phải "chạy ngay" — bật API không tự
     đốt GPU Modal. Ngoại lệ: nút "Đồng bộ ngay" (`trigger_now`).
3. Bỏ qua khi `MemAvailable` dưới ngưỡng, khi đang có lượt sync tay (`SYNC_STATE` dùng chung với `/api/rag/sync`), hoặc
   khi tiến trình khác đã giữ khoá advisory của bộ lập lịch (mỗi DB chỉ một bộ lập lịch).
4. Mỗi lượt chạy ghi một dòng `worker_runs` step `rag_sync` (ok/failed, stats, lỗi qua `safe_error`).

Luồng bắt MỌI Exception, không bao giờ chết; lỗi liên tiếp thì giãn thời gian chờ (gấp đôi, tối đa 30 phút).
Tắt hẳn: `RAG_AUTO_SYNC=0` (test đặt sẵn trong tests/conftest.py) — xem `enabled_from_env`.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from eventrank.common import settings_store
from eventrank.rag.chunking import chunking_version
from eventrank.rag.sync import pending_summary, safe_error, sync_rag

log = logging.getLogger(__name__)

SETTINGS_KEY = "rag_sync"
INTERVALS = (15, 30, 60, 120, 240, 360, 720, 1440)
SCHED_LOCK = 0x72616773796E63      # "ragsync": khoá advisory riêng của bộ lập lịch (khác khoá ghi chỉ mục)
CRAWL_RUNNING_HOURS = 2            # dòng crawl_runs 'running' cũ hơn chừng này coi là tiến trình đã chết
MAX_BACKOFF_SECONDS = 1800
RECENT_RUNS = 5


class RagSyncSettings(BaseModel):
    """Khối cài đặt `rag_sync` (bảng `system_settings`)."""
    model_config = ConfigDict(extra="forbid")
    mode: Literal["after_crawl", "interval", "off"] = "after_crawl"
    interval_minutes: Literal[15, 30, 60, 120, 240, 360, 720, 1440] = 60
    max_articles_per_run: int = Field(200, ge=10, le=1000)
    min_mem_available_mb: int = Field(1500, ge=0, le=16384)


def enabled_from_env() -> bool:
    """`RAG_AUTO_SYNC=0|false|no|off` tắt hẳn bộ lập lịch (không tạo luồng)."""
    return os.environ.get("RAG_AUTO_SYNC", "1").strip().lower() not in ("0", "false", "no", "off")


def load_settings(conn) -> settings_store.Stored[RagSyncSettings]:
    return settings_store.load(conn, SETTINGS_KEY, RagSyncSettings)


def save_settings(conn, value: RagSyncSettings, user_id: int | None = None):
    return settings_store.save(conn, SETTINGS_KEY, value, user_id)


# ---------------------------------------------------------------------- trạng thái dùng chung với /api/rag/sync
# `apps/api/rag.py` dùng CHÍNH hai đối tượng này (_SYNC_LOCK, _SYNC_STATE): sync tay và sync tự động không chạy chồng.
SYNC_LOCK = threading.Lock()
SYNC_STATE: dict[str, Any] = {
    "running": False,
    "trigger": None,            # manual (/api/rag/sync) | auto | forced (nút "Đồng bộ ngay")
    "last_started_at": None,
    "last_finished_at": None,
    "last_result": None,
    "last_error": None,
}


def begin_run(trigger: str) -> bool:
    with SYNC_LOCK:
        if SYNC_STATE["running"]:
            return False
        SYNC_STATE.update(running=True, trigger=trigger, last_started_at=datetime.now(UTC).isoformat(),
                          last_error=None)
        return True


def end_run(result: dict | None = None, error: str | None = None) -> None:
    with SYNC_LOCK:
        SYNC_STATE.update(running=False, last_finished_at=datetime.now(UTC).isoformat())
        if error is None:
            SYNC_STATE.update(last_result=result, last_error=None)
        else:
            SYNC_STATE["last_error"] = error


def state_snapshot() -> dict[str, Any]:
    with SYNC_LOCK:
        return dict(SYNC_STATE)


# ---------------------------------------------------------------------- đọc DB / máy
def mem_available_mb(path: str | Path = "/proc/meminfo") -> int | None:
    """MemAvailable (MB) của máy; không đọc được (không phải Linux) → None = không chặn."""
    try:
        for line in Path(path).read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def recent_runs(conn, limit: int = RECENT_RUNS) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT run_id, status, started_at, finished_at, stats, left(error, 300) AS error, versions->>'trigger', "
        "extract(epoch FROM finished_at - started_at)::float8, versions->>'reason' FROM worker_runs "
        "WHERE step = 'rag_sync' ORDER BY started_at DESC, run_id DESC LIMIT %s", (limit,))
    return [{"run_id": r[0], "status": r[1], "started_at": r[2], "finished_at": r[3], "stats": r[4] or {},
             "error": r[5], "trigger": r[6], "seconds": r[7], "reason": r[8]} for r in cur.fetchall()]


STALE_RUN_ERROR = "Máy chủ khởi động lại giữa lượt đồng bộ (lượt bị bỏ dở)"


def recover_stale_runs(conn, before: datetime) -> int:
    """Dòng `rag_sync` còn 'running' từ trước lúc bộ lập lịch này khởi động = tiến trình API cũ chết giữa lượt → failed.
    Chỉ gọi khi đã giữ khoá bộ lập lịch. Sau đó `decide` coi chúng là lượt lỗi (được thử lại có giãn chờ)."""
    return conn.execute(
        "UPDATE worker_runs SET status = 'failed', finished_at = now(), error = %s "
        "WHERE step = 'rag_sync' AND status = 'running' AND started_at < %s", (STALE_RUN_ERROR, before)).rowcount


def last_crawl_finished_at(conn) -> datetime | None:
    return conn.execute("SELECT max(finished_at) FROM crawl_runs WHERE status <> 'running'").fetchone()[0]


def crawl_in_progress(conn, hours: int = CRAWL_RUNNING_HOURS) -> bool:
    return bool(conn.execute(
        "SELECT EXISTS (SELECT 1 FROM crawl_runs WHERE status = 'running' "
        "AND started_at >= now() - make_interval(hours => %s))", (hours,)).fetchone()[0])


def versions_of(config: dict) -> tuple[str, str]:
    """(index_version, chunking_version) theo configs/rag.yaml — cùng tiêu chí với sync_rag."""
    chunk = config["chunking"]
    return config["index_version"], chunking_version(int(chunk["max_units"]), int(chunk["overlap_units"]))


def pending_count(conn, config: dict) -> int:
    iv, cv = versions_of(config)
    return pending_summary(conn, index_version=iv, chunk_version=cv)["pending_articles"]


# ---------------------------------------------------------------------- quyết định (hàm thuần)
# Lượt lỗi (Modal tắt, Qdrant mất kết nối…) được THỬ LẠI có giãn chờ trong cùng một "đợt" (đợt = một lượt cào mới ở
# after_crawl, một chu kỳ mới ở interval): lỗi lần 1 chờ 5 phút, lần 2 chờ 15, lần 3 chờ 45; lỗi lần 4 thì thôi, đợi đợt
# sau. Trần này để một chunk lỗi vĩnh viễn không bật GPU Modal mãi.
RETRY_BACKOFF_MINUTES = (5, 15, 45)
RETRY_REASON = "retry_failed"


@dataclass
class Decision:
    run: bool
    reason: str      # mã: off, no_pending, crawl_running, waiting_crawl, waiting_interval, after_crawl, interval_due,
    #                  continue_batch, retry_failed, retry_wait, retries_exhausted, forced, low_memory, already_running,
    #                  other_scheduler, missing_migration, ok, failed
    error: str | None = None


def failed_wave(history: list[dict]) -> list[dict]:
    """Các lượt lỗi liên tiếp của đợt hiện tại, mới nhất trước: từ lượt mới nhất lùi về tới lượt MỞ ĐỢT (lượt đầu tiên
    không phải `retry_failed`). Lượt mới nhất không lỗi → []."""
    chain: list[dict] = []
    for r in history:
        if r.get("status") != "failed":
            break
        chain.append(r)
        if r.get("reason") != RETRY_REASON:
            break
    return chain


def _retry(chain: list[dict], now: datetime) -> Decision | None:
    if not chain:
        return None
    if len(chain) > len(RETRY_BACKOFF_MINUTES):
        return Decision(False, "retries_exhausted")
    wait = timedelta(minutes=RETRY_BACKOFF_MINUTES[len(chain) - 1])
    return Decision(True, RETRY_REASON) if now - chain[0]["started_at"] >= wait else Decision(False, "retry_wait")


def decide(settings: RagSyncSettings, *, now: datetime, pending: int, last_run: dict | None,
           last_crawl_at: datetime | None, crawl_busy: bool | Callable[[], bool], started_at: datetime,
           force: bool = False, history: list[dict] | None = None) -> Decision:
    """Có nên chạy lượt sync bây giờ không. `crawl_busy` có thể là hàm (chỉ gọi khi cần: hỏi dịch vụ crawler tốn I/O).
    `history`: các lượt `rag_sync` gần nhất, mới nhất trước (để đếm lượt thử lại); bỏ trống = chỉ `last_run`."""
    if force:
        return Decision(True, "forced")
    if settings.mode == "off":
        return Decision(False, "off")
    if pending <= 0:
        return Decision(False, "no_pending")
    if history is None:
        history = [last_run] if last_run else []
    base = last_run["started_at"] if last_run else started_at
    continue_batch = bool(last_run and last_run["status"] == "ok" and (last_run.get("stats") or {}).get("limited"))
    chain = failed_wave(history)
    if settings.mode == "after_crawl":
        if crawl_busy() if callable(crawl_busy) else crawl_busy:
            return Decision(False, "crawl_running")
        if continue_batch:
            return Decision(True, "continue_batch")
        if last_crawl_at is not None and last_crawl_at > base:
            return Decision(True, "after_crawl")          # đợt mới: đếm thử lại từ đầu
        return _retry(chain, now) or Decision(False, "waiting_crawl")
    if continue_batch:
        return Decision(True, "continue_batch")
    wave_start = chain[-1]["started_at"] if chain else base
    if now - wave_start >= timedelta(minutes=settings.interval_minutes):
        return Decision(True, "interval_due")
    return _retry(chain, now) or Decision(False, "waiting_interval")


# ---------------------------------------------------------------------- bộ lập lịch
class AutoSync:
    """Luồng nền đồng bộ RAG. `connect()` trả kết nối Postgres autocommit; `load_config()` trả configs/rag.yaml;
    `ner_factory(config)` trả bộ NER dùng chung (BamiBERT nạp lười ở lần predict đầu) hoặc None."""

    def __init__(self, *, connect: Callable[[], psycopg.Connection], load_config: Callable[[], dict],
                 ner_factory: Callable[[dict], Any] | None = None, crawler_busy: Callable[[], bool] | None = None,
                 poll_seconds: float = 60.0, sync_fn: Callable[..., dict] = sync_rag,
                 mem_fn: Callable[[], int | None] = mem_available_mb):
        self._connect, self._load_config, self._ner_factory = connect, load_config, ner_factory
        self._crawler_busy, self._sync, self._mem = crawler_busy, sync_fn, mem_fn
        self.poll_seconds = float(poll_seconds)
        self.started_at = datetime.now(UTC)
        self.leader = False
        self.last_check_at: datetime | None = None
        self.next_check_at: datetime | None = None
        self.last_decision: Decision | None = None
        self.consecutive_failures = 0
        self._force = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ vòng lặp
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> AutoSync:
        if not self.running:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="rag-auto-sync", daemon=True)
            self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def trigger_now(self) -> bool:
        """Nút "Đồng bộ ngay": luồng đang chạy → đánh thức để chạy ở vòng kế (bỏ qua chế độ/điều kiện chờ, vẫn kiểm
        RAM và lượt đang chạy). Luồng không chạy (RAG_AUTO_SYNC=0) → chạy một lượt trong luồng riêng."""
        if self.running:
            with self._lock:
                self._force = True
            self._wake.set()
            return True
        threading.Thread(target=self._run_detached, name="rag-sync-now", daemon=True).start()
        return True

    def wake(self) -> None:
        """Kiểm lại ngay ở vòng kế (vd. vừa đổi cài đặt); không ép chạy như `trigger_now`."""
        self._wake.set()

    def _take_force(self) -> bool:
        with self._lock:
            force, self._force = self._force, False
            return force

    def _run_detached(self) -> None:
        try:
            with self._connect() as conn:
                self.last_decision = self.tick(conn, force=True)
        except Exception as exc:  # luồng phụ không được ném lỗi ra ngoài
            log.exception("đồng bộ RAG (chạy ngay) lỗi")
            self.last_decision = Decision(False, "failed", safe_error(exc))

    def _loop(self) -> None:
        conn = None
        while not self._stop.is_set():
            try:
                if conn is None or conn.closed:
                    conn, self.leader = self._connect(), False
                if not self.leader:
                    self.leader = bool(conn.execute("SELECT pg_try_advisory_lock(%s)", (SCHED_LOCK,)).fetchone()[0])
                    if self.leader:
                        self._recover(conn)
                force = self._take_force()
                if self.leader or force:
                    # Không giữ khoá (tiến trình API thứ hai) mà có người bấm "Đồng bộ ngay" → vẫn chạy lượt đó ở đây
                    # (không nuốt yêu cầu); `_preparation_lock` vẫn chặn ghi chồng với bộ lập lịch kia.
                    decision = self.tick(conn, force=force)
                else:
                    decision = Decision(False, "other_scheduler")
                self.last_decision = decision
                self.consecutive_failures = self.consecutive_failures + 1 if decision.reason == "failed" else 0
            except Exception as exc:  # luồng nền không bao giờ chết; lần sau kết nối lại
                log.exception("vòng đồng bộ RAG tự động lỗi")
                self.last_decision = Decision(False, "failed", safe_error(exc))
                self.consecutive_failures += 1
                self._close(conn)
                conn = None
            wait = self.poll_seconds
            if self.consecutive_failures:
                wait = min(self.poll_seconds * 2 ** min(self.consecutive_failures, 10), MAX_BACKOFF_SECONDS)
            self.next_check_at = datetime.now(UTC) + timedelta(seconds=wait)
            self._wake.wait(wait)
            self._wake.clear()
        self._close(conn)       # đóng kết nối = nhả khoá advisory của bộ lập lịch

    def _recover(self, conn) -> None:
        try:
            n = recover_stale_runs(conn, self.started_at)
            if n:
                log.warning("đánh dấu %d lượt rag_sync bị bỏ dở (máy chủ khởi động lại) là failed", n)
        except Exception:  # dọn dẹp phụ: không được chặn vòng lặp
            log.warning("không dọn được lượt rag_sync bị bỏ dở (chưa áp migration 011?)", exc_info=True)

    def _close(self, conn) -> None:
        self.leader = False
        if conn is not None:
            try:
                conn.close()
            except Exception:  # kết nối đã hỏng: không còn gì để nhả
                log.debug("đóng kết nối bộ lập lịch RAG lỗi", exc_info=True)

    # ------------------------------------------------------------ một lần kiểm
    def tick(self, conn, *, force: bool = False) -> Decision:
        """Đọc cài đặt, quyết định, chạy nếu cần. Lỗi của lượt sync được ghi lại và trả `reason='failed'`."""
        self.last_check_at = datetime.now(UTC)
        if not settings_store.available(conn) and not force:
            return Decision(False, "missing_migration")
        settings = load_settings(conn).value
        if state_snapshot()["running"]:
            return Decision(False, "already_running")
        config = self._load_config()
        decision = Decision(True, "forced") if force else None
        if decision is None:
            history = recent_runs(conn, len(RETRY_BACKOFF_MINUTES) + 2)
            decision = decide(
                settings, now=conn.execute("SELECT now()").fetchone()[0], pending=pending_count(conn, config),
                last_run=history[0] if history else None, last_crawl_at=last_crawl_finished_at(conn),
                crawl_busy=lambda: crawl_in_progress(conn) or bool(self._crawler_busy and self._crawler_busy()),
                started_at=self.started_at, history=history)
        if not decision.run:
            return decision
        mem = self._mem()
        if mem is not None and mem < settings.min_mem_available_mb:
            log.warning("bỏ qua đồng bộ RAG: RAM trống %d MB < ngưỡng %d MB", mem, settings.min_mem_available_mb)
            return Decision(False, "low_memory")
        return self._run(conn, config, settings, trigger="forced" if force else "auto", reason=decision.reason)

    def _run(self, conn, config: dict, settings: RagSyncSettings, *, trigger: str, reason: str) -> Decision:
        if not begin_run(trigger):
            return Decision(False, "already_running")
        result: dict | None = None
        err: str | None = "RuntimeError: lượt đồng bộ dừng bất thường"
        try:                          # end_run trong finally: SYNC_STATE không bao giờ kẹt running=True
            run_id = self._log_start(conn, config, trigger, reason, settings)
            t0 = time.perf_counter()
            try:
                ner = self._ner_factory(config) if self._ner_factory else None
                result = self._sync(conn, config, ner_predictor=ner, max_articles=settings.max_articles_per_run)
                err = None
            except Exception as exc:  # noqa: BLE001 -- ghi lỗi đã làm sạch, vòng lặp đếm lỗi liên tiếp
                err = safe_error(exc)
                log.warning("đồng bộ RAG lỗi: %s", err)
                self._log_end(conn, run_id, "failed", {"seconds": round(time.perf_counter() - t0, 2)}, err)
                return Decision(False, "failed", err)
            self._log_end(conn, run_id, "ok", result, None)
            log.info("đồng bộ RAG xong (%s): %s bài NER, %s chunk mới", reason, result.get("ner_articles"),
                     result.get("chunks_inserted"))
            return Decision(True, "ok")
        finally:
            end_run(result=result, error=err)

    @staticmethod
    def _log_start(conn, config, trigger, reason, settings) -> int | None:
        try:
            return conn.execute(
                "INSERT INTO worker_runs (step, app_now, versions) VALUES ('rag_sync', now(), %s) RETURNING run_id",
                (Jsonb({"index_version": config.get("index_version"), "trigger": trigger, "reason": reason,
                        "max_articles": settings.max_articles_per_run}),)).fetchone()[0]
        except Exception:  # DB chưa áp 011 (CHECK chưa có 'rag_sync')…: vẫn chạy, chỉ không ghi lịch sử
            log.warning("không ghi được worker_runs rag_sync (chưa áp migration 011?)", exc_info=True)
            return None

    @staticmethod
    def _log_end(conn, run_id, status, stats, error) -> None:
        if run_id is None:
            return
        try:
            conn.execute("UPDATE worker_runs SET status = %s, finished_at = now(), stats = %s, error = %s "
                         "WHERE run_id = %s", (status, Jsonb(stats or {}), error, run_id))
        except Exception:  # stats không tuần tự hoá được, mất kết nối…: không được làm hỏng SYNC_STATE
            log.warning("không cập nhật được worker_runs %s", run_id, exc_info=True)

    def status(self) -> dict[str, Any]:
        d = self.last_decision
        return {"scheduler_running": self.running, "leader": self.leader, "started_at": self.started_at,
                "last_check_at": self.last_check_at, "next_check_at": self.next_check_at if self.running else None,
                "last_decision": d.reason if d else None, "last_decision_error": d.error if d else None,
                "consecutive_failures": self.consecutive_failures}
