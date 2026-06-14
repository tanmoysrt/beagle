"""Git Smart-HTTP transport route.

Delegates to :class:`SmartHttpHandler`, which authenticates, authorizes, and
proxies to ``git http-backend``. Git objects travel here, never through the JSON
API (design/15 §21). The repository id is the bare-mirror name; the trailing
path is the Git service endpoint (``info/refs``, ``git-upload-pack``, ...).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from beagle.service.api.context import container_of

router = APIRouter()


@router.api_route("/git/{repository_id}.git/{git_path:path}", methods=["GET", "POST"])
async def git_transport(
    request: Request, repository_id: str, git_path: str
) -> Response:
    container = container_of(request)
    body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    result = container.smart_http.handle(
        method=request.method,
        repository_id=repository_id,
        subpath=git_path,
        query_string=request.url.query,
        headers=headers,
        body=body,
    )
    return Response(
        content=result.body,
        status_code=result.status_code,
        headers=result.headers,
    )
