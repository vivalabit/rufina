import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.applications import router as applications_router
from app.api.assistant import router as assistant_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.job_search import router as job_search_router
from app.api.jobs import router as jobs_router
from app.api.parsers import router as parsers_router
from app.api.profile import router as profile_router
from app.api.privacy import router as privacy_router
from app.api.resume_tailoring import router as resume_tailoring_router
from app.api.resume_templates import router as resume_templates_router
from app.api.settings import router as settings_router
from app.core.migrations import upgrade_database
from app.core.settings import get_settings
from app.services.job_search_worker import run_job_search_worker
from app.services.storage_cleanup import run_expiration_cleanup

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    upgrade_database()
    job_search_stop = asyncio.Event()
    cleanup_task = asyncio.create_task(
        run_expiration_cleanup(settings.storage_cleanup_interval_seconds),
        name="storage-expiration-cleanup",
    )
    job_search_task = asyncio.create_task(
        run_job_search_worker(
            settings.job_search_poll_interval_seconds,
            settings=settings,
            stop_event=job_search_stop,
        ),
        name="automatic-job-search-worker",
    )
    try:
        yield
    finally:
        job_search_stop.set()
        await job_search_task
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


app = FastAPI(
    title="Rufina API",
    version="0.1.0",
    description="Backend skeleton for the personal AI job search assistant.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Content-Disposition",
        "X-Rufina-Document-Id",
        "X-Rufina-Document-Version",
        "X-Rufina-Template-Id",
        "X-Rufina-Template-Version",
        "X-Rufina-Design-Sha256",
    ],
)

app.include_router(health_router, prefix="/health", tags=["health"])
app.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
app.include_router(job_search_router, prefix="/job-search", tags=["job search"])
app.include_router(applications_router, prefix="/applications", tags=["applications"])
app.include_router(assistant_router, prefix="/assistant", tags=["assistant"])
app.include_router(
    conversations_router,
    prefix="/assistant/conversations",
    tags=["assistant conversations"],
)
app.include_router(documents_router, prefix="/documents", tags=["documents"])
app.include_router(parsers_router, prefix="/parsers", tags=["parsers"])
app.include_router(profile_router, prefix="/profile", tags=["profile"])
app.include_router(
    resume_tailoring_router,
    prefix="/resume-tailoring",
    tags=["resume tailoring"],
)
app.include_router(
    resume_templates_router,
    prefix="/resume-templates",
    tags=["resume templates"],
)
app.include_router(privacy_router, prefix="/privacy", tags=["privacy"])
app.include_router(settings_router, prefix="/settings", tags=["settings"])


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "rufina-api", "status": "ready"}
