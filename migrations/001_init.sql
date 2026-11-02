-- Data model per plan §6, plus two additions from rev 5:
--   suggestions (§7.3 review queue: possible duplicates, low-confidence updates)
--   thread_messages (§7.3: per-email processed marking, repeat-dropping)
-- Single-user instance: no users table, no row-level security (§6 note).

create table sync_state (
    id                integer primary key default 1 check (id = 1),  -- single row
    last_history_id   text,
    last_full_sync_at timestamptz,
    updated_at        timestamptz not null default now()
);

create table people (
    id           bigint generated always as identity primary key,
    email        text not null unique,
    display_name text,
    aliases      text[] not null default '{}'
);

create table threads (
    id                        bigint generated always as identity primary key,
    gmail_thread_id           text not null unique,
    subject                   text,
    participants              text[] not null default '{}',  -- email addresses
    last_message_at           timestamptz,
    last_extracted_history_id text,
    cached_text               text  -- private instance only (D4); null in the public demo
);

-- One row per message seen in a thread. processed_at null = new/unprocessed.
-- Reconciliation drops extraction quotes sourced from already-processed messages (§7.3).
create table thread_messages (
    gmail_message_id text primary key,
    thread_id        bigint not null references threads(id) on delete cascade,
    internal_date    timestamptz,
    processed_at     timestamptz
);
create index thread_messages_thread_idx on thread_messages(thread_id);

create table tasks (
    id              bigint generated always as identity primary key,
    title           text not null,
    owner_person_id bigint references people(id),
    due_date        date,
    status          text not null default 'open' check (status in ('open', 'done', 'cancelled')),
    confidence      real,
    needs_review    boolean not null default false,
    thread_id       bigint references threads(id),
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);
create index tasks_thread_idx on tasks(thread_id);
create index tasks_owner_idx on tasks(owner_person_id);
create index tasks_status_idx on tasks(status);

create table task_collaborators (
    task_id   bigint not null references tasks(id) on delete cascade,
    person_id bigint not null references people(id),
    primary key (task_id, person_id)
);

create table task_sources (
    id               bigint generated always as identity primary key,
    task_id          bigint not null references tasks(id) on delete cascade,
    gmail_message_id text not null,
    evidence_quote   text not null,
    kind             text not null  -- creation | update | completion | ...
);
create index task_sources_task_idx on task_sources(task_id);

-- The temporal view (§2.1): append-only log of what changed, when, from which message.
create table task_events (
    id                bigint generated always as identity primary key,
    task_id           bigint not null references tasks(id) on delete cascade,
    at                timestamptz not null default now(),
    kind              text not null,  -- created | title_changed | owner_changed | due_changed |
                                      -- status_changed | merged | split | reextracted | ...
    old               jsonb,
    new               jsonb,
    source_message_id text
);
create index task_events_task_idx on task_events(task_id, at);

-- Audit log of proposed and executed writes (§6). tool_call_id is the idempotency key
-- from rev 5 §8.2: recorded before the external call, so a retry never sends twice.
create table actions (
    id           bigint generated always as identity primary key,
    kind         text not null,  -- create_gmail_draft | create_calendar_event | create_google_task
    args         jsonb not null,
    status       text not null default 'proposed'
                 check (status in ('proposed', 'approved', 'executed', 'rejected', 'failed')),
    external_id  text,
    tool_call_id text unique,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

-- Chat state (§6 + rev 5 §8.2): four-state machine with version-checked transitions.
create table chat_sessions (
    id                bigint generated always as identity primary key,
    messages          jsonb not null default '[]',   -- Pydantic AI message history
    pending_approvals jsonb,                          -- DeferredToolRequests payload
    state             text not null default 'idle'
                      check (state in ('idle', 'running', 'awaiting_approval', 'failed')),
    version           integer not null default 0,     -- optimistic concurrency: stale forms no-op
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

-- Review queue (rev 5 §7.3): suggestions never auto-apply; merges happen only on accept.
create table suggestions (
    id            bigint generated always as identity primary key,
    kind          text not null,  -- possible_duplicate | low_confidence_done | ...
    task_id       bigint references tasks(id) on delete cascade,
    other_task_id bigint references tasks(id) on delete cascade,
    payload       jsonb,
    status        text not null default 'pending'
                  check (status in ('pending', 'accepted', 'rejected')),
    created_at    timestamptz not null default now(),
    decided_at    timestamptz
);

-- Full-text search backing search_tasks(query, ...) (§8): plain SQL, no pgvector (§2.2).
alter table tasks
    add column search tsvector
    generated always as (to_tsvector('english', coalesce(title, ''))) stored;
create index tasks_search_idx on tasks using gin(search);

insert into sync_state (id) values (1) on conflict do nothing;
