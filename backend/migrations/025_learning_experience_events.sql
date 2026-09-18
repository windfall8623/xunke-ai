-- Interaction diagnostics only. Authoritative progress stays in learning tables.
CREATE TABLE IF NOT EXISTS learning_experience_events (
    owner_id BIGINT UNSIGNED NOT NULL,
    event_id VARCHAR(64) NOT NULL,
    name VARCHAR(48) NOT NULL,
    course_id VARCHAR(64) NULL,
    lesson_id VARCHAR(64) NULL,
    task_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
    elapsed_ms INT UNSIGNED NULL,
    helpful BOOLEAN NULL,
    body_hash CHAR(64) NOT NULL,
    received_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (owner_id,event_id),
    KEY idx_experience_owner_time (owner_id,received_at),
    KEY idx_experience_retention (received_at),
    FOREIGN KEY (owner_id) REFERENCES users(id),
    CONSTRAINT ck_experience_elapsed CHECK (elapsed_ms IS NULL OR elapsed_ms <= 86400000),
    CONSTRAINT ck_experience_name CHECK (name IN (
        'course_create_viewed','course_create_submitted','lesson_opened',
        'learning_session_finished','task_retry_clicked','response_helpfulness_submitted',
        'content_first_visible','content_stream_interrupted'
    ))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
