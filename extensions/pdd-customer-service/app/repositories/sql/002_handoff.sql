CREATE TABLE conversation_handoff_states (
    shop_id TEXT NOT NULL,
    buyer_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (
        mode IN ('AI', 'WAITING_HUMAN', 'HUMAN', 'CLOSED')
    ),
    risk_level TEXT NOT NULL CHECK (
        risk_level IN ('low', 'medium', 'high', 'critical')
    ),
    reason_code TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (shop_id, buyer_id, conversation_id)
);

CREATE TABLE handoff_queue (
    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id TEXT NOT NULL,
    buyer_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('waiting', 'claimed', 'closed')
    ),
    reason_code TEXT NOT NULL,
    risk_level TEXT NOT NULL CHECK (
        risk_level IN ('low', 'medium', 'high', 'critical')
    ),
    created_at TEXT NOT NULL,
    claimed_by TEXT,
    claimed_at TEXT,
    closed_at TEXT
);

CREATE UNIQUE INDEX idx_handoff_open_conversation
ON handoff_queue (shop_id, buyer_id, conversation_id)
WHERE status IN ('waiting', 'claimed');

CREATE INDEX idx_handoff_queue_status
ON handoff_queue (status, queue_id);

CREATE TABLE handoff_audit_events (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id TEXT NOT NULL,
    buyer_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    event TEXT NOT NULL,
    from_mode TEXT,
    to_mode TEXT NOT NULL,
    reason_code TEXT,
    risk_level TEXT NOT NULL CHECK (
        risk_level IN ('low', 'medium', 'high', 'critical')
    ),
    operator TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_handoff_audit_conversation
ON handoff_audit_events (
    shop_id,
    buyer_id,
    conversation_id,
    audit_id
);

PRAGMA user_version = 2;
