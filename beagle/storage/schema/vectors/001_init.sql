create virtual table chunk_vectors using vec0(
    chunk_id integer primary key,
    embedding float[{dims}]
);

create virtual table finding_vectors using vec0(
    finding_rowid integer primary key,
    embedding float[{dims}]
);

-- vec0 tables hold no text, so keep the join keys for finding suppression here.
create table finding_vector_keys (
    rowid_ref   integer primary key,
    finding_id  text not null unique,
    fingerprint text not null,
    category    text not null,
    created_at  text not null
);
