-- Bounded, owner-private previews. Redis carries wakeups, never this content.
CREATE TABLE IF NOT EXISTS task_content_heads (
    task_id VARCHAR(64) PRIMARY KEY,
    owner_id BIGINT UNSIGNED NOT NULL,
    attempt INT UNSIGNED NOT NULL,
    generation_revision INT UNSIGNED NOT NULL,
    seq INT UNSIGNED NOT NULL DEFAULT 0,
    byte_count INT UNSIGNED NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    closed_at DATETIME(6) NULL,
    KEY idx_content_owner (owner_id,task_id),
    KEY idx_content_retention (closed_at),
    FOREIGN KEY (task_id,owner_id) REFERENCES quiz_tasks(task_id,user_id),
    CONSTRAINT ck_content_head_status CHECK (status IN ('active','finalized','unavailable'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS task_content_frames (
    task_id VARCHAR(64) NOT NULL,
    owner_id BIGINT UNSIGNED NOT NULL,
    attempt INT UNSIGNED NOT NULL,
    generation_revision INT UNSIGNED NOT NULL,
    seq INT UNSIGNED NOT NULL,
    payload_json JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (task_id,attempt,generation_revision,seq),
    KEY idx_content_frames_owner (owner_id,task_id),
    FOREIGN KEY (task_id) REFERENCES task_content_heads(task_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
