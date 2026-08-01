create table files (
    id            integer primary key,
    path          text    not null unique,
    lang          text,
    blob_sha      text    not null,
    content_hash  text    not null,
    size_bytes    integer not null,
    indexed_at    text    not null
);

create table symbols (
    id             integer primary key,
    file_id        integer not null references files(id) on delete cascade,
    parent_id      integer references symbols(id) on delete cascade,
    name           text    not null,
    qualified_name text    not null,
    kind           text    not null,
    lang           text    not null,
    signature      text,
    start_line     integer not null,
    end_line       integer not null,
    start_byte     integer not null,
    end_byte       integer not null
);
create index symbols_file on symbols(file_id);
create index symbols_name on symbols(name);
create index symbols_qname on symbols(qualified_name);

create table imports (
    id       integer primary key,
    file_id  integer not null references files(id) on delete cascade,
    module   text    not null,
    symbol   text,
    alias    text,
    line     integer
);
create index imports_file on imports(file_id);
create index imports_module on imports(module);

-- dst_symbol_id is null while a callee is unresolved, or once the file that
-- owned it is reindexed; dst_name always survives so text matching still works.
create table symbol_edges (
    id            integer primary key,
    src_symbol_id integer not null references symbols(id) on delete cascade,
    dst_symbol_id integer references symbols(id) on delete set null,
    dst_name      text    not null,
    kind          text    not null,
    resolution    text    not null,
    line          integer
);
create index edges_src on symbol_edges(src_symbol_id);
create index edges_dst on symbol_edges(dst_symbol_id);
create index edges_name on symbol_edges(dst_name);

create table chunks (
    id             integer primary key,
    file_id        integer not null references files(id) on delete cascade,
    symbol_id      integer references symbols(id) on delete set null,
    path           text    not null,
    start_line     integer not null,
    end_line       integer not null,
    content_hash   text    not null,
    token_estimate integer not null default 0,
    embedded       integer not null default 0,
    body           text    not null
);
create index chunks_file on chunks(file_id);
create index chunks_pending on chunks(embedded);
create unique index chunks_identity on chunks(path, content_hash);

create table reviews (
    id           text primary key,
    base_sha     text,
    head_sha     text,
    status       text not null default 'queued',
    verdict      text,
    confidence   real,
    coverage     real,
    description  text,
    summary_json text,
    cost_usd     real default 0,
    tokens_in    integer default 0,
    tokens_out   integer default 0,
    created_at   text not null,
    completed_at text
);

create table findings (
    id             text primary key,
    review_id      text not null references reviews(id) on delete cascade,
    fingerprint    text not null,
    file           text not null,
    line_start     integer,
    line_end       integer,
    category       text not null,
    severity       text not null,
    model_severity text,
    confidence     real,
    app_code       integer,
    title          text not null,
    body           text not null,
    suggested_patch text,
    context_used   text,
    metadata_json  text,
    status         text not null default 'open',
    created_at     text not null
);
create index findings_review on findings(review_id);
create index findings_fingerprint on findings(fingerprint);

create table feedback (
    id          integer primary key,
    finding_id  text references findings(id) on delete set null,
    fingerprint text,
    action      text not null,
    reason      text,
    author      text,
    weight      real not null default 1.0,
    created_at  text not null
);
create index feedback_fingerprint on feedback(fingerprint);

create table rules (
    id         text primary key,
    body       text not null,
    author     text,
    hits       integer not null default 0,
    active     integer not null default 1,
    created_at text not null
);

create table jobs (
    id           integer primary key,
    kind         text not null,
    payload_json text not null,
    review_id    text,
    status       text not null default 'queued',
    attempts     integer not null default 0,
    error        text,
    created_at   text not null,
    started_at   text,
    finished_at  text
);
create index jobs_status on jobs(status, id);

create table github_sync (
    key        text primary key,
    value      text,
    updated_at text
);

create table config_stamps (
    key        text primary key,
    value      text,
    updated_at text
);

create table index_state (
    key        text primary key,
    value      text,
    updated_at text
);
