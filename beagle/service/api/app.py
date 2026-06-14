"""FastAPI application factory.

Wires the container, registers routes, and maps :class:`ServiceError` subclasses
to their HTTP status. Construct with an explicit config in tests; in deployment
``create_app()`` reads configuration from the environment.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from beagle.service.api import git_routes, routes
from beagle.service.config import ServiceConfig
from beagle.service.container import ServiceContainer
from beagle.service.errors import ServiceError


def create_app(config: ServiceConfig | None = None) -> FastAPI:
    container = ServiceContainer(config or ServiceConfig.from_env()).setup()
    app = FastAPI(title="Beagle Service", version="0.1.0")
    app.state.container = container
    app.include_router(routes.router)
    app.include_router(git_routes.router)

    @app.exception_handler(ServiceError)
    async def _on_service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "message": str(exc)},
        )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app
