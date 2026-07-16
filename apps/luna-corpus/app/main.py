"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.agent_routes import router as agent_router
from app.api.agent_runs_routes import router as agent_runs_router
from app.api.auth_routes import router as auth_router
from app.api.cost_routes import router as cost_router
from app.api.metadata_routes import router as metadata_router
from app.api.routes import router
from app.api.tenant_routes import router as tenant_router
from app.core.config import get_settings
from app.db.database import init_db
from app.observability.logging import configure_logging
from app.observability.metrics import render_metrics
from app.observability.middleware import MetricsMiddleware
from app.security.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    if settings.auto_create_tables:
        init_db()
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging(settings)

    app = FastAPI(
        title="Luna-Corpus API",
        description="RAG-based Q&A Knowledge Base System",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(MetricsMiddleware)

    app.include_router(auth_router)
    app.include_router(router)
    app.include_router(agent_router)
    app.include_router(agent_runs_router)
    app.include_router(tenant_router)
    app.include_router(metadata_router)
    app.include_router(cost_router)

    @app.get("/")
    async def root():
        """Root endpoint."""
        return {"message": "Luna-Corpus API", "version": "1.0.0"}

    @app.get("/metrics")
    async def metrics():
        if not settings.metrics_enabled:
            raise HTTPException(status_code=404, detail="Not found")
        body, content_type = render_metrics()
        return Response(content=body, media_type=content_type)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_env != "production",
    )
