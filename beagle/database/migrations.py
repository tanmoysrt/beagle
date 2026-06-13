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
    (
        2,
        # Temporal decision and change memory (design/13). These tables are
        # deliberately NOT keyed on owner_file: they record history that must
        # survive reindexing, so connection._OWNED_TABLES never purges them.
        """
        CREATE TABLE temporal_episodes (
            id           TEXT PRIMARY KEY,
            title        TEXT NOT NULL,
            status       TEXT NOT NULL,
            created_at   REAL NOT NULL,
            updated_at   REAL NOT NULL,
            base_commit  TEXT,
            head_commit  TEXT,
            branch       TEXT,
            summary      TEXT,
            problem      TEXT,
            goal         TEXT,
            outcome      TEXT,
            confidence   REAL,
            confirmation TEXT NOT NULL DEFAULT 'generated',
            provenance_json TEXT
        );

        CREATE TABLE temporal_sessions (
            id                TEXT PRIMARY KEY,
            episode_id        TEXT,
            tool              TEXT,
            started_at        REAL,
            ended_at          REAL,
            working_directory TEXT,
            start_commit      TEXT,
            end_commit        TEXT,
            transcript_path   TEXT,
            transcript_hash   TEXT,
            summary           TEXT,
            redaction_status  TEXT
        );

        CREATE TABLE temporal_decisions (
            id            TEXT PRIMARY KEY,
            episode_id    TEXT,
            statement     TEXT NOT NULL,
            rationale     TEXT,
            status        TEXT NOT NULL,
            confidence    REAL,
            created_at    REAL NOT NULL,
            superseded_by TEXT,
            confirmation  TEXT NOT NULL DEFAULT 'generated',
            provenance_json TEXT
        );

        CREATE TABLE temporal_alternatives (
            id               TEXT PRIMARY KEY,
            episode_id       TEXT,
            description      TEXT NOT NULL,
            status           TEXT NOT NULL,
            rejection_reason TEXT,
            provenance_json  TEXT
        );

        CREATE TABLE temporal_commits (
            commit_sha       TEXT PRIMARY KEY,
            episode_id       TEXT,
            parent_shas      TEXT,
            message          TEXT,
            author           TEXT,
            timestamp        REAL,
            patch_id         TEXT,
            match_confidence REAL
        );

        CREATE TABLE temporal_entity_changes (
            id              INTEGER PRIMARY KEY,
            episode_id      TEXT,
            commit_sha      TEXT,
            entity_before   TEXT,
            entity_after    TEXT,
            change_type     TEXT NOT NULL,
            path_before     TEXT,
            path_after      TEXT,
            diff_ranges_json TEXT,
            confidence      REAL
        );

        CREATE TABLE temporal_changesets (
            id                 TEXT PRIMARY KEY,
            episode_id         TEXT,
            base_commit        TEXT,
            head_commit        TEXT,
            patch_id           TEXT,
            entity_fingerprint TEXT,
            summary            TEXT
        );

        CREATE TABLE temporal_test_results (
            id                TEXT PRIMARY KEY,
            episode_id        TEXT,
            command           TEXT,
            status            TEXT,
            started_at        REAL,
            finished_at       REAL,
            output_summary    TEXT,
            source_session_id TEXT
        );

        CREATE TABLE temporal_followups (
            id               TEXT PRIMARY KEY,
            episode_id       TEXT,
            description      TEXT NOT NULL,
            status           TEXT,
            priority         TEXT,
            related_entities TEXT
        );

        CREATE INDEX idx_tchanges_episode ON temporal_entity_changes(episode_id);
        CREATE INDEX idx_tchanges_after   ON temporal_entity_changes(entity_after);
        CREATE INDEX idx_tchanges_before  ON temporal_entity_changes(entity_before);
        CREATE INDEX idx_tchanges_commit  ON temporal_entity_changes(commit_sha);
        CREATE INDEX idx_tcommits_episode ON temporal_commits(episode_id);
        CREATE INDEX idx_tdecisions_episode ON temporal_decisions(episode_id);
        CREATE INDEX idx_talternatives_episode ON temporal_alternatives(episode_id);
        CREATE INDEX idx_tfollowups_episode ON temporal_followups(episode_id);
        """,
    ),
]

LATEST_VERSION = MIGRATIONS[-1][0]
