-- Initial schema for ombench.
--
-- The relational store holds metadata and indexes. Large payloads live in the
-- content addressed blob store and are referenced here by their hash. Time
-- columns are ISO 8601 UTC strings, which sort lexically in the same order as
-- chronologically, so range scans on valid_at and ingested_at are correct.

-- ---------------------------------------------------------------------------
-- Canonical append only bitemporal event log.
--
-- This is the source of truth for app history. Nothing is ever updated or
-- deleted. State as of a bitemporal point is computed by folding the subset of
-- events with valid_at <= T and ingested_at <= tau.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_events (
    event_id          TEXT PRIMARY KEY,
    app               TEXT NOT NULL,            -- slack | gcal | gdocs | drive | gmail
    entity_type       TEXT NOT NULL,            -- message | channel | event | document | ...
    entity_id         TEXT NOT NULL,
    op                TEXT NOT NULL,            -- upsert_entity | delete_entity | ...
    payload_hash      TEXT,                     -- blob hash of the normalized payload
    valid_at          TEXT NOT NULL,            -- when it took effect in the source app
    ingested_at       TEXT NOT NULL,            -- when ombench learned it
    actor_ref         TEXT,
    parent_entity_ref TEXT,
    source_cursor     TEXT,                     -- sync token, page token, historyId, ts
    provenance_hash   TEXT,                     -- blob hash of the provenance record
    seq               INTEGER,                  -- monotonic ingest sequence, tie breaker
    edge_target       TEXT,                     -- target id for edge operations
    edge_kind         TEXT                      -- relationship kind for edge operations
);

CREATE INDEX IF NOT EXISTS idx_events_entity
    ON app_events (app, entity_type, entity_id, valid_at);
CREATE INDEX IF NOT EXISTS idx_events_app_valid
    ON app_events (app, valid_at);
CREATE INDEX IF NOT EXISTS idx_events_ingested
    ON app_events (ingested_at);
CREATE INDEX IF NOT EXISTS idx_events_seq
    ON app_events (seq);

-- Per stream ingest cursors so incremental sync can resume. One row per
-- (app, stream) such as a Slack channel or a Calendar id.
CREATE TABLE IF NOT EXISTS sync_cursors (
    app          TEXT NOT NULL,
    stream       TEXT NOT NULL,
    cursor       TEXT,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (app, stream)
);

-- ---------------------------------------------------------------------------
-- Trajectory capture: runs and spans.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trace_runs (
    trace_id      TEXT PRIMARY KEY,
    group_id      TEXT,
    workflow_name TEXT,
    agent         TEXT,                         -- claude_code | codex | ...
    started_at    TEXT,
    ended_at      TEXT,
    user_ref      TEXT,
    task_ref      TEXT,
    status        TEXT,
    payload_hash  TEXT,                         -- blob hash of the full trajectory doc
    ingested_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trace_spans (
    span_id        TEXT PRIMARY KEY,
    trace_id       TEXT NOT NULL,
    parent_id      TEXT,
    kind           TEXT NOT NULL,               -- AGENT | LLM | TOOL | RETRIEVER | ...
    name           TEXT,
    started_at     TEXT,
    ended_at       TEXT,
    status         TEXT,
    input_ref      TEXT,                        -- blob hash
    output_ref     TEXT,                        -- blob hash
    tool_name      TEXT,
    attributes_hash TEXT,                       -- blob hash of the attribute bag
    tokens         INTEGER,
    cost_usd       REAL,
    FOREIGN KEY (trace_id) REFERENCES trace_runs (trace_id)
);

CREATE INDEX IF NOT EXISTS idx_spans_trace ON trace_spans (trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_kind ON trace_spans (kind);

-- App references attached to spans, the join between trajectories and app state.
CREATE TABLE IF NOT EXISTS span_app_refs (
    span_id     TEXT NOT NULL,
    app         TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    FOREIGN KEY (span_id) REFERENCES trace_spans (span_id)
);

CREATE INDEX IF NOT EXISTS idx_span_app_refs ON span_app_refs (app, entity_type, entity_id);

-- ---------------------------------------------------------------------------
-- Snapshot manifests: materialized point in time roots.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS snapshot_manifests (
    snapshot_id        TEXT PRIMARY KEY,
    app                TEXT NOT NULL,
    as_of_valid_time   TEXT NOT NULL,
    as_of_ingest_time  TEXT NOT NULL,
    root_hash          TEXT NOT NULL,           -- merkle root over entity version hashes
    manifest_hash      TEXT NOT NULL,           -- blob hash of the full manifest doc
    entity_count       INTEGER NOT NULL,
    created_at         TEXT NOT NULL,
    label              TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_app ON snapshot_manifests (app, as_of_valid_time);

-- ---------------------------------------------------------------------------
-- Compiled memory items. Append only: contradictions are represented by edges,
-- never by in place updates.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_items (
    memory_id     TEXT PRIMARY KEY,
    type          TEXT NOT NULL,                -- episodic | semantic | procedural
    namespace     TEXT NOT NULL,                -- user | team | project | app_state
    subject       TEXT,
    claim         TEXT NOT NULL,
    confidence    REAL NOT NULL,
    ttl_policy    TEXT,
    acl           TEXT,
    evidence_hash TEXT,                          -- blob hash of evidence refs
    content_hash  TEXT NOT NULL,                 -- dedupe key for the claim
    created_at    TEXT NOT NULL,
    valid_at      TEXT,
    active        INTEGER NOT NULL DEFAULT 1     -- resolver flag, not a delete
);

CREATE INDEX IF NOT EXISTS idx_memory_ns ON memory_items (namespace, type);
CREATE INDEX IF NOT EXISTS idx_memory_active ON memory_items (active);

-- Edges between memory items: supersedes, contradicts, supports, derived_from.
CREATE TABLE IF NOT EXISTS memory_edges (
    src_id    TEXT NOT NULL,
    dst_id    TEXT NOT NULL,
    relation  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (src_id, dst_id, relation)
);

-- ---------------------------------------------------------------------------
-- Benchmark tasks and replay results.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS task_specs (
    task_id        TEXT PRIMARY KEY,
    snapshot_ref   TEXT,
    prompt         TEXT NOT NULL,
    rubric_id      TEXT,
    spec_hash      TEXT NOT NULL,                -- blob hash of the full spec
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS replay_results (
    result_id      TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL,
    condition      TEXT NOT NULL,                -- with_memory | without_memory
    trace_id       TEXT,
    scores_hash    TEXT,                         -- blob hash of the rubric scores
    rubric_total   REAL,
    success        INTEGER,
    invalid_actions INTEGER,
    latency_seconds REAL,
    token_cost_usd REAL,
    created_at     TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES task_specs (task_id)
);

CREATE INDEX IF NOT EXISTS idx_results_task ON replay_results (task_id, condition);
