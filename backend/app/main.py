from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.db import SessionLocal, engine, init_db
from app.db_migrations import run_db_migrations
from app.routers import cv, health, insights, interactions, scheduler, searches, sessions
from app.routers import settings as settings_router
from app.services.desktop_bootstrap import prepare_desktop_runtime
from app.services.scheduler_service import SearchScheduler
from app.services.search_service import ensure_scheduler_state

_scheduler: SearchScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler

    prepare_desktop_runtime()
    init_db()
    run_db_migrations(engine)

    with SessionLocal() as db:
        state = ensure_scheduler_state(db, interval_minutes=settings.scheduler_interval_minutes)
        # Safety: do not auto-resume background writer on startup from stale persisted state.
        state_changed = False
        if state.is_running:
            state.is_running = False
            state_changed = True
        if state.interval_minutes != settings.scheduler_interval_minutes:
            state.interval_minutes = settings.scheduler_interval_minutes
            state_changed = True
        if state_changed:
            db.add(state)
            try:
                db.commit()
            except OperationalError:
                db.rollback()

    _scheduler = SearchScheduler(SessionLocal, poll_seconds=settings.scheduler_poll_seconds)
    await _scheduler.start()

    yield

    if _scheduler:
        await _scheduler.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(cv.router, prefix="/api")
app.include_router(searches.router, prefix="/api")
app.include_router(interactions.router, prefix="/api")
app.include_router(insights.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")
app.include_router(scheduler.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
