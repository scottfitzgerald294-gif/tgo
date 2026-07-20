CREATE TABLE inbox_messages (
    inbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    buyer_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    content TEXT NOT NULL,
    received_at TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    inbound_recorded INTEGER NOT NULL DEFAULT 0,
    conversation_created INTEGER NOT NULL DEFAULT 0,
    UNIQUE (shop_id, message_id)
);

CREATE TABLE outbox_messages (
    reply_id TEXT PRIMARY KEY,
    inbox_id INTEGER NOT NULL UNIQUE REFERENCES inbox_messages(inbox_id),
    reply_timestamp TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'sent', 'failed', 'retrying', 'dead_letter')
    ),
    attempts INTEGER NOT NULL DEFAULT 0,
    retryable INTEGER NOT NULL DEFAULT 1,
    last_reason TEXT,
    next_attempt_at TEXT,
    lease_epoch INTEGER
);

CREATE TABLE reply_leases (
    shop_id TEXT NOT NULL,
    buyer_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    owner TEXT NOT NULL CHECK (owner IN ('ai', 'human')),
    epoch INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (shop_id, buyer_id, conversation_id)
);

CREATE TABLE audit_events (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    inbox_id INTEGER REFERENCES inbox_messages(inbox_id),
    trace_id TEXT NOT NULL,
    event TEXT NOT NULL,
    status TEXT CHECK (
        status IS NULL OR
        status IN ('pending', 'sent', 'failed', 'retrying', 'dead_letter')
    ),
    attempt INTEGER NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_outbox_recovery
    ON outbox_messages (status, retryable, next_attempt_at);

CREATE INDEX idx_audit_inbox
    ON audit_events (inbox_id, audit_id);

PRAGMA user_version = 1;
