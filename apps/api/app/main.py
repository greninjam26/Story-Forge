import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.request_limits import ReferencePhotoUploadLimitMiddleware
from app.routers.children import router as children_router
from app.routers.media import router as media_router
from app.routers.parents import router as parents_router
from app.routers.reader import router as reader_router
from app.routers.stories import router as stories_router
from app.services import asset_cleanup


logger = logging.getLogger(__name__)
WORKER_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def _process_asset_cleanup(
    session_factory: Callable[[], Session],
) -> None:
    try:
        with session_factory() as db:
            asset_cleanup.try_process_pending_deletions(db)
    except Exception:
        logger.exception("Background asset cleanup pass failed.")


async def _asset_cleanup_worker(
    session_factory: Callable[[], Session],
    interval_seconds: float,
    stop: asyncio.Event,
) -> None:
    if not stop.is_set():
        await asyncio.to_thread(_process_asset_cleanup, session_factory)

    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            await asyncio.to_thread(_process_asset_cleanup, session_factory)


@asynccontextmanager
async def lifespan(application: FastAPI):
    stop = asyncio.Event()
    worker: asyncio.Task[None] | None = None
    if settings.asset_cleanup_worker_enabled:
        worker = asyncio.create_task(
            _asset_cleanup_worker(
                application.state.asset_cleanup_session_factory,
                settings.asset_cleanup_worker_interval_seconds,
                stop,
            )
        )

    try:
        yield
    finally:
        stop.set()
        if worker is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(worker),
                    timeout=WORKER_SHUTDOWN_TIMEOUT_SECONDS,
                )
            except (TimeoutError, asyncio.CancelledError):
                logger.warning(
                    "Asset cleanup worker did not stop in time; cancelling."
                )
                worker.cancel()


app = FastAPI(title="Story Forge API", lifespan=lifespan)
app.state.asset_cleanup_session_factory = SessionLocal

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ReferencePhotoUploadLimitMiddleware)

app.include_router(parents_router)
app.include_router(children_router)
app.include_router(stories_router)
app.include_router(reader_router)
app.include_router(media_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
