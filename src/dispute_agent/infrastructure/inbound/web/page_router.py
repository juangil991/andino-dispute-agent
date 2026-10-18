"""Router de la página de chat (`GET /`) y de sus recursos estáticos (spec 008, RN-008-02)."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def build_page_router() -> APIRouter:
    router = APIRouter()

    @router.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html", media_type="text/html")

    return router


def static_files() -> StaticFiles:
    return StaticFiles(directory=_STATIC_DIR)
