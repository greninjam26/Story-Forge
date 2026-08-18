import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from threading import Event as ThreadEvent
from uuid import UUID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.request_limits import ReferencePhotoUploadLimitMiddleware
from app.routers.auth import router as auth_router
from app.routers.billing import router as billing_router
from app.routers.children import router as children_router
from app.routers.media import router as media_router
from app.routers.parents import router as parents_router
from app.routers.reader import router as reader_router
from app.routers.stories import router as stories_router
from app.services import asset_cleanup, safety_config, story_workflow


logger = logging.getLogger(__name__)
WORKER_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def _process_asset_cleanup(
    session_factory: Callable[[], Session],
    _should_stop: Callable[[], bool],
) -> None:
    try:
        with session_factory() as db:
            asset_cleanup.try_process_pending_deletions(db)
    except Exception:
        logger.exception("Background asset cleanup pass failed.")


def _process_story_generation(
    session_factory: Callable[[], Session],
    should_stop: Callable[[], bool],
) -> None:
    story_workflow.try_process_pending_stories(
        session_factory,
        limit=1,
        should_stop=should_stop,
    )


def _process_notified_story(
    session_factory: Callable[[], Session],
    story_id: UUID,
    should_stop: Callable[[], bool],
) -> None:
    try:
        story_workflow.process_queued_story(
            session_factory,
            story_id,
            should_stop=should_stop,
        )
    except Exception as error:
        logger.error(
            "Notified story generation failed with category %s.",
            type(error).__name__,
        )


async def _interval_worker(
    job: Callable[
        [Callable[[], Session], Callable[[], bool]],
        None,
    ],
    session_factory: Callable[[], Session],
    interval_seconds: float,
    stop: asyncio.Event,
) -> None:
    if not stop.is_set():
        await asyncio.to_thread(job, session_factory, stop.is_set)

    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            await asyncio.to_thread(job, session_factory, stop.is_set)


async def _story_generation_worker(
    session_factory: Callable[[], Session],
    interval_seconds: float,
    stop: asyncio.Event,
    stop_requested: ThreadEvent,
    notified_stories: asyncio.Queue[UUID | None],
    *,
    recovery_enabled: bool,
) -> None:
    event_loop = asyncio.get_running_loop()
    next_recovery_at: float | None = None
    if recovery_enabled and not stop.is_set():
        await asyncio.to_thread(
            _process_story_generation,
            session_factory,
            stop_requested.is_set,
        )
        next_recovery_at = event_loop.time() + interval_seconds

    while not stop.is_set():
        if (
            next_recovery_at is not None
            and event_loop.time() >= next_recovery_at
        ):
            await asyncio.to_thread(
                _process_story_generation,
                session_factory,
                stop_requested.is_set,
            )
            next_recovery_at = event_loop.time() + interval_seconds
            continue
        try:
            if recovery_enabled:
                assert next_recovery_at is not None
                story_id = await asyncio.wait_for(
                    notified_stories.get(),
                    timeout=max(
                        0,
                        next_recovery_at - event_loop.time(),
                    ),
                )
            else:
                story_id = await notified_stories.get()
        except TimeoutError:
            await asyncio.to_thread(
                _process_story_generation,
                session_factory,
                stop_requested.is_set,
            )
            next_recovery_at = event_loop.time() + interval_seconds
            continue
        if story_id is None or stop.is_set():
            return
        await asyncio.to_thread(
            _process_notified_story,
            session_factory,
            story_id,
            stop_requested.is_set,
        )


@asynccontextmanager
async def lifespan(application: FastAPI):
    from app import observability

    observability.init()
    safety_config.validate_production_configuration()
    stop = asyncio.Event()
    stop_requested = ThreadEvent()
    notified_stories: asyncio.Queue[UUID | None] = asyncio.Queue()
    event_loop = asyncio.get_running_loop()

    def notify_story_generation(story_id: UUID) -> None:
        event_loop.call_soon_threadsafe(
            notified_stories.put_nowait,
            story_id,
        )

    application.state.generation_worker_stop = stop_requested
    application.state.notify_story_generation = notify_story_generation
    workers: list[tuple[str, asyncio.Task[None]]] = []
    if settings.asset_cleanup_worker_enabled:
        workers.append(
            (
                "asset cleanup",
                asyncio.create_task(
                    _interval_worker(
                        _process_asset_cleanup,
                        application.state.asset_cleanup_session_factory,
                        settings.asset_cleanup_worker_interval_seconds,
                        stop,
                    )
                ),
            )
        )
    workers.append(
        (
            "story generation",
            asyncio.create_task(
                _story_generation_worker(
                    application.state.story_generation_session_factory,
                    settings.story_generation_worker_interval_seconds,
                    stop,
                    stop_requested,
                    notified_stories,
                    recovery_enabled=(
                        settings.story_generation_worker_enabled
                    ),
                )
            ),
        )
    )

    try:
        yield
    finally:
        stop_requested.set()
        stop.set()
        notified_stories.put_nowait(None)
        for worker_name, worker in workers:
            try:
                await asyncio.wait_for(
                    asyncio.shield(worker),
                    timeout=WORKER_SHUTDOWN_TIMEOUT_SECONDS,
                )
            except (TimeoutError, asyncio.CancelledError):
                logger.warning(
                    "%s worker did not stop in time; cancelling.",
                    worker_name.capitalize(),
                )
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass


app = FastAPI(title="Story Forge API", lifespan=lifespan)
app.state.asset_cleanup_session_factory = SessionLocal
app.state.story_generation_session_factory = SessionLocal

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ReferencePhotoUploadLimitMiddleware)

app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(parents_router)
app.include_router(children_router)
app.include_router(stories_router)
app.include_router(reader_router)
app.include_router(media_router)


@app.get("/health")
def health(response: Response) -> dict[str, object]:
    components: dict[str, str] = {}
    status_code = 200

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception:
        logger.exception("health check: database unreachable")
        components["database"] = "unreachable"
        status_code = 503

    response.status_code = status_code
    return {
        "status": "ok" if status_code == 200 else "degraded",
        "components": components,
    }
