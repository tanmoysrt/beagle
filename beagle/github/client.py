from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlsplit

import httpx

from ..config import GithubCfg
from ..errors import GithubError

log = logging.getLogger("beagle.github.client")

RETRY_STATUSES = {429, 500, 502, 503, 504}
IDEMPOTENT = ("GET", "HEAD")
MAX_PAGES = 20
NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')

THREADS_QUERY = """
query($owner:String!, $name:String!, $number:Int!) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      reviewThreads(first:100) {
        nodes { id isResolved comments(first:1) { nodes { databaseId } } }
      }
    }
  }
}
"""

RESOLVE_MUTATION = """
mutation($id:ID!) { resolveReviewThread(input:{threadId:$id}) { thread { isResolved } } }
"""


class GithubClient:
    """The slice of the GitHub REST API that Beagle needs, and nothing else."""

    def __init__(self, cfg: GithubCfg, timeout: float = 30.0):
        self.repo = cfg.repo
        self.base = f"{cfg.api_url.rstrip('/')}/repos/{cfg.repo}"
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {cfg.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "beagle",
            },
        )

    def repo_info(self) -> dict:
        return self.call("GET", "")

    def open_pulls(self, etag: str | None = None) -> tuple[list[dict] | None, str | None]:
        """A list of open pull requests, or None when nothing changed since the etag."""
        headers = {"If-None-Match": etag} if etag else None
        response = self.request(
            "GET", "/pulls", params={"state": "open", "per_page": 100}, headers=headers
        )
        if response.status_code == 304:
            return None, etag
        self.raise_for(response, "GET", "/pulls")
        pulls = response.json()
        if len(pulls) == 100:
            log.warning("100 open pull requests read; any after that wait for the next poll")
        return pulls, response.headers.get("etag")

    def pull(self, number: int) -> dict:
        return self.call("GET", f"/pulls/{number}")

    def issue_comments(self, number: int) -> list[dict]:
        return self.paged(f"/issues/{number}/comments")

    def review_comments(self, number: int) -> list[dict]:
        return self.paged(f"/pulls/{number}/comments")

    def pull_files(self, number: int) -> list[dict]:
        return self.paged(f"/pulls/{number}/files")

    def review_comment(self, comment_id: int) -> dict:
        return self.call("GET", f"/pulls/comments/{comment_id}")

    def create_issue_comment(self, number: int, body: str) -> dict:
        return self.call("POST", f"/issues/{number}/comments", json={"body": body})

    def update_issue_comment(self, comment_id: int, body: str) -> dict:
        return self.call("PATCH", f"/issues/comments/{comment_id}", json={"body": body})

    def reply_to_review_comment(self, number: int, comment_id: int, body: str) -> dict:
        return self.call(
            "POST", f"/pulls/{number}/comments/{comment_id}/replies", json={"body": body}
        )

    def react(self, path: str, content: str) -> int | None:
        return self.call("POST", f"{path}/reactions", json={"content": content}).get("id")

    def unreact(self, path: str, reaction_id: int) -> None:
        self.call("DELETE", f"{path}/reactions/{reaction_id}")

    def submit_review(
        self,
        number: int,
        event: str,
        body: str,
        comments: list[dict] | None = None,
        commit_id: str | None = None,
    ) -> dict:
        """One review: every new inline comment and the state, in one notification."""
        payload: dict = {"event": event, "body": body}
        if comments:
            payload["comments"] = comments
        if commit_id:
            payload["commit_id"] = commit_id
        return self.call("POST", f"/pulls/{number}/reviews", json=payload)

    def graphql(self, query: str, variables: dict) -> dict:
        """Resolving a thread exists only here, so one GraphQL call earns its place."""
        url = f"{self.base.split('/repos/')[0]}/graphql"
        response = self.request("POST", url, json={"query": query, "variables": variables})
        self.raise_for(response, "POST", "/graphql")
        payload = response.json()
        if payload.get("errors"):
            raise GithubError(f"graphql: {payload['errors'][0].get('message')}")
        return payload.get("data") or {}

    def review_threads(self, number: int) -> dict[int, str]:
        """The node id of each unresolved thread, keyed by its first comment's id."""
        owner, name = self.repo.split("/", 1)
        data = self.graphql(THREADS_QUERY, {"owner": owner, "name": name, "number": number})
        threads = (((data.get("repository") or {}).get("pullRequest") or {})
                   .get("reviewThreads") or {}).get("nodes") or []
        found = {}
        for thread in threads:
            if thread.get("isResolved"):
                continue
            for comment in ((thread.get("comments") or {}).get("nodes") or []):
                if comment.get("databaseId"):
                    found[comment["databaseId"]] = thread["id"]
        return found

    def resolve_thread(self, thread_id: str) -> None:
        self.graphql(RESOLVE_MUTATION, {"id": thread_id})

    def call(self, method: str, path: str, **kwargs) -> dict:
        response = self.request(method, path, **kwargs)
        self.raise_for(response, method, path)
        return response.json() if response.content else {}

    def paged(self, path: str, params: dict | None = None) -> list[dict]:
        items: list[dict] = []
        url, query = path, dict(params or {}, per_page=100)
        for _ in range(MAX_PAGES):
            response = self.request("GET", url, params=query)
            self.raise_for(response, "GET", path)
            items.extend(response.json())
            url, query = self.next_link(response), None
            if not url:
                return items
        log.warning(
            "%s has more than %d pages; beagle read the first %d items only",
            path, MAX_PAGES, len(items),
        )
        return items

    def next_link(self, response: httpx.Response) -> str | None:
        """Only follow a link on the api host: the token travels with it."""
        found = NEXT_LINK.search(response.headers.get("link", ""))
        if not found:
            return None
        link = found.group(1)
        if urlsplit(link)[:2] != urlsplit(self.base)[:2]:
            log.warning("ignoring a next link that leaves the api host: %s", link)
            return None
        return link

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = path if path.startswith(("http://", "https://")) else f"{self.base}{path}"
        response = None
        for attempt in range(2):
            try:
                response = self.client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                raise GithubError(f"github {method} {path} failed: {exc}") from exc
            if attempt == 0 and self.can_repeat(method, response.status_code):
                time.sleep(retry_delay(response))
                continue
            break
        return response

    def can_repeat(self, method: str, status: int) -> bool:
        if status == 429:
            return True
        return status in RETRY_STATUSES and method in IDEMPOTENT

    def raise_for(self, response: httpx.Response, method: str, path: str) -> None:
        if response.status_code < 400:
            return
        detail = response.text[:300].replace("\n", " ")
        raise GithubError(
            f"github {method} {path} returned {response.status_code}: {detail}",
        )

    def close(self) -> None:
        self.client.close()


def retry_delay(response: httpx.Response) -> float:
    retry_after = response.headers.get("retry-after", "")
    return min(float(retry_after), 30.0) if retry_after.isdigit() else 2.0


