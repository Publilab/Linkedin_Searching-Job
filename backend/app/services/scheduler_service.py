from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.services.search_service import run_all_active_searches, scheduler_status


class SearchScheduler:
    def __init__(self, session_factory: sessionmaker, poll_seconds: int = 15):
        self._session_factory = session_factory
        self._poll_seconds = poll_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="linkedin-search-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(self._poll_seconds)

            with self._session_factory() as db:
                state = scheduler_status(db)
                if not state.is_running:
                    continue
                now = datetime.utcnow()
                if state.last_tick_at and now - state.last_tick_at < timedelta(minutes=state.interval_minutes):
                    continue
                state.last_tick_at = now
                db.add(state)
                db.commit()

            await asyncio.to_thread(run_all_active_searches, self._session_factory)
