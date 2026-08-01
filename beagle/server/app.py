from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ..config import ConfigProvider, load_config
from ..constants import DEFAULT_CONFIG_PATH
from ..errors import BeagleError
from .routes import router
from .service import BeagleService

log = logging.getLogger("beagle")


def build_app(config_path: Path | str = DEFAULT_CONFIG_PATH) -> FastAPI:
    loaded = load_config(config_path)
    provider = ConfigProvider(loaded)
    service = BeagleService(provider, Path(config_path).parent)
    queue = service.queue

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        queue.start()
        log.info(
            "beagle serving repo %s with %d workers",
            provider.current.repo.url,
            provider.current.server.max_parallel_reviews,
        )
        if service.github is not None:
            service.github.start()
        yield
        if service.github is not None:
            service.github.stop()
        queue.stop()
        service.close()

    app = FastAPI(title="beagle", version="0.1.0", lifespan=lifespan)
    app.state.service = service
    app.state.queue = queue
    app.include_router(router)

    @app.exception_handler(BeagleError)
    async def beagle_error(request, exc: BeagleError):
        return JSONResponse(status_code=400, content={"error": str(exc), "kind": type(exc).__name__})

    return app
