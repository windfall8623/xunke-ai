-- Weekly summaries read existing tables only (B07)
-- Reminder preferences and deliveries persist here, never a second copy of grades.
CREATE TABLE IF NOT EXISTS learning_reminder_preferences (
 owner_id BIGINT UNSIGNED PRIMARY KEY,
 in_app_enabled BOOLEAN NOT NULL DEFAULT FALSE,
 email_enabled BOOLEAN NOT NULL DEFAULT FALSE,
 frequency VARCHAR(16) NOT NULL DEFAULT 'weekly',
 local_time VARCHAR(8) NOT NULL DEFAULT '09:00',
 timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
 paused_until DATETIME(6) NULL,
 revision INT NOT NULL DEFAULT 1,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 FOREIGN KEY (owner_id) REFERENCES users(id),
 CONSTRAINT ck_reminder_pref_frequency CHECK (frequency IN ('daily_due','weekly')),
 CONSTRAINT ck_reminder_pref_time CHECK (local_time REGEXP '^([01][0-9]|2[0-3]):[0-5][0-9]$'),
 CONSTRAINT ck_reminder_pref_revision CHECK (revision>=1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_reminders (
 reminder_id VARCHAR(64) PRIMARY KEY,
 owner_id BIGINT UNSIGNED NOT NULL,
 kind VARCHAR(32) NOT NULL,
 title VARCHAR(200) NOT NULL,
 body VARCHAR(500) NULL,
 link_path VARCHAR(200) NULL,
 due_at DATETIME(6) NULL,
 read_at DATETIME(6) NULL,
 send_after DATETIME(6) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 KEY idx_learning_reminder_owner (owner_id,created_at),
 FOREIGN KEY (owner_id) REFERENCES users(id),
 CONSTRAINT ck_learning_reminder_kind CHECK (kind IN ('weekly_summary','due_review','course_event'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_reminder_outbox (
 delivery_id VARCHAR(64) PRIMARY KEY,
 owner_id BIGINT UNSIGNED NOT NULL,
 identity_key CHAR(64) NOT NULL,
 channel VARCHAR(8) NOT NULL,
 status VARCHAR(12) NOT NULL DEFAULT 'pending',
 attempts INT NOT NULL DEFAULT 0,
 last_error_code VARCHAR(48) NULL,
 scheduled_for DATETIME(6) NOT NULL,
 payload_json JSON NULL,
 sent_at DATETIME(6) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_learning_outbox_identity (owner_id,identity_key,channel),
 KEY idx_learning_outbox_due (status,scheduled_for,delivery_id),
 FOREIGN KEY (owner_id) REFERENCES users(id),
 CONSTRAINT ck_learning_outbox_channel CHECK (channel IN ('in_app','email')),
 CONSTRAINT ck_learning_outbox_status CHECK (status IN ('pending','sent','failed','cancelled')),
 CONSTRAINT ck_learning_outbox_attempts CHECK (attempts>=0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
