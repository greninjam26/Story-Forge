from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers.children import router as children_router
from app.routers.parents import router as parents_router
from app.routers.reader import router as reader_router
from app.routers.stories import router as stories_router

app = FastAPI(title="Story Forge API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(parents_router)
app.include_router(children_router)
app.include_router(stories_router)
app.include_router(reader_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
