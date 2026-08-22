from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import SessionLocal, init_database
from .routes.accounts import router as accounts_router
from .routes.admin_draws import router as admin_draws_router
from .routes.admin_collections import router as admin_collections_router
from .routes.admin_sets import router as admin_sets_router
from .routes.auth import router as auth_router
from .routes.cards import router as cards_router
from .routes.collections import router as collections_router
from .routes.draws import router as draws_router
from .routes.gifts import router as gifts_router
from .routes.trades import router as trades_router
from .services.trades import cancel_all_active_rooms


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite"):
        init_database()
    with SessionLocal() as db:
        cancel_all_active_rooms(db)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Youngho Gacha", version="0.1.0", lifespan=lifespan)
    app.state.session_factory = SessionLocal
    app.include_router(auth_router)
    app.include_router(accounts_router)
    app.include_router(admin_draws_router)
    app.include_router(admin_collections_router)
    app.include_router(admin_sets_router)
    app.include_router(cards_router)
    app.include_router(collections_router)
    app.include_router(draws_router)
    app.include_router(gifts_router)
    app.include_router(trades_router)

    @app.get("/api/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    if settings.static_dir.exists():
        assets = settings.static_dir / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            candidate = settings.static_dir / path
            if path and candidate.is_file() and settings.static_dir in candidate.resolve().parents:
                return FileResponse(candidate)
            return FileResponse(settings.static_dir / "index.html")

    return app


app = create_app()
