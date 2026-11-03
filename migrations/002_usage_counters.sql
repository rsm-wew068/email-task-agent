-- Demo spend control: per-day LLM chat turn counter.
create table usage_counters (
    day date primary key,
    chat_turns integer not null default 0
);
