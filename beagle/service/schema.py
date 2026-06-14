"""Portable schema for the shared service.

DDL is written to run unchanged on both SQLite and PostgreSQL:

- every primary key is an application-generated ``TEXT`` id (no SERIAL/IDENTITY);
- booleans are ``INTEGER`` 0/1;
- timestamps are ISO-8601 ``TEXT`` (JWT ``iat``/``exp`` are ``INTEGER`` epochs);
- list/object columns are JSON encoded into ``TEXT``.

Migrations are an ordered list of ``(version, [statements])``. The runner applies
any not yet recorded in ``service_schema_versions``.
"""

from __future__ import annotations

_V1 = [
    """
    CREATE TABLE IF NOT EXISTS organizations (
        id TEXT PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL REFERENCES organizations(id),
        username TEXT NOT NULL,
        display_name TEXT NOT NULL,
        email TEXT NOT NULL,
        disabled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        UNIQUE (organization_id, username)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jwt_tokens (
        jti TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        organization_id TEXT NOT NULL REFERENCES organizations(id),
        repositories TEXT NOT NULL,
        permissions TEXT NOT NULL,
        issued_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        revoked INTEGER NOT NULL DEFAULT 0,
        revoked_at TEXT,
        label TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS repositories (
        id TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL REFERENCES organizations(id),
        slug TEXT NOT NULL,
        name TEXT NOT NULL,
        remote_url TEXT,
        default_branch TEXT NOT NULL DEFAULT 'main',
        storage_path TEXT NOT NULL,
        ingestion_state TEXT NOT NULL DEFAULT 'registered',
        created_at TEXT NOT NULL,
        UNIQUE (organization_id, slug)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS repository_access (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        repository_id TEXT NOT NULL REFERENCES repositories(id),
        permissions TEXT NOT NULL,
        granted_at TEXT NOT NULL,
        UNIQUE (user_id, repository_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS git_refs (
        repository_id TEXT NOT NULL REFERENCES repositories(id),
        namespace TEXT NOT NULL,
        ref_name TEXT NOT NULL,
        commit_sha TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (repository_id, ref_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        organization_id TEXT NOT NULL REFERENCES organizations(id),
        repository_id TEXT REFERENCES repositories(id),
        client_name TEXT NOT NULL DEFAULT '',
        client_version TEXT NOT NULL DEFAULT '',
        privacy_mode TEXT NOT NULL DEFAULT 'summary',
        initial_revision TEXT,
        current_revision TEXT,
        workspace_id TEXT,
        started_at TEXT NOT NULL,
        ended_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        user_id TEXT,
        organization_id TEXT,
        repository_id TEXT,
        action TEXT NOT NULL,
        request_id TEXT,
        detail TEXT NOT NULL DEFAULT '{}'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_events(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_repo ON audit_events(repository_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON mcp_sessions(user_id)",
]

_V2 = [
    """
    CREATE TABLE IF NOT EXISTS git_commits (
        repository_id TEXT NOT NULL REFERENCES repositories(id),
        sha TEXT NOT NULL,
        tree_sha TEXT NOT NULL,
        subject TEXT NOT NULL,
        body TEXT NOT NULL DEFAULT '',
        author_name TEXT NOT NULL,
        author_email TEXT NOT NULL,
        author_time INTEGER NOT NULL,
        author_tz TEXT NOT NULL,
        committer_name TEXT NOT NULL,
        committer_email TEXT NOT NULL,
        commit_time INTEGER NOT NULL,
        committer_tz TEXT NOT NULL,
        signature_status TEXT NOT NULL DEFAULT 'N',
        is_merge INTEGER NOT NULL DEFAULT 0,
        files_changed INTEGER,
        insertions INTEGER,
        deletions INTEGER,
        indexed_at TEXT NOT NULL,
        PRIMARY KEY (repository_id, sha)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS git_commit_parents (
        repository_id TEXT NOT NULL,
        child_sha TEXT NOT NULL,
        parent_sha TEXT NOT NULL,
        position INTEGER NOT NULL,
        PRIMARY KEY (repository_id, child_sha, parent_sha)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS git_commit_trailers (
        repository_id TEXT NOT NULL,
        sha TEXT NOT NULL,
        position INTEGER NOT NULL,
        trailer_key TEXT NOT NULL,
        trailer_value TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_commits_time ON git_commits(repository_id, commit_time)",
    "CREATE INDEX IF NOT EXISTS idx_commits_author ON git_commits(repository_id, author_email)",
    "CREATE INDEX IF NOT EXISTS idx_trailers_key ON git_commit_trailers(repository_id, trailer_key)",
    "CREATE INDEX IF NOT EXISTS idx_parents_child ON git_commit_parents(repository_id, child_sha)",
]

_V3 = [
    """
    CREATE TABLE IF NOT EXISTS git_identities (
        organization_id TEXT NOT NULL REFERENCES organizations(id),
        email TEXT NOT NULL,
        name TEXT NOT NULL,
        verified_user_id TEXT REFERENCES users(id),
        verification_method TEXT,
        first_seen INTEGER NOT NULL,
        last_seen INTEGER NOT NULL,
        commit_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (organization_id, email)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_identities_user ON git_identities(verified_user_id)",
]

_V4 = [
    """
    CREATE TABLE IF NOT EXISTS index_snapshots (
        id TEXT PRIMARY KEY,
        repository_id TEXT NOT NULL REFERENCES repositories(id),
        commit_sha TEXT NOT NULL,
        tree_sha TEXT NOT NULL,
        indexer_version TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'indexing',
        file_count INTEGER,
        entity_count INTEGER,
        observation_count INTEGER,
        edge_count INTEGER,
        artifact_path TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        UNIQUE (repository_id, commit_sha)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_snapshots_repo ON index_snapshots(repository_id)",
]

_V5 = [
    """
    CREATE TABLE IF NOT EXISTS change_episodes (
        id TEXT PRIMARY KEY,
        repository_id TEXT NOT NULL REFERENCES repositories(id),
        title TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',
        created_by TEXT NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS decisions (
        id TEXT PRIMARY KEY,
        episode_id TEXT NOT NULL REFERENCES change_episodes(id),
        repository_id TEXT NOT NULL REFERENCES repositories(id),
        problem TEXT NOT NULL DEFAULT '',
        goal TEXT NOT NULL DEFAULT '',
        decision TEXT NOT NULL,
        rationale TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',
        created_by TEXT NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS decision_actors (
        id TEXT PRIMARY KEY,
        decision_id TEXT NOT NULL REFERENCES decisions(id),
        user_id TEXT REFERENCES users(id),
        external_name TEXT,
        role TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 1.0,
        evidence TEXT NOT NULL DEFAULT '',
        confirmation_state TEXT NOT NULL DEFAULT 'inferred'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS decision_entities (
        decision_id TEXT NOT NULL REFERENCES decisions(id),
        repository_id TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        PRIMARY KEY (decision_id, entity_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS feedback (
        id TEXT PRIMARY KEY,
        repository_id TEXT NOT NULL REFERENCES repositories(id),
        episode_id TEXT REFERENCES change_episodes(id),
        comment TEXT NOT NULL,
        author_user_id TEXT NOT NULL REFERENCES users(id),
        revision TEXT,
        entity_id TEXT,
        status TEXT NOT NULL DEFAULT 'received',
        rationale TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_summaries (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES mcp_sessions(id),
        problem TEXT NOT NULL DEFAULT '',
        decision TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_decisions_repo ON decisions(repository_id)",
    "CREATE INDEX IF NOT EXISTS idx_decision_entities_entity ON decision_entities(repository_id, entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_repo ON feedback(repository_id)",
    "CREATE INDEX IF NOT EXISTS idx_actors_decision ON decision_actors(decision_id)",
]

_V6 = [
    """
    CREATE TABLE IF NOT EXISTS dependency_snapshots (
        id TEXT PRIMARY KEY,
        repository_id TEXT NOT NULL REFERENCES repositories(id),
        commit_sha TEXT NOT NULL,
        profile TEXT NOT NULL DEFAULT 'default',
        sources TEXT NOT NULL DEFAULT '[]',
        package_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        UNIQUE (repository_id, commit_sha, profile)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dependency_packages (
        id TEXT PRIMARY KEY,
        snapshot_id TEXT NOT NULL REFERENCES dependency_snapshots(id),
        ecosystem TEXT NOT NULL,
        name TEXT NOT NULL,
        version TEXT NOT NULL,
        hash TEXT,
        source_type TEXT NOT NULL,
        package_group TEXT NOT NULL DEFAULT 'default'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_dep_packages_snapshot ON dependency_packages(snapshot_id)",
    "CREATE INDEX IF NOT EXISTS idx_dep_packages_name ON dependency_packages(name)",
]

_V7 = [
    """
    CREATE TABLE IF NOT EXISTS workspace_overlays (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        repository_id TEXT NOT NULL REFERENCES repositories(id),
        base_commit TEXT NOT NULL,
        patch_hash TEXT NOT NULL DEFAULT '',
        dirty_tree_hash TEXT NOT NULL DEFAULT '',
        patch_path TEXT NOT NULL DEFAULT '',
        snapshot_id TEXT,
        sharing_state TEXT NOT NULL DEFAULT 'private',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        expiry TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workspace_shares (
        workspace_id TEXT NOT NULL REFERENCES workspace_overlays(id),
        user_id TEXT NOT NULL REFERENCES users(id),
        PRIMARY KEY (workspace_id, user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_overlays_user ON workspace_overlays(user_id)",
    # decisions may now reference a workspace and a commit (design §16).
    "ALTER TABLE decisions ADD COLUMN workspace_id TEXT",
    "ALTER TABLE decisions ADD COLUMN commit_sha TEXT",
]

MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, _V1), (2, _V2), (3, _V3), (4, _V4), (5, _V5), (6, _V6), (7, _V7)
]

LATEST_VERSION = MIGRATIONS[-1][0]
