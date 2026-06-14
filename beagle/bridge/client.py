"""HTTP + Git client for the shared service (design/15 §21).

JSON requests go over the service API; Git objects move over Git Smart HTTP via
``git push`` (never JSON payloads). Uses only the standard library so the bridge
has no extra runtime dependency.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request

from beagle.service.errors import AuthenticationError, NotFound, ServiceError
from beagle.bridge.local_repo import LocalRepository


class ServiceClient:
    """Talks to one shared service with one bearer token."""

    def __init__(self, service_url: str, token: str, git_binary: str = "git"):
        self._base = service_url.rstrip("/")
        self._token = token
        self._git = git_binary

    def whoami(self) -> dict:
        return self._request("GET", "/v1/me")

    def list_repositories(self) -> list[dict]:
        return self._request("GET", "/v1/repositories")["repositories"]

    def find_repository(self, slug: str) -> dict:
        for repo in self.list_repositories():
            if repo["slug"] == slug:
                return repo
        raise NotFound(f"repository not found on service: {slug}")

    def sync_status(self, repository_id: str, head: str) -> dict:
        return self._request(
            "GET", f"/v1/repositories/{repository_id}/sync-status?head={head}"
        )

    def index_revision(self, repository_id: str, revision: str) -> dict:
        return self._request(
            "POST", f"/v1/repositories/{repository_id}/revisions/{revision}/index"
        )

    def push_ref(
        self, local: LocalRepository, repository_id: str, refspec: str
    ) -> None:
        """Push local objects to the service over authenticated Git Smart HTTP."""
        url = f"{self._base}/git/{repository_id}.git"
        env = {
            **os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true",
        }
        result = subprocess.run(
            [self._git, "-c", f"http.extraHeader=Authorization: Bearer {self._token}",
             "-c", "credential.helper=", "push", url, refspec],
            cwd=str(local.root), env=env, capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise ServiceError(f"git push failed: {result.stderr.strip()}")

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self._base}{path}", data=data, method=method,
            headers={"Authorization": f"Bearer {self._token}",
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            self._raise(exc)

    @staticmethod
    def _raise(exc: urllib.error.HTTPError) -> None:
        message = exc.read().decode(errors="replace")
        if exc.code == 401:
            raise AuthenticationError(message)
        if exc.code == 404:
            raise NotFound(message)
        raise ServiceError(f"service error {exc.code}: {message}")
