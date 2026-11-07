from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from automation.config import Settings
from automation.job_manager import JobManager, JobConflict
from .schemas import CrawlRequest, ScheduleUpdate


def create_app(settings=None, manager_factory=JobManager):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        manager = manager_factory(settings)
        manager.start()
        app.state.manager = manager
        try:
            yield
        finally:
            # The blocking join runs outside the event-loop thread.
            import asyncio
            await asyncio.to_thread(manager.close)

    app = FastAPI(title="News Crawler", version="1.0.0", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok", "active_job_id": app.state.manager.active_id}

    @app.post("/crawl/jobs", status_code=202)
    def start_job(body: CrawlRequest):
        try:
            return app.state.manager.submit(body.sources, retry_failed=body.retry_failed)
        except JobConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/crawl/jobs")
    def list_jobs(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        return app.state.manager.list_jobs(limit, offset)

    @app.get("/crawl/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return app.state.manager.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get("/crawl/schedule")
    def get_schedule():
        return app.state.manager.get_schedule()

    @app.patch("/crawl/schedule")
    def update_schedule(body: ScheduleUpdate):
        if any(value is None for value in body.model_dump(exclude_unset=True).values()):
            raise HTTPException(status_code=422, detail="Schedule fields cannot be null")
        try:
            return app.state.manager.update_schedule(body.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app


app = create_app()
