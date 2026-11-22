from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.db import engine, init_db
from app.core.errors import register_error_handlers
from app.diagnostics.router import router as diagnostics_router
from app.framing.router import assets_router, framing_router, profiles_router
from app.projects.router import router as projects_router
from app.settings.router import router as settings_router
from app.captions.router import router as captions_router
from app.exports.router import router as exports_router
from app.exports.service import shutdown_export_jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize SQLite tables
    await init_db()
    try:
        yield
    finally:
        # Stop and reap active export subprocesses before the API process exits.
        await shutdown_export_jobs()
        # Shutdown: Dispose engine connection pool
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    # Register Problem Details error handlers
    register_error_handlers(app)

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API Routers
    app.include_router(diagnostics_router)
    app.include_router(settings_router)
    app.include_router(projects_router)
    app.include_router(profiles_router)
    app.include_router(assets_router)
    app.include_router(framing_router)
    app.include_router(captions_router)
    app.include_router(exports_router)

    # Dynamic static file and SPA serving
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        dist_dir = settings.frontend_dist_dir
        index_file = dist_dir / "index.html"

        if dist_dir.exists() and index_file.exists():
            file_path = dist_dir / full_path
            # Check if requesting a direct existing static file
            if full_path and file_path.is_file():
                return FileResponse(file_path)
            # Fallback to index.html for client-side SPA routing
            return FileResponse(index_file)

        # Fallback when frontend dist is not yet built
        return JSONResponse(
            {
                "app": settings.app_name,
                "version": settings.app_version,
                "status": "ready",
                "apiDocs": "/docs",
                "diagnostics": "/api/diagnostics",
                "settings": "/api/settings",
                "note": "Frontend dist not found. Run 'npm run build' inside frontend/ to serve the UI shell.",
            }
        )

    return app


app = create_app()
