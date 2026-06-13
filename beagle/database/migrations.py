"""Schema migrations.

Each entry is ``(version, sql)``. Migrations apply in order; ``schema_versions``
records which have run so re-opening a database is idempotent.

Design constraints (see design/03-data-model.md):
- three layers: entities, observations, resolved edges;
- every edge carries confidence, resolver, evidence, owner file, source range;
- stable IDs never contain line numbers;
- deleting/changing a file must remove every fact it owns in one transaction,
  which is why entities/observations/edges/text_chunks all carry ``owner_file``.
"""

from __future__ import annotations

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE index_runs (
            id          INTEGER PRIMARY KEY,
            root        TEXT NOT NULL,
            started_at  REAL NOT NULL,
            finished_at REAL,
            status      TEXT NOT NULL,
            files_indexed INTEGER NOT NULL DEFAULT 0,
            summary_json TEXT
        );

        CREATE TABLE files (
            id       INTEGER PRIMARY KEY,
            path     TEXT NOT NULL UNIQUE,
            language TEXT NOT NULL,
            hash     TEXT NOT NULL,
            size     INTEGER NOT NULL,
            mtime    REAL NOT NULL,
            run_id   INTEGER REFERENCES index_runs(id) ON DELETE SET NULL
        );

        CREATE TABLE entities (
            id             TEXT PRIMARY KEY,
            kind           TEXT NOT NULL,
            name           TEXT NOT NULL,
            qualified_name TEXT NOT NULL,
            owner_file     TEXT NOT NULL,
            start_line     INTEGER NOT NULL,
            start_col      INTEGER NOT NULL,
            end_line       INTEGER NOT NULL,
            end_col        INTEGER NOT NULL,
            signature      TEXT,
            docstring      TEXT,
            extra_json     TEXT
        );
        CREATE INDEX idx_entities_owner ON entities(owner_file);
        CREATE INDEX idx_entities_name ON entities(name);
        CREATE INDEX idx_entities_qname ON entities(qualified_name);
        CREATE INDEX idx_entities_kind ON entities(kind);

        CREATE TABLE observations (
            id          INTEGER PRIMARY KEY,
            kind        TEXT NOT NULL,
            owner_file  TEXT NOT NULL,
            subject     TEXT NOT NULL,
            start_line  INTEGER NOT NULL,
            start_col   INTEGER NOT NULL,
            end_line    INTEGER NOT NULL,
            end_col     INTEGER NOT NULL,
            data_json   TEXT
        );
        CREATE INDEX idx_observations_owner ON observations(owner_file);
        CREATE INDEX idx_observations_subject ON observations(subject);
        CREATE INDEX idx_observations_kind ON observations(kind);

        CREATE TABLE edges (
            id               INTEGER PRIMARY KEY,
            source_id        TEXT NOT NULL,
            target_id        TEXT,
            target_hint      TEXT,
            relationship     TEXT NOT NULL,
            confidence       REAL NOT NULL,
            resolver         TEXT NOT NULL,
            resolver_version TEXT NOT NULL,
            observation_id   INTEGER,
            owner_file       TEXT NOT NULL,
            start_line       INTEGER NOT NULL,
            start_col        INTEGER NOT NULL,
            end_line         INTEGER NOT NULL,
            end_col          INTEGER NOT NULL,
            evidence_json    TEXT
        );
        CREATE INDEX idx_edges_owner ON edges(owner_file);
        CREATE INDEX idx_edges_source ON edges(source_id);
        CREATE INDEX idx_edges_target ON edges(target_id);
        CREATE INDEX idx_edges_rel ON edges(relationship);

        CREATE TABLE text_chunks (
            id          INTEGER PRIMARY KEY,
            owner_file  TEXT NOT NULL,
            entity_id   TEXT,
            kind        TEXT NOT NULL,
            content     TEXT NOT NULL,
            start_line  INTEGER NOT NULL,
            start_col   INTEGER NOT NULL,
            end_line    INTEGER NOT NULL,
            end_col     INTEGER NOT NULL
        );
        CREATE INDEX idx_chunks_owner ON text_chunks(owner_file);
        CREATE INDEX idx_chunks_entity ON text_chunks(entity_id);

        CREATE VIRTUAL TABLE fts_chunks USING fts5(
            content,
            content='text_chunks',
            content_rowid='id'
        );

        CREATE TRIGGER text_chunks_ai AFTER INSERT ON text_chunks BEGIN
            INSERT INTO fts_chunks(rowid, content) VALUES (new.id, new.content);
        END;
        CREATE TRIGGER text_chunks_ad AFTER DELETE ON text_chunks BEGIN
            INSERT INTO fts_chunks(fts_chunks, rowid, content)
                VALUES ('delete', old.id, old.content);
        END;
        CREATE TRIGGER text_chunks_au AFTER UPDATE ON text_chunks BEGIN
            INSERT INTO fts_chunks(fts_chunks, rowid, content)
                VALUES ('delete', old.id, old.content);
            INSERT INTO fts_chunks(rowid, content) VALUES (new.id, new.content);
        END;
        """,
    ),
]

LATEST_VERSION = MIGRATIONS[-1][0]
