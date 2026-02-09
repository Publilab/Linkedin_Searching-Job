from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import SchedulerStartIn, SchedulerStatusOut
from app.services.search_service import scheduler_status, set_scheduler_running

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.post("/start", response_model=SchedulerStatusOut)
def start_scheduler(payload: SchedulerStartIn, db: Session = Depends(get_db)) -> SchedulerStatusOut:
    state = set_scheduler_running(
        db,
        running=True,
        interval_minutes=payload.interval_minutes,
    )
    return SchedulerStatusOut(
        is_running=state.is_running,
        interval_minutes=state.interval_minutes,
        last_tick_at=state.last_tick_at,
    )


@router.post("/stop", response_model=SchedulerStatusOut)
def stop_scheduler(db: Session = Depends(get_db)) -> SchedulerStatusOut:
    state = set_scheduler_running(db, running=False)
    return SchedulerStatusOut(
        is_running=state.is_running,
        interval_minutes=state.interval_minutes,
        last_tick_at=state.last_tick_at,
    )


@router.get("/status", response_model=SchedulerStatusOut)
def get_scheduler_status(db: Session = Depends(get_db)) -> SchedulerStatusOut:
    state = scheduler_status(db)
    return SchedulerStatusOut(
        is_running=state.is_running,
        interval_minutes=state.interval_minutes,
        last_tick_at=state.last_tick_at,
    )
