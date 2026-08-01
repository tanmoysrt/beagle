create table llm_calls (
    id                 integer primary key,
    request_hash       text not null,
    prompt_name        text,
    prompt_set_version text,
    model              text not null,
    tokens_in          integer default 0,
    tokens_out         integer default 0,
    tokens_cached      integer default 0,
    cost_usd           real    default 0,
    latency_ms         integer,
    ok                 integer not null default 1,
    error              text,
    review_id          text,
    unit               text,
    request_json       text not null,
    response_json      text,
    created_at         text not null
);
create index llm_calls_review on llm_calls(review_id);
create index llm_calls_hash on llm_calls(request_hash);
create index llm_calls_created on llm_calls(created_at);
