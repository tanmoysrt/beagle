"""Dependency snapshot persistence (design/15 §11, §13, §14).

A dependency snapshot is identified by repository + commit + runtime profile and
catalogs the pinned packages parsed from that revision's lockfiles. Package rows
carry the artifact hash so artifacts can later be cached and verified by hash.
"""

from __future__ import annotations

import json

from beagle.service import ids
from beagle.service.clock import now_iso
from beagle.service.db import Connection
from beagle.service.dependencies import ParsedPackage
from beagle.service.errors import NotFound


class DependencyStore:
    """Persists and queries dependency snapshots and their packages."""

    def replace_snapshot(
        self, conn: Connection, repository_id: str, commit_sha: str, profile: str,
        sources: list[str], packages: list[ParsedPackage],
    ) -> str:
        existing = conn.fetch_one(
            "SELECT id FROM dependency_snapshots WHERE repository_id = ?"
            " AND commit_sha = ? AND profile = ?",
            (repository_id, commit_sha, profile),
        )
        if existing:
            conn.execute(
                "DELETE FROM dependency_packages WHERE snapshot_id = ?", (existing["id"],)
            )
            conn.execute(
                "DELETE FROM dependency_snapshots WHERE id = ?", (existing["id"],)
            )
        snapshot_id = ids._new("dep")
        conn.execute(
            "INSERT INTO dependency_snapshots(id, repository_id, commit_sha, profile,"
            " sources, package_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (snapshot_id, repository_id, commit_sha, profile, json.dumps(sources),
             len(packages), now_iso()),
        )
        for package in packages:
            self._insert_package(conn, snapshot_id, package)
        return snapshot_id

    def _insert_package(
        self, conn: Connection, snapshot_id: str, package: ParsedPackage
    ) -> None:
        conn.execute(
            "INSERT INTO dependency_packages(id, snapshot_id, ecosystem, name, version,"
            " hash, source_type, package_group) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ids._new("pkg"), snapshot_id, package.ecosystem, package.name,
             package.version, package.hash, package.source_type, package.group),
        )

    def get_snapshot(
        self, conn: Connection, repository_id: str, commit_sha: str, profile: str = "default"
    ) -> dict:
        row = conn.fetch_one(
            "SELECT * FROM dependency_snapshots WHERE repository_id = ?"
            " AND commit_sha = ? AND profile = ?",
            (repository_id, commit_sha, profile),
        )
        if not row:
            raise NotFound(f"dependency snapshot not found: {commit_sha}")
        row["sources"] = json.loads(row["sources"])
        row["packages"] = conn.fetch_all(
            "SELECT ecosystem, name, version, hash, source_type, package_group"
            " FROM dependency_packages WHERE snapshot_id = ? ORDER BY ecosystem, name",
            (row["id"],),
        )
        return row

    def search_packages(
        self, conn: Connection, repository_id: str, name: str, limit: int = 50
    ) -> list[dict]:
        return conn.fetch_all(
            "SELECT p.ecosystem, p.name, p.version, p.source_type, s.commit_sha"
            " FROM dependency_packages p JOIN dependency_snapshots s ON s.id = p.snapshot_id"
            " WHERE s.repository_id = ? AND lower(p.name) LIKE ?"
            " ORDER BY p.name LIMIT ?",
            (repository_id, f"%{name.lower()}%", limit),
        )
