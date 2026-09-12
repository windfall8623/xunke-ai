-- Task public phase events for durable cursor-replayable progress records.
-- MySQL stays the source of truth and Redis notifications stay best-effort only.
-- @column quiz_tasks public_event_seq
ALTER TABLE quiz_tasks ADD COLUMN public_event_seq INT UNSIGNED NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS task_public_events (
    task_id VARCHAR(64) NOT NULL,
    owner_id BIGINT UNSIGNED NOT NULL,
    seq INT UNSIGNED NOT NULL,
    attempt INT UNSIGNED NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    payload_json JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (task_id, seq),
    KEY idx_task_events_read (owner_id, task_id, seq),
    KEY idx_task_events_cleanup (created_at, task_id, seq)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
