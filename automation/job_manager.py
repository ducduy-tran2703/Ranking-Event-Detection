from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import logging
import threading
from uuid import uuid4

from .config import SOURCES
from .pipeline import Pipeline
from .scheduler import clock_now, slot_at, next_slot
from .state import now_iso
from .storage import ProcessLock, read_json, write_json

logger = logging.getLogger(__name__)


class JobConflict(RuntimeError):
    pass


class JobManager:
    def __init__(self, settings, pipeline_factory=Pipeline):
        self.settings = settings
        self.root = settings.data_dir
        self.lock = threading.RLock()
        self.process_lock = ProcessLock(self.root / "state" / "instance.lock")
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.active_id = None
        self.executor = None
        self.thread = None
        self.pipeline_factory = pipeline_factory

    @property
    def schedule_path(self):
        return self.root / "state" / "schedule.json"

    def start(self):
        self.process_lock.acquire()
        try:
            self.schedule = read_json(self.schedule_path, {
                "enabled": self.settings.scheduler_enabled, "interval_minutes": 30,
                "sources": list(SOURCES), "last_slot": None, "last_event": None})
            # Running records from a dead process are retained as interrupted.
            interrupted = False
            for path in (self.root / "jobs").glob("*/job.json"):
                record = read_json(path)
                if record["status"] in ("queued", "running"):
                    interrupted = True
                    record.update(status="interrupted", finished_at=now_iso())
                    write_json(path, record)
            if interrupted:
                self.schedule["last_slot"] = None
            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job")
            self.thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
            self.thread.start()
        except BaseException:
            if self.executor:
                self.executor.shutdown(wait=True)
            self.process_lock.release()
            raise

    def close(self):
        self.stop.set()
        self.wake.set()
        try:
            if self.thread:
                self.thread.join()
            if self.executor:
                self.executor.shutdown(wait=True)
        finally:
            self.process_lock.release()

    def job_path(self, job_id):
        # API path parameters must not turn into arbitrary filesystem paths.
        from uuid import UUID
        try:
            if UUID(job_id).hex != job_id:
                raise ValueError
        except (ValueError, AttributeError):
            raise KeyError(job_id)
        return self.root / "jobs" / job_id / "job.json"

    def get(self, job_id):
        with self.lock:
            job = read_json(self.job_path(job_id))
            if job is None:
                raise KeyError(job_id)
            return job

    def list_jobs(self, limit=20, offset=0):
        with self.lock:
            jobs = [read_json(path) for path in (self.root / "jobs").glob("*/job.json")]
            jobs.sort(key=lambda j: j["created_at"], reverse=True)
            return {"total": len(jobs), "items": jobs[offset:offset + limit]}

    def submit(self, sources=None, trigger="manual", retry_failed=False):
        with self.lock:
            if self.stop.is_set():
                raise JobConflict("Application is shutting down")
            if self.active_id:
                raise JobConflict(f"Job {self.active_id} is still running")
            sources = list(dict.fromkeys(sources if sources is not None else SOURCES))
            if not sources or any(s not in SOURCES for s in sources):
                raise ValueError("Select at least one supported source")
            job = {"id": uuid4().hex, "trigger": trigger, "sources": sources,
                   "status": "queued", "created_at": now_iso(), "started_at": None,
                   "finished_at": None, "results": {}, "retry_failed": retry_failed}
            write_json(self.job_path(job["id"]), job)
            self.active_id = job["id"]
            try:
                self.executor.submit(self._run, deepcopy(job))
            except BaseException:
                self.active_id = None
                job.update(status="failed", finished_at=now_iso())
                write_json(self.job_path(job["id"]), job)
                raise
            return job

    def _run(self, job):
        try:
            with self.lock:
                job.update(status="running", started_at=now_iso())
                write_json(self.job_path(job["id"]), job)

            def report(source, value):
                with self.lock:
                    job["results"][source] = deepcopy(value)
                    write_json(self.job_path(job["id"]), job)

            results = self.pipeline_factory(self.settings, self.stop).run(job, report, job["retry_failed"])
            statuses = [r["status"] for r in results.values()]
            job["status"] = ("completed" if all(s == "completed" for s in statuses)
                             else "interrupted" if self.stop.is_set() else "partial")
        except Exception as exc:
            logger.exception("Job %s failed", job["id"])
            job.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            with self.lock:
                job["finished_at"] = now_iso()
                try:
                    write_json(self.job_path(job["id"]), job)
                finally:
                    self.active_id = None

    def get_schedule(self):
        with self.lock:
            result = deepcopy(self.schedule)
            result.update(timezone="Asia/Ho_Chi_Minh", active_job_id=self.active_id,
                          next_run_at=(next_slot(clock_now(), result["interval_minutes"]).isoformat()
                                       if result["enabled"] else None))
            return result

    def update_schedule(self, changes):
        with self.lock:
            updated = {**self.schedule, **changes}
            interval = updated["interval_minutes"]
            if interval not in (5, 10, 15, 20, 30, 60):
                raise ValueError("interval_minutes must divide 60: 5, 10, 15, 20, 30, 60")
            if not updated["sources"] or any(s not in SOURCES for s in updated["sources"]):
                raise ValueError("Invalid sources")
            # Enabling/changing a schedule starts from the next wall-clock slot.
            # It does not replay time deliberately spent with the schedule off.
            if (updated["enabled"] and not self.schedule["enabled"]) or interval != self.schedule["interval_minutes"]:
                updated["last_slot"] = slot_at(clock_now(), interval).isoformat()
            write_json(self.schedule_path, updated)
            self.schedule = updated
            self.wake.set()
            return self.get_schedule()

    def tick(self, now=None):
        """One durable decision per wall-clock slot, called on startup too."""
        now = now or clock_now()
        with self.lock:
            if not self.schedule["enabled"] or self.stop.is_set():
                return
            slot = slot_at(now, self.schedule["interval_minutes"])
            previous = self.schedule["last_slot"]
            if previous and datetime.fromisoformat(previous) >= slot:
                return
            event = {"at": now.isoformat(), "slot": slot.isoformat()}
            if self.active_id:
                event.update(action="skipped", reason="previous_job_running", job_id=self.active_id)
            else:
                job = self.submit(self.schedule["sources"],
                                  trigger="scheduled" if (now - slot).total_seconds() < 5 else "catch_up")
                event.update(action="submitted", job_id=job["id"])
            self.schedule.update(last_slot=slot.isoformat(), last_event=event)
            write_json(self.schedule_path, self.schedule)

    def _loop(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("Scheduler tick failed")
            self.wake.wait(1)
            self.wake.clear()
